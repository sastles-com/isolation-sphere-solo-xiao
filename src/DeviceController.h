/**
 * @file DeviceController.h
 * @brief 制御面 (HTTP / MQTT / シリアルコンソール) が共通で呼ぶ操作の窓口
 *
 * 統合ファームでは Web UI (SoloWebServer)、MQTT (CommandHandler)、シリアルコンソールの
 * 3 つから同じ操作が来る。各制御面は「パース → DeviceController → 応答」だけにして、
 * 実際の適用 (LED / 再生 / IMU / 設定の永続化) はここに 1 か所で書く。
 *   - 明るさ % → LED 値は Gamma.h (γ=2.2) に統一 (派生元 server と同じ見え方)
 *   - 利用者が変えた値は Settings (NVS) に保存 (どの制御面から変えても次回起動で復元)
 *   - 再起動は予約制 (Settings::flush → 応答を返してから loop の tick() で実行)
 *
 * 呼び出し文脈: loopTask と httpd タスクの両方。操作は単純なセッタか、SoloPlayer のように
 * 内部でミューテックスを持つものだけなので、ここでは追加のロックを取らない。
 */

#ifndef __DEVICE_CONTROLLER_H__
#define __DEVICE_CONTROLLER_H__

#include <Arduino.h>
#include <ArduinoJson.h>

#include "ConfigManager.h"
#include "FramePump.h"
#include "BatteryGauge.h"
#include "BatteryGuard.h"
#include "IMUManager.h"
#include "LEDManager.h"
#include "MQTTManager.h"
#include "NetworkManager.h"
#include "SoloPlayer.h"
#include "SoundManager.h"

namespace sastle {

class DeviceController {
public:
    struct Deps {
        ConfigManager* config = nullptr;
        SoloPlayer* player = nullptr;
        LEDManager* led = nullptr;
        IMUManager* imu = nullptr;       ///< 未検出なら nullptr
        NetworkManager* net = nullptr;
        FramePump* pump = nullptr;
        MQTTManager* mqtt = nullptr;     ///< server 未設定なら nullptr
        ImageManager* image = nullptr;   ///< 統計の読み出し用
        BatteryGauge* battery = nullptr; ///< 基板B の残量計 (読むだけ)
        SoundManager* sound = nullptr;   ///< 電源 OFF の終了音
    };

    enum class PlayResult : uint8_t { Ok, NoVideo, Uploading, Unavailable };
    enum class LedMode : uint8_t { Sphere, Pixels, Off, Test };

    /// 依存を受け取り、起動時の明るさ (NVS > config.params) と軸表示を LED に適用する
    void begin(const Deps& deps);

    /// loop() から呼ぶ: 設定の遅延保存と予約済み再起動の実行
    void tick();

    // --- 再生 ---
    PlayResult play();
    PlayResult pause();
    PlayResult stop();
    PlayResult toggle();
    static const char* playResultMessage(PlayResult r);
    /// MQTT state 用: playing | paused | stopped
    const char* playbackStatus() const;

    // --- 表示パラメータ (params) ---
    void setBrightnessPct(uint8_t pct);        ///< Gamma 適用 + NVS 保存
    uint8_t brightnessPct() const { return _brightness; }
    void setSpeed(uint8_t v) { _speed = v; }
    void setHue(uint16_t v) { _hue = v; }
    void setSaturation(uint8_t v) { _saturation = v; }
    uint8_t speed() const { return _speed; }
    uint16_t hue() const { return _hue; }
    uint8_t saturation() const { return _saturation; }

    // --- LED ---
    /// sphere | pixels | off | test。test は低輝度を強制し、戻るときに params の明るさを再適用
    void setLedMode(LedMode mode);
    static bool parseLedMode(const char* name, LedMode& out);
    LedMode ledMode() const { return _ledMode; }
    const char* ledModeName() const;
    /// strip / strip_id / chase。width は 1..60。false = 名前または幅が不正
    bool setTestPattern(const char* pattern, int width);
    const char* testPatternName() const;
    uint8_t testWidth() const;
    /// ストリップ 1〜5 の電源 (LED_EN)。保存しない (再起動で ON に戻る)
    void setLedPower(bool on) { if (_d.led) _d.led->setPowerEnabled(on); }
    bool ledPower() const { return _d.led ? _d.led->powerEnabled() : false; }
    /// 北極 LED: sphere | rainbow | off。false = 名前が不正
    bool setNorthMode(const char* name);
    const char* northModeName() const;
    void setAxisIndicator(bool on);            ///< NVS 保存
    bool axisIndicator() const;
    void setImuCompensation(bool on);
    /// pixels モードで [{index,r,g,b},...] を適用。戻り値 = 適用数
    uint16_t applyPixels(JsonArrayConst pixels);

    // --- IMU (実行時スイッチ) ---
    bool imuAvailable() const;
    bool setImuSmooth(int frames);             ///< 1..kSmoothMax。NVS 保存
    bool setImuI2cKhz(int khz);                ///< 50..400
    void setImuAux(bool on);
    void setImuWordRead(bool on);
    void imuReset();
    bool imuDump(int samples);                 ///< 1..2000
    void imuResetTiming();

