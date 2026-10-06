/**
 * @file main.cpp
 * @brief isolation-sphere solo: 外部 server 無しで球体単独再生するファームウェア
 *
 * 起動すると SoftAP を立て、LittleFS 上の raw MJPEG (320x160, 10fps) を自動ループ再生する。
 * 操作は iPhone を AP に接続 (個体シールの QR) し、Web UI (http://192.168.4.1/) で行う。
 *
 * server モード (config.json wifi{} 有効時) では同じファームが P2P 網にも STA で入り、
 * UDP で届く JPEG を優先表示し、MQTT で操作を受ける (配信が途切れるとローカル再生に戻る)。
 *
 * タスク構成:
 *   Core0: WiFi/lwIP, async_udp (受信→キュー), frame_pump (UDP 再構成 or ローカル MJPEG 読み
 *          → JPEG デコード。デコードは必ずこのタスク), httpd (Web UI/アップロード)
 *   Core1: LED_Render (IMU姿勢で毎パス再マッピング + RMT出力), imu (100Hz),
 *          loopTask (本ファイルの loop: OTA/ネットワーク/MQTT/ログ)
 */

#include <Arduino.h>
#include <WiFi.h>
#include "common.h"
#include "FileManager.h"
#include "ConfigManager.h"
#include "NetworkManager.h"
#include "IMUManager.h"
#include "GestureManager.h"
#include "SoundManager.h"
#include "ImageManager.h"
#include "LEDManager.h"
#include "OtaManager.h"
#include "Settings.h"

#include "SoloPlayer.h"
#include "SoloWebServer.h"
#include "DeviceController.h"
#include "SerialConsole.h"
#include "FramePump.h"
#include "UdpReceiver.h"
#include "MQTTManager.h"
#include "MqttTopics.h"
#include "CommandHandler.h"
#include "TimeSync.h"
#include "Telemetry.h"

using namespace sastle;

// グローバルデバッグフラグ (common.hでextern宣言)
bool g_debugEnabled = false;

ConfigManager config;
NetworkManager network;
IMUManager imuSensor;
GestureManager gesture;
SoundManager sound;
ImageManager imageManager;
LEDManager ledManager;
OtaManager ota;
SoloPlayer soloPlayer;
SoloWebServer soloWeb;
DeviceController controller;   // HTTP / MQTT / コンソールが共通で呼ぶ操作の窓口
SerialConsole console;
UdpReceiver udpRx;             // UDP 映像チャンク受信 (server モード時のみ listen)
FramePump pump;                // フレーム供給の単一タスク (UDP 再構成 / ローカル再生 → デコード)
MQTTManager mqtt;              // server モード: 操作受信 / imu・state・log 送信 (broker 設定時のみ)
CommandHandler commandHandler; // MQTT コマンド → DeviceController
TimeSync timeSync;             // sphere/all/clock からの共通タイムベース
Telemetry telemetry;           // imu / state の周期 publish

// MQTT メッセージ受信コールバック (mqtt.loop() 経由で loopTask のみが呼ぶ)
static void mqttCallback(char* topic, uint8_t* payload, unsigned int length) {
    // 重要: PubSubClient は送受信で同一バッファを使う。コールバック内で publish
    // (= Log の MQTT 送出やコマンド応答) を行うと受信中の topic/payload が上書き破損する。
    // 先にローカルへ退避してから処理する。2KB はスタックに積まず static。
    char topicCopy[128];
    strncpy(topicCopy, topic, sizeof(topicCopy) - 1);
    topicCopy[sizeof(topicCopy) - 1] = '\0';
    static char payloadCopy[sastle::kMqttBufferSize];
    const unsigned int len = (length < sizeof(payloadCopy) - 1) ? length : sizeof(payloadCopy) - 1;
    memcpy(payloadCopy, payload, len);
    payloadCopy[len] = '\0';

    // 時刻同期ビーコン (1 秒周期) は command 判定より先に捌き、ログも出さない
    if (strcmp(topicCopy, sastle::topics::kAllClock) == 0) {
        timeSync.onClockMessage(payloadCopy);
        return;
    }
    if (strstr(topicCopy, "/command/") != nullptr) {
        sastle::Log.printf("[MQTT] <- %s\n", topicCopy);
        commandHandler.handleMessage(topicCopy, (uint8_t*)payloadCopy, len);
    } else {
        sastle::Log.printf("[MQTT] unhandled topic %s: %s\n", topicCopy, payloadCopy);
    }
}

// 接続案内の文字列 (LCD が無いので起動ログにだけ出す。QR は個体シールで渡す: tools/make_wifi_qr.py)
static String g_wifiQrText;
static String g_apSsid;
static String g_uiUrl;

unsigned long lastIMULog = 0;
const unsigned long IMU_LOG_INTERVAL = 3000; // 3秒に1回ログ出力
unsigned long lastPerfLog = 0;
const unsigned long PERF_LOG_INTERVAL = 2000; // 2秒に1回 性能計測ログ

// Grove I2C バスを走査して検出アドレスを出す (診断用)。
// BNO055 は ADR ピンにより 0x28 (L) / 0x29 (H) に応答する。
static void scanI2cBus(uint8_t sda, uint8_t scl) {
    // 100kHz で走査する。BNO055 はクロックストレッチが長く 400kHz では化ける。
    // Wire.begin は 2 回目以降は周波数を再設定しないため、ここが実効クロックになる。
    Wire.begin(sda, scl, 100000);
    delay(50);

    sastle::Log.printf("\n[I2C] Scanning bus (SDA=GPIO%u, SCL=GPIO%u)\n", sda, scl);

    int found = 0;
    bool bnoFound = false;
    for (uint8_t addr = 0x08; addr <= 0x77; ++addr) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            ++found;
            const bool isBno = (addr == 0x28 || addr == 0x29);
            if (isBno) {
                bnoFound = true;
            }
            sastle::Log.printf("[I2C]   found 0x%02X%s\n", addr, isBno ? "  <- BNO055" : "");
            delay(2);
        }
    }

    sastle::Log.printf("[I2C] Scan done: %d device(s), BNO055(0x28/0x29)=%s\n",
                       found, bnoFound ? "PRESENT" : "ABSENT");
}