    // --- 映像ソース (FramePump の調停) ---
    bool setSourceMode(const char* name);      ///< auto | local | network
    const char* sourceModeName() const { return _d.pump ? _d.pump->sourceModeName() : "auto"; }
    const char* activeSourceName() const {
        if (_d.pump) return _d.pump->activeSourceName();
        return (_d.player && _d.player->state() == SoloPlayer::State::Playing) ? "local" : "none";
    }

    // --- ネットワーク / システム ---
    bool saveStaCredentials(const String& ssid, const String& password);
    /// server 接続 (config.json wifi.enabled) を切り替えて保存する。反映は再起動後
    bool setServerEnabled(bool enabled);
    bool serverConfigured();
    // --- 省電力 (SoftAP / モデム省電力) ---
    // 実際の Wi-Fi 操作は loopTask の tick() が行う (httpd タスクから WiFi を直接触らない。
    // AP 停止は応答を返してから効かせる意味もある)。設定値は NVS に保存。
    /// SoftAP を今すぐ止める/再開する (delayMs 後に実行)。止めても自動停止の設定は変わらない
    void requestAp(bool on, uint32_t delayMs = 300);
    bool apRunning() const { return _d.net && _d.net->isSoftAP(); }
    /// デモ向けの切替: AP が動いていれば止め、止まっていれば再開する。ジェスチャー (メニューで Z−) から呼ぶ (loopTask)
    void togglePowerSave();
    /// 端末 0 台がこの分数続いたら AP を自動停止。0 = 常時 ON。NVS 保存
    void setApIdleMinutes(uint16_t minutes);
    uint16_t apIdleMinutes() const { return _d.net ? _d.net->apIdleTimeoutMin() : 0; }
    void setModemSleep(bool on);       ///< NVS 保存。STA 接続中に効く
    bool modemSleep() const { return _d.net && _d.net->modemSleep(); }

    /// 初回起動時の AP 自動停止時間 [分]。NVS に値があればそちらが優先
    static constexpr uint16_t kDefaultApIdleMin = 10;

    /// delayMs 後に再起動する (Settings は即時 flush)。応答を返す猶予を持たせるため予約制
    void scheduleReboot(uint32_t delayMs);

    /**
     * @brief 電源を切る (FW-3)。応答を返す猶予のため delayMs 後に loop の tick() で実行する。
     * 手順: LED データ線 Low (描画停止) → LED_EN Low → 設定保存 → 終了音 → PWR_KILL Low を保持。
     * PWR_KILL Low で LTC2954 が MCU_EN を Low にし、3V3_MCU (TPS62933) が止まる。
     * USB 給電中は XIAO が止まらないので、powerOffFailed() が true になる。
     */
    void requestPowerOff(uint32_t delayMs = 500);
    /// 診断: ブザーで起動音を鳴らす (鳴り終わるまでブロック)。false = ブザー未初期化
    bool testBuzzer() { if (!_d.sound) return false; _d.sound->playEffect(SoundEffect::STARTUP); return true; }
    bool powerOffPending() const { return _powerOffAtMs != 0; }
    bool powerOffFailed() const { return _powerOffFailed; }
    bool rebootPending() const { return _rebootAtMs != 0; }
    /// 電池の低電圧監視 (BatteryGuard.h): "ok" / "low" (予告済み) / "empty" (放電終止で電源 OFF を要求した)
    const char* batteryGuardLevel() const { return battery_guard::levelName(_battGuard.level()); }

    /**
     * @brief MQTT の retained state (sphere/<id>/state) を組み立てる。派生元と同じ鍵。
     * @return false = バッファに収まらない (publish しない)
     */
    bool getStateJson(char* buffer, size_t bufferSize);

    // 依存へのアクセス (制御面が統計を読むため)
    SoloPlayer* player() const { return _d.player; }
    LEDManager* led() const { return _d.led; }
    IMUManager* imu() const { return _d.imu; }
    NetworkManager* net() const { return _d.net; }
    ConfigManager* config() const { return _d.config; }
    FramePump* pump() const { return _d.pump; }
    MQTTManager* mqtt() const { return _d.mqtt; }
    ImageManager* image() const { return _d.image; }
    BatteryGauge* battery() const { return _d.battery; }
    bool mqttConnected() const { return _d.mqtt && _d.mqtt->isConnected(); }

private:
    void applyBrightnessToLed(uint8_t pct);

    Deps _d;
    uint8_t _brightness = 50;    ///< %
    uint8_t _speed = 50;
    uint16_t _hue = 120;
    uint8_t _saturation = 100;
    LedMode _ledMode = LedMode::Sphere;
    volatile uint32_t _rebootAtMs = 0;   ///< 0 = 予約なし
    volatile uint32_t _powerOffAtMs = 0; ///< 0 = 予約なし
    volatile bool _powerOffFailed = false;
    void doPowerOff();
    void checkBattery();                 ///< 低電圧の予告と放電終止での電源 OFF (tick から)
    battery_guard::Guard _battGuard;
    volatile int8_t _apPending = -1;     ///< -1 = なし / 0 = 停止予約 / 1 = 再開予約
    volatile uint32_t _apPendingAtMs = 0;

    /// mode:"test" 突入時に強制する低輝度 (0-255)。点灯/配線確認が目的で眩しさ・電流を抑える
    static constexpr uint8_t kTestBrightness = 24;
};

}  // namespace sastle

#endif  // __DEVICE_CONTROLLER_H__