void setup() {
    // 最優先: LED即時消灯。WS2812は起動中のデータ線ノイズでランダム点灯
    // (白=フル電流もあり得る) し、電源が引き倒されて起動に失敗する事象があるため、
    // 何よりも先に全ストリップへ黒を送信する。
    LEDManager::earlyBlank();

    // シリアル初期化。Log の退避バッファ (PSRAM) も同時に用意する。server モードで MQTT に
    // 繋がると、ここ以降の起動ログがまとめて sphere/<id>/log に流れる。
    Serial.begin(115200);
    sastle::Log.begin();

    // Sound初期化を最優先で行い、起動音を即再生する。
    // 理由: WiFi/IMU初期化が終わるまでLED表示は数秒かかるため、
    // 電源スイッチが正しくONになったかをすぐ確認できるよう、
    // 他の初期化より前に音でフィードバックする。
    bool soundReady = sound.begin(config);
    if (soundReady) {
        sound.playEffect(SoundEffect::STARTUP);
    }

    // シリアルモニタ接続待ち。USB ホストが繋がっているときだけ短く待つ (起動ログの先頭を
    // 取りこぼさないため)。電池駆動 (ホスト無し) では待たない。
    if (Serial.isConnected()) {
        delay(300);
    }

    if (!soundReady) {
        sastle::Log.println("Sound initialization failed (continuing without sound)");
    }

    sastle::Log.println("\n\n=== Isolation Sphere (solo) ===");

    // 直前のリセット理由を記録 (勝手な再起動の原因切り分け用)
    // 1=POWERON 3=SW 4=PANIC 5/6=WDT 7=TASK_WDT 9=BROWNOUT (esp_reset_reason_t)
    {
        esp_reset_reason_t rr = esp_reset_reason();
        const char* rrName;
        switch (rr) {
            case ESP_RST_POWERON:  rrName = "POWERON"; break;
            case ESP_RST_SW:       rrName = "SW_RESTART"; break;
            case ESP_RST_PANIC:    rrName = "PANIC"; break;
            case ESP_RST_INT_WDT:  rrName = "INT_WDT"; break;
            case ESP_RST_TASK_WDT: rrName = "TASK_WDT"; break;
            case ESP_RST_WDT:      rrName = "WDT"; break;
            case ESP_RST_BROWNOUT: rrName = "BROWNOUT"; break;
            case ESP_RST_DEEPSLEEP:rrName = "DEEPSLEEP"; break;
            default:               rrName = "OTHER"; break;
        }
        sastle::Log.printf("[BOOT] Reset reason: %d (%s)\n", (int)rr, rrName);
    }

    // PSRAM初期化確認
    if (psramFound()) {
        sastle::Log.printf("PSRAM found: %d bytes\n", ESP.getPsramSize());
        sastle::Log.printf("Free PSRAM: %d bytes\n", ESP.getFreePsram());
    } else {
        sastle::Log.println("PSRAM not found");
    }

    // LittleFS初期化
    sastle::Log.println("\n=== Initializing LittleFS ===");
    // LittleFS が壊れていても停止しない。SoftAP と OTA を必ず立ち上げ、無線で書き戻せる
    // 状態を保つ (組み立て後は USB 端子に触れないため、ここで止まると復旧手段が無くなる)。
    const bool fsReady = FileManager::begin();
    if (!fsReady) {
        sastle::Log.println("FileManager initialization FAILED "
                            "(no video / uploads disabled, but SoftAP+OTA will start)");
    } else {
        FileManager::printInfo();
    }

    // ConfigManager初期化とロード
    sastle::Log.println("\n=== Loading Configuration ===");
    // 同様に、設定が読めなくても停止しない。ConfigManager の各 getter は
    // コンパイル時の既定値 (320x160 / SoftAP 既定 SSID など) を返す。
    if (!fsReady || !config.loadConfig("/config.json")) {
        sastle::Log.println("Failed to load config (using compiled-in defaults)");
    }
    config.printConfig();

    // UI で変えた設定 (明るさ等) を NVS から復元する
    sastle::Settings::begin();

    // Wi-Fi を立てる: STA (NVS の LAN > config の P2P 網) を先行させ、SoftAP を常に立てる。
    // 失敗しても停止しない (動画があれば iPhone 無しでも自動再生する要件)。
    SoloConfig soloCfg = config.getSoloConfig();
    IPAddress apIp;
    if (!apIp.fromString(soloCfg.ap_ip)) {
        apIp = IPAddress(192, 168, 4, 1);
    }
    // 省電力設定 (モデム省電力 / AP 無操作自動停止) は無線を立てる前に入れる。
    network.setModemSleep(sastle::Settings::modemSleep(false));
    network.setApIdleTimeoutMin(sastle::Settings::apIdleMinutes(DeviceController::kDefaultApIdleMin));
    if (!network.begin(config)) {
        sastle::Log.println("SoftAP start FAILED (playback continues without Web UI)");
    }
    // 起動ログに出す接続情報 (シール用 QR の元になる文字列)。
    g_apSsid = soloCfg.ap_ssid;
    g_wifiQrText = NetworkManager::wifiQrText(soloCfg.ap_ssid, soloCfg.ap_password);
    g_uiUrl = "http://" + apIp.toString() + "/";
    sastle::Log.printf("[SOLO] Wi-Fi QR: %s  UI: %s\n", g_wifiQrText.c_str(), g_uiUrl.c_str());

    // OTA (espota) 初期化: AP が立った直後に受け口を開く。これ以降の初期化
    // (IMU / LED / 再生 / Web) で失敗・停止しても、無線での書き戻しは生き残る。
    // stopRenderTask() は _taskRunning ガードがあるため未初期化でも安全。
    ota.begin(&ledManager, &pump, &soloPlayer, config.getSphereID().c_str(), &mqtt);

    // IMU初期化前に I2C バスを走査 (BNO055 の有無を切り分けるため)
    scanI2cBus(kImuI2cSda, kImuI2cScl);

    // IMU初期化
    if (!imuSensor.begin(config)) {
        sastle::Log.println("IMU initialization failed (continuing without IMU)");
    } else {
        imuSensor.setSmoothFrames(sastle::Settings::imuSmoothFrames(config.getImuSmoothFrames()));
        sastle::Log.printf("IMU smoothing: %u frame(s)\n", imuSensor.smoothFrames());
        imuSensor.printStatus();
    }

    // ジェスチャー初期化 (サウンドフィードバック付き)
    if (imuSensor.isInitialized()) {
        if (!gesture.begin(imuSensor, &sound)) {
            sastle::Log.println("Gesture initialization failed");
        }
    } else {
        sastle::Log.println("Gesture disabled (IMU not available)");
    }

    // ImageManager初期化 (PSRAM トリプルバッファ)
    if (!imageManager.begin(config)) {
        sastle::Log.println("ImageManager initialization failed (continuing without image)");
    } else {
        imageManager.printStats();

        // フレーム供給タスク (Core0)。UDP 受信より先に立てる: server は球体の MQTT status を
        // 見た瞬間に配信を始めるので、受け側 (キュー + デコード) が先に居ないと起動直後の
        // フラッドで詰まる (派生元の知見)。server 無効時は単にローカル再生の締切を回す。
        FramePump::Deps pd;
        pd.image = &imageManager;
        pd.player = &soloPlayer;
        pd.udp = &udpRx;
        if (pump.begin(pd, config.getSourceConfig())) {
            // 優先度 2: httpd (prio 1) より上にして、/api/status の JSON 組み立てや
            // アップロード受信にデコードが割り込まれないようにする (締切 100ms の保護)
            pump.startTask(0, 2, 8192);
        } else {
            sastle::Log.println("FramePump initialization failed (no frame source)");
        }
        if (config.isServerConfigured()) {
            // listen は ANY にバインドするので STA 接続前でも開ける
            const WiFiConfig wcfg = config.getWiFiConfig();
            if (!udpRx.begin((uint16_t)wcfg.udp_port, config.getSourceConfig().udp_queue_len)) {
                sastle::Log.println("UDP receiver failed to start (network video disabled)");
            }
        }

        // ローカル動画を開く (動画全体を PSRAM に読み込む。3MB で数秒)。描画タスクを起動する前に
        // 行い、フラッシュ操作ロックの取り合いで読み込みが遅くなるのを避ける。
        if (!soloPlayer.begin(config, imageManager)) {
            sastle::Log.println("SoloPlayer initialization failed");
        }
    }

    // LEDManager初期化 (IMUManager連携)
    if (imageManager.isInitialized()) {
        IMUManager* imuPtr = imuSensor.isInitialized() ? &imuSensor : nullptr;
        if (!ledManager.begin(config, imageManager, imuPtr)) {
            sastle::Log.println("LEDManager initialization failed (continuing without LED)");
        } else {
            ledManager.printStatus();

            // 起動オープニングパターン (config でスキップ可)
            if (config.getOpeningActionEnabled()) {
                ledManager.playOpening(config.getOpeningActionDurationMs());
            } else {
                ledManager.fillSolid(0, 0, 0);
                ledManager.show();
            }

            // 明るさ (NVS > config.params、γ=2.2) と軸表示は controller.begin() が適用する

            // レンダリングタスク開始 (Core 1)
            if (!ledManager.startRenderTask(1, 2, 8192)) {
                sastle::Log.println("Failed to start LED render task");
            }
        }
    } else {
        sastle::Log.println("LEDManager disabled (ImageManager not available)");
    }

    // 操作の窓口。起動時の明るさ/軸表示を LED に適用し、以降は Web UI / MQTT / コンソールが
    // ここを通して操作する (明るさは γ=2.2 で LED 値に変換、変更は NVS に保存)。
    {
        DeviceController::Deps deps;
        deps.config = &config;
        deps.player = &soloPlayer;
        deps.led = &ledManager;
        deps.imu = imuSensor.isInitialized() ? &imuSensor : nullptr;
        deps.net = &network;
        deps.pump = &pump;
        deps.mqtt = &mqtt;
        deps.image = &imageManager;
        controller.begin(deps);
        // トリプルシェイク = デモ向けの AP の ON/OFF 切替 (UI モードの代わり)
        gesture.setOnTripleShake([]() { controller.togglePowerSave(); });
        console.begin(controller, g_apSsid);
    }

    // Web UI を開始。再生 (FramePump) は PSRAM 上の動画を 100ms 締切でデコードし、描画 (Core1)
    // とはトリプルバッファ経由で独立に動く。
    if (imageManager.isInitialized()) {
        if (network.isSoftAP()) {
            if (!soloWeb.begin(controller, config, soloPlayer, ledManager, network, imuSensor,
                               config.getSoloHttpPort(), &udpRx)) {
                sastle::Log.println("Web server failed to start");
            }
        }
    }

    // server モード: MQTT。受け側 (FramePump + UDP キュー) はこの時点で既に動いている。
    // server は球体の status/state を見た瞬間に配信を始めるので、MQTT は最後に立てる。
    // 接続自体は STA が繋がってから mqtt.loop() が行う (起動直後は STA 未接続のことがある)。
    if (config.isServerConfigured()) {
        mqtt.setCallback(mqttCallback);
        if (mqtt.begin(config)) {
            sastle::Log.setSink(&mqtt, "log");   // 起動ログの退避分もここから流れる
            commandHandler.begin(&controller);
            gesture.setEventSink([](const char* suffix, const char* json) {
                mqtt.publishDevice(suffix, json, false);
            });
            telemetry.begin(imuSensor.isInitialized() ? &imuSensor : nullptr, &mqtt, &timeSync,
                            &controller, config.getTelemetryImuHz());
        }
    } else {
        sastle::Log.println("server mode: off (config wifi{} disabled or no SSID) - MQTT/UDP not started");
    }

    // IMU ポーリングを専用タスク (core1, 優先度3) で回す。IMU 初期化の後・setup の最後に置く
    // (以前は ota.begin() の直前 = IMU 初期化より前に置いてしまい、isInitialized() が false で
    //  一度も起動していなかった。loop のフォールバックで 40/s しか出ていなかった原因)。loopTask (優先度1) から呼ぶと
    // ログ出力などで周期が乱れ (実測 中央値 22ms、最大 240ms)、描画が古い姿勢のまま
    // 止まって「ジャンプ」に見える。描画 (優先度2) より先に走るので定刻を守れる。
    if (imuSensor.isInitialized()) {
        if (!imuSensor.startTask(1, 3, 4096)) {
            sastle::Log.println("Failed to start IMU task (fallback: loop polling)");
        }
    }

    sastle::Log.println("\n=== Setup Complete ===");
}

// 性能計測ログ (2秒間隔): 描画/デコード時間と再生統計
static void logPerfIfDue(unsigned long now) {
    if (now - lastPerfLog < PERF_LOG_INTERVAL) {
        return;
    }
    lastPerfLog = now;

    LEDStats led = ledManager.getStats();
    ImageStats img = imageManager.getStats();
    SoloPlayer::Stats s = soloPlayer.stats();

    // 姿勢の鮮度: 「前フレームと同じ姿勢で描いたフレーム」の割合。
    // これが高いほど IMU のレートが描画に追いついていない = カクつく。
    static uint32_t s_prevRendered = 0, s_prevStale = 0;
    const uint32_t dRendered = led.frames_rendered - s_prevRendered;
    const uint32_t dStale = led.imu_stale_frames - s_prevStale;
    s_prevRendered = led.frames_rendered;
    s_prevStale = led.imu_stale_frames;
    const float stalePct = dRendered ? (100.0f * dStale / dRendered) : 0.0f;

    // 姿勢データの健全性診断。ortho/norm が 0 でなければ渡っている quat が壊れている
    // (非正規化 or torn read)。step は 1 フレームあたりの回転角の最大。
    sastle::Log.printf("[QDIAG] ortho_max=%.6f norm_max=%.6f step_max=%.2fdeg\n",
                       led.imu_ortho_err_max, led.imu_norm_err_max, led.imu_step_deg_max);
    ledManager.resetImuDiag();

    const FramePump::Stats ps = pump.stats();
    sastle::Log.printf(
        "[PERF] render_fps=%.1f map=%luus out=%luus stale=%.0f%% | img_fps=%.1f decode=%luus jpeg=%uB drop=%lu "
        "| src=%s net_fps=%.1f udp=%lu reasm_drop=%lu pump_stack=%lu | heap=%u\n",
        led.fps, (unsigned long)led.mapping_time_us, (unsigned long)led.output_time_us,
        stalePct,
        img.fps, (unsigned long)img.decode_time_us, (unsigned)img.last_jpeg_size,
        (unsigned long)imageManager.getDropped(),
        pump.activeSourceName(), ps.netFps, (unsigned long)udpRx.received(), (unsigned long)ps.reasmDropped,
        (unsigned long)ps.stackMinWords, (unsigned)ESP.getFreeHeap());
    sastle::Log.printf(
        "[SOLO] state=%s fps=%.1f frames=%lu loops=%lu miss=%lu decode_err=%lu read=%luus tick=%luus clients=%u\n",
        soloPlayer.stateName(), s.fps, (unsigned long)s.frames, (unsigned long)s.loops,
        (unsigned long)s.deadlineMisses, (unsigned long)s.decodeErrors,
        (unsigned long)s.lastReadUs, (unsigned long)s.lastTickUs,
        (unsigned)network.clientCount());
}

void loop() {
    // --- 実効レート計装 (5秒ごと) ---
    {
        static uint32_t s_loops = 0, s_pReads = 0, s_pFails = 0, s_pDisc = 0;
        static unsigned long s_lastRate = 0;
        s_loops++;
        unsigned long nowR = millis();
        if (nowR - s_lastRate >= 5000) {
            uint32_t rt = imuSensor.debugReadTotal(), rf = imuSensor.debugReadFails(),
                     rd = imuSensor.debugDiscards(), rz = imuSensor.debugZeroReads(),
                     rp = imuSensor.debugPartialReads(), rs = imuSensor.debugStraddles();
            static uint32_t pRz = 0, pRp = 0, pRs = 0;
            const float dtR = (nowR - s_lastRate) * 0.001f;
            sastle::Log.printf("[RATE] loop=%.0f/s imu_read=%.0f/s fail=%.0f/s disc=%.0f/s zero=%.0f/s partial=%.0f/s straddle=%.0f/s "
                               "i2c=%lukHz word=%d smooth=%u seq=%lu\n",
                               s_loops / dtR,
                               (rt - s_pReads) / dtR, (rf - s_pFails) / dtR, (rd - s_pDisc) / dtR, (rz - pRz) / dtR,
                               (rp - pRp) / dtR, (rs - pRs) / dtR,
                               (unsigned long)(imuSensor.i2cClock() / 1000), imuSensor.wordRead() ? 1 : 0,
                               (unsigned)imuSensor.smoothFrames(), (unsigned long)imuSensor.quatSeq());
            pRz = rz; pRp = rp; pRs = rs;
            // IMU タスクが退避した診断スナップショットをここで吐く (タスク側は Log を呼ばない)
            {
                uint8_t raw[8]; float n2; uint8_t reg; uint32_t hz; bool okR, autoR;
                if (imuSensor.takeDiagClockChanged(hz)) sastle::Log.printf("[IMU] I2C clock -> %lu kHz\n", (unsigned long)(hz / 1000));
                if (imuSensor.takeDiagReset(okR, autoR)) sastle::Log.printf("[IMU] sensor re-init (%s) %s\n", autoR ? "AUTO: discard ratio >50% for 4s" : "manual", okR ? "OK" : "FAILED");
                if (imuSensor.takeDiagReadFail(raw)) sastle::Log.printf("[IMU] quat read failed, raw=%02X %02X %02X %02X %02X %02X %02X %02X\n", raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7]);
                if (imuSensor.takeDiagDiscard(raw, n2)) sastle::Log.printf("[IMU] Discarded quat |q|^2=%.3f raw=%02X%02X %02X%02X %02X%02X %02X%02X\n", n2, raw[1], raw[0], raw[3], raw[2], raw[5], raw[4], raw[7], raw[6]);
                if (imuSensor.takeDiagVecPartial(reg, raw)) sastle::Log.printf("[IMU] vec reg=0x%02X partial raw=%02X%02X %02X%02X %02X%02X\n", reg, raw[1], raw[0], raw[3], raw[2], raw[5], raw[4]);
                static char dumpHex[200]; uint16_t idx0;
                for (int k = 0; k < 3 && imuSensor.takeRawDumpLine(dumpHex, sizeof(dumpHex), idx0); k++) sastle::Log.printf("[DUMP] %u %s\n", (unsigned)idx0, dumpHex);
            }
            s_loops = 0; s_pReads = rt; s_pFails = rf; s_pDisc = rd;
            s_lastRate = nowR;
        }
    }

    // OTA 要求を最優先で処理。書き込みセッション中は handle() が転送完了まで
    // ブロックするため、描画・再生は自然に停止する。
    ota.handle();

    // キャプティブポータル DNS の応答と、HTTP 経由の再起動要求の実行
    network.poll();   // STA 接続状態の変化をログに出し、切断時はバックオフ再接続
    mqtt.loop();      // keep-alive / 受信 / STA 接続後の (再) 接続 (server 未設定なら即 return)
    sastle::Log.loop();   // 退避ログを MQTT へ (sink 未登録なら即 return)
    soloWeb.loop();
    controller.tick();    // 設定の遅延保存と予約済み再起動

    // シリアルコンソール
    console.poll();

    // IMU更新
    unsigned long now = millis();
    if (imuSensor.isInitialized()) {
        if (!imuSensor.taskHandle()) {
            imuSensor.update();   // タスク起動に失敗したときだけ loop で読む
        }

        // ジェスチャー検出更新
        gesture.update();

        // 診断ログ (3秒に1回)
        if (now - lastIMULog >= IMU_LOG_INTERVAL) {
            lastIMULog = now;
            float w, x, y, z;
            if (imuSensor.getQuaternion(w, x, y, z)) {
                float gx, gy, gz, ax, ay, az;
                imuSensor.getGyro(gx, gy, gz);
                imuSensor.getAccel(ax, ay, az);
                uint8_t cs, cg, ca, cm;
                imuSensor.getCalibration(cs, cg, ca, cm);
                imu::Vector<3> eul = imuSensor.getEuler();
                sastle::Log.printf(
                    "[IMU] q=(%.3f,%.3f,%.3f,%.3f) eul=(%.1f,%.1f,%.1f) gyro=(%.2f,%.2f,%.2f) acc=(%.1f,%.1f,%.1f) cal=%u%u%u%u mode=%u\n",
                    w, x, y, z, (float)eul.x(), (float)eul.y(), (float)eul.z(),
                    gx, gy, gz, ax, ay, az, cs, cg, ca, cm, imuSensor.getOperationMode());
            }
        }
    }

    // 性能計測ログ
    logPerfIfDue(now);

    // server モードの周期 publish (MQTT 接続中のみ)
    telemetry.publishImuIfDue((uint32_t)now);
    telemetry.publishStateIfDue((uint32_t)now);
    telemetry.emitTimeSyncIfDue((uint32_t)now);

    delay(10);
}
