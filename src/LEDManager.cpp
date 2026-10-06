/**
 * @file LEDManager.cpp
 * @brief LED制御マネージャー実装
 */

#include "LEDManager.h"
#include "FileManager.h"
#include "common.h"
#include "FastMath.h"
#include "SphereMap.h"
#include "BoardConfig.h"
#include <FS.h>
#include <LittleFS.h>
#include <math.h>

namespace sastle {

// LED設定定数 (値は BoardConfig.h に集約)
#define LED_TYPE WS2812B
#define COLOR_ORDER GRB

// 静的メンバー初期化
LEDManager* LEDManager::_instance = nullptr;

LEDManager::LEDManager()
    : _initialized(false)
    , _taskRunning(false)
    , _config(nullptr)
    , _imageManager(nullptr)
    , _imuManager(nullptr)
    , _imuCompensationEnabled(false)
    , _renderTaskHandle(nullptr)
    , _ledBuffer(nullptr)
    , _ledLayout(nullptr)
    , _numLEDs(0)
    , _lastFPSUpdate(0)
    , _frameCount(0)
{
    memset(&_stats, 0, sizeof(_stats));
    memset(_ledsPerStrip, 0, sizeof(_ledsPerStrip));
    
    _instance = this;
}

LEDManager::~LEDManager() {
    stopRenderTask();
    
    if (_ledBuffer) {
        // _ledBuffer は静的バッファのため free しない
        _ledBuffer = nullptr;
    }
    
    if (_ledLayout) {
        free(_ledLayout);
        _ledLayout = nullptr;
    }

    if (_pxLUT) { free(_pxLUT); _pxLUT = nullptr; }
    if (_pyLUT) { free(_pyLUT); _pyLUT = nullptr; }

    _instance = nullptr;
}

namespace {
// LED実バッファ (静的確保, 2.4KB)。earlyBlank() がこのバッファで FastLED を
// 登録し、begin() も同じバッファを使う。setLeds() による差し替えは FastLED の
// ESP32 RMTドライバで効かないことがある (実機で全消灯のままになった) ため、
// 「最初から実バッファで登録する」方式にする。
CRGB s_ledBufferStatic[sastle::kMaxLeds];
bool s_earlyBlanked = false;

// FastLED の addLeds<> はピンがテンプレート引数なので、kLedPins[] を再帰テンプレートで展開して
// ストリップ 0..N-1 を順に登録する。std::index_sequence (C++14) はこのビルドでは使えなかった
// (build_flags の -std=c++14 が効いていない。Arduino-ESP32 2.x の既定 gnu++11 が後から付くとみられる)。
template <uint8_t N>
struct StripRegistrar {
    static void run(CRGB* const* buffers, const uint16_t* counts) {
        StripRegistrar<N - 1>::run(buffers, counts);
        FastLED.addLeds<LED_TYPE, kLedPins[N - 1], COLOR_ORDER>(buffers[N - 1], counts[N - 1]);
    }
};
template <>
struct StripRegistrar<0> {
    static void run(CRGB* const*, const uint16_t*) {}
};

void registerStrips(CRGB* const* buffers, const uint16_t* counts) {
    StripRegistrar<kNumStrips>::run(buffers, counts);
}
}  // namespace

void LEDManager::earlyBlank() {
    if (s_earlyBlanked) return;
    // FastLED 3.10 以降は CRGB 配列向け memset オーバーロードを持ち、libc 版と曖昧になる
    fill_solid(s_ledBufferStatic, sastle::kMaxLeds, CRGB::Black);
    // レイアウト読み込み前なので、各ストリップ kLedsPerStrip 個の均等割りで登録する
    CRGB* buffers[kNumStrips];
    uint16_t counts[kNumStrips];
    for (uint8_t i = 0; i < kNumStrips; i++) {
        buffers[i] = s_ledBufferStatic + i * kLedsPerStrip;
        counts[i] = kLedsPerStrip;
    }
    registerStrips(buffers, counts);
    FastLED.setBrightness(0);
    FastLED.show();
    s_earlyBlanked = true;
}

bool LEDManager::begin(ConfigManager& config, ImageManager& imageManager, IMUManager* imuManager) {
    Serial.println("[LEDManager] Initializing...");
    
    _config = &config;
    _imageManager = &imageManager;
    _imuManager = imuManager;
    
    // IMUが有効なら姿勢補正を有効化
    if (_imuManager && _imuManager->isInitialized()) {
        _imuCompensationEnabled = true;
        Serial.println("[LEDManager] IMU compensation enabled");
    } else {
        _imuCompensationEnabled = false;
        Serial.println("[LEDManager] IMU compensation disabled (no IMU)");
    }
    
    // LEDレイアウト読み込み
    String layoutPathStr = config.getLayoutPath();
    const char* layoutPath = layoutPathStr.c_str();
    if (!loadLayout(layoutPath)) {
        Serial.println("[LEDManager] Failed to load LED layout");
        return false;
    }
    
    Serial.printf("[LEDManager] Loaded %d LEDs from layout\n", _numLEDs);
    
    // LEDバッファは静的確保 (earlyBlank と共有。kMaxLeds を超えないこと)
    if (_numLEDs > kMaxLeds) {
        Serial.printf("[LEDManager] LED count %d exceeds kMaxLeds %d\n", _numLEDs, kMaxLeds);
        return false;
    }
    _ledBuffer = s_ledBufferStatic;
    Serial.printf("[LEDManager] Using static LED buffer: %d bytes\n", _numLEDs * sizeof(CRGB));

    // IMU補正OFF時用に静的UV→ピクセル座標を事前計算 (毎フレームの三角関数を回避)
    precomputeStaticUV();

    // マルチサンプリング設定 (config駆動。円周オフセットをここで前計算)
    setMultisample(config.getLedMultisampleEnabled(),
                   config.getLedMultisampleRadius(),
                   config.getLedMultisamplePoints());
    
    // ストリップ毎のLED数とオフセットを計算 (CSVの strip 列から導出)
    memset(_ledsPerStrip, 0, sizeof(_ledsPerStrip));
    memset(_stripStartIndex, 0, sizeof(_stripStartIndex));

    for (uint16_t i = 0; i < _numLEDs; i++) {
        uint8_t strip = _ledLayout[i].strip;
        if (strip < kNumStrips) {
            _ledsPerStrip[strip]++;
        }
    }

    // ストリップ開始インデックスを計算
    _stripStartIndex[0] = 0;
    for (int i = 1; i < kNumStrips; i++) {
        _stripStartIndex[i] = _stripStartIndex[i-1] + _ledsPerStrip[i-1];
    }

    // ストリップ毎のバッファポインタを設定
    for (int i = 0; i < kNumStrips; i++) {
        _stripBuffers[i] = _ledBuffer + _stripStartIndex[i];
    }

    Serial.printf("[LEDManager] Strips=%d, LEDs/strip:", kNumStrips);
    for (int i = 0; i < kNumStrips; i++) {
        Serial.printf(" %d", _ledsPerStrip[i]);
    }
    Serial.println();

    // FastLED初期化。earlyBlank() 済みなら同一の静的バッファで登録済みのため
    // 何もしない (均等 kLedsPerStrip 個/本の前提のみ確認)。未実行ならレイアウトどおりに登録する。
    if (s_earlyBlanked) {
        for (int i = 0; i < kNumStrips; i++) {
            if (_ledsPerStrip[i] != kLedsPerStrip ||
                _stripBuffers[i] != s_ledBufferStatic + i * kLedsPerStrip) {
                Serial.printf("[LEDManager] WARN strip%d layout mismatch (count=%d)\n",
                              i, _ledsPerStrip[i]);
            }
        }
    } else {
        registerStrips(_stripBuffers, _ledsPerStrip);
    }

    // 電源保護: 高負荷フレーム (全白など) でも合計電流を上限内に自動スケール。
    FastLED.setMaxPowerInVoltsAndMilliamps(5, kLedMaxPowerMa);
    FastLED.setBrightness(kLedDefaultBrightness);
    FastLED.clear();
    FastLED.show();

    // レンダリングは連続駆動 (renderTaskFunction が毎パス adoptReadyFrame + renderFrame)。
    // フレーム到着セマフォ/コールバックによるハンドシェイクは廃止 (トリプルバッファ化)。

    _initialized = true;
    Serial.println("[LEDManager] Initialization complete");
    
    return true;
}

bool LEDManager::loadLayout(const char* path) {
    if (!FileManager::exists(path)) {
        Serial.printf("[LEDManager] Layout file not found: %s\n", path);
        return false;
    }
    
    File file = LittleFS.open(path, "r");
    if (!file) {
        Serial.println("[LEDManager] Failed to open layout file");
        return false;
    }
    
    // 1行目（ヘッダー）をスキップ
    String line = file.readStringUntil('\n');
    
    // LED数をカウント
    uint16_t ledCount = 0;
    while (file.available()) {
        line = file.readStringUntil('\n');
        if (line.length() > 0) {
            ledCount++;
        }
    }
    
    if (ledCount == 0 || ledCount > kMaxLeds) {
        Serial.printf("[LEDManager] Invalid LED count: %d\n", ledCount);
        file.close();
        return false;
    }
    
    // レイアウトバッファ確保
    _ledLayout = (LEDCoord*)malloc(ledCount * sizeof(LEDCoord));
    if (!_ledLayout) {
        Serial.println("[LEDManager] Failed to allocate layout buffer");
        file.close();
        return false;
    }
    
    // ファイルを再読み込み
    file.seek(0);
    file.readStringUntil('\n');  // ヘッダースキップ
    
    _numLEDs = 0;
    while (file.available() && _numLEDs < ledCount) {
        line = file.readStringUntil('\n');
        if (line.length() == 0) continue;
        
        // CSV解析: FaceID,strip,strip_num,x,y,z
        int idx[5];
        idx[0] = line.indexOf(',');
        for (int i = 1; i < 5; i++) {
            idx[i] = line.indexOf(',', idx[i-1] + 1);
        }
        
        if (idx[4] > 0) {
            LEDCoord& coord = _ledLayout[_numLEDs];
            
            coord.faceID = line.substring(0, idx[0]).toInt();
            coord.strip = line.substring(idx[0] + 1, idx[1]).toInt();
            coord.stripNum = line.substring(idx[1] + 1, idx[2]).toInt();
            coord.x = line.substring(idx[2] + 1, idx[3]).toFloat();
            coord.y = line.substring(idx[3] + 1, idx[4]).toFloat();
            coord.z = line.substring(idx[4] + 1).toFloat();
            
            _numLEDs++;
        }
    }
    
    file.close();
    
    Serial.printf("[LEDManager] Loaded %d LED coordinates\n", _numLEDs);
    
    return _numLEDs > 0;
}

void LEDManager::sphereToUV(float x, float y, float z, float& u, float& v) {
    // 実体は SphereMap.h (純粋関数、native テスト済み)。WebUI デジタルツインと同一式。
    sphere::toUV(x, y, z, u, v);
}

void LEDManager::rotateByQuaternion(float& x, float& y, float& z, float qw, float qx, float qy, float qz) {
    sphere::rotateByQuaternion(x, y, z, qw, qx, qy, qz);
}

void LEDManager::setIMUCompensation(bool enabled) {
    _imuCompensationEnabled = enabled;
    Serial.printf("[LEDManager] IMU compensation %s\n", enabled ? "enabled" : "disabled");
}

bool LEDManager::startRenderTask(uint8_t core, uint8_t priority, uint32_t stackSize) {
    if (!_initialized) {
        Serial.println("[LEDManager] Not initialized");
        return false;
    }
    
    if (_taskRunning) {
        Serial.println("[LEDManager] Task already running");
        return true;
    }
    
    BaseType_t result = xTaskCreatePinnedToCore(
        renderTaskFunction,     // タスク関数
        "LED_Render",           // タスク名
        stackSize,              // スタックサイズ
        this,                   // パラメータ (this)
        priority,               // 優先度
        &_renderTaskHandle,     // タスクハンドル
        core                    // 実行コア
    );
    
    if (result != pdPASS) {
        Serial.println("[LEDManager] Failed to create render task");
        return false;
    }
    
    _taskRunning = true;
    Serial.printf("[LEDManager] Render task started on core %d (priority %d)\n", core, priority);
    
    return true;
}

void LEDManager::stopRenderTask() {
    if (!_taskRunning) {
        return;
    }

    // 協調停止にする理由 (実機 2026-09-22): 以前は vTaskDelete で即殺していたが、
    // FASTLED_ESP32_FLASH_LOCK=1 だと show() が spi_flash_op_lock() を握っている
    // 区間がある (20ms 周期のうち約 15ms)。そこで殺すと unlock が永久に呼ばれず、
    // 以降フラッシュに触る処理がすべて停止する。OTA (Update.write) と
    // /api/status (LittleFS) が固まり、ping だけ通る状態になった。
    // フラグを立てて、タスク自身が安全な位置 (show() の外) で抜けるのを待つ。
    _stopRequested = true;
    for (int i = 0; i < 200 && _taskRunning; i++) {  // 最大 2 秒待つ
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (_taskRunning) {
        // 抜けてこない場合の最後の手段。ロックを握ったままの可能性があるため警告する。
        Serial.println("[LEDManager] WARN: render task did not stop in 2s — forcing delete");
        if (_renderTaskHandle) {
            vTaskDelete(_renderTaskHandle);
        }
        _taskRunning = false;
    }
    _renderTaskHandle = nullptr;
    _stopRequested = false;
    Serial.println("[LEDManager] Render task stopped");
}

void LEDManager::renderTaskFunction(void* parameter) {
    LEDManager* manager = static_cast<LEDManager*>(parameter);

    Serial.printf("[LED_Render] Task started on core %d\n", xPortGetCoreID());

    // 連続駆動: フレーム到着に依存せず、毎パス最新IMUで現在の表示フレームを
    // 再マッピング描画する。新フレームは adoptReadyFrame() で独立に差し替わる。
    // → IMU姿勢追従は show() 律速の高Hz(~50-60Hz)で滑らか、動画は来たぶんだけ差替。
    while (true) {
        if (manager->_stopRequested) {
            // show() の外で抜ける (フラッシュ操作ロックを必ず解放した状態)
            manager->_taskRunning = false;
            manager->_renderTaskHandle = nullptr;
            Serial.println("[LED_Render] Task exiting (cooperative stop)");
            vTaskDelete(nullptr);
            return;
        }
        unsigned long frameStart = micros();

        if (manager->_imageManager) {
            manager->_imageManager->adoptReadyFrame();  // 新フレームがあれば採用
        }
        manager->renderFrame();                          // 最新IMUで再マッピング+出力

        manager->_stats.render_time_us = micros() - frameStart;
        vTaskDelay(1);  // 他タスクに譲る (show()が~14msなので実効~50-60Hz)
    }
}

void LEDManager::renderFrame() {
    unsigned long start = micros();

    // LEDバッファ更新。Manual では外部 (pixels/off コマンド) が _ledBuffer を
    // 直接書くため、マッピングを飛ばして出力のみ行う。
    if (_outputMode == OutputMode::Sphere) {
        updateLEDBuffer();
    } else if (_outputMode == OutputMode::Test) {
        updateTestBuffer();
    }

    unsigned long mappingTime = micros() - start;
    _stats.mapping_time_us = mappingTime;
    
    // LED出力（RMT DMA並列出力）
    unsigned long outputStart = micros();
    showParallel();
    unsigned long outputTime = micros() - outputStart;
    _stats.output_time_us = outputTime;

    
    // 統計更新
    _stats.frames_rendered++;
    _frameCount++;
    
    // FPS計算 (1秒毎)
    unsigned long now = millis();
    if (now - _lastFPSUpdate >= 1000) {
        _stats.fps = _frameCount * 1000.0f / (now - _lastFPSUpdate);
        _frameCount = 0;
        _lastFPSUpdate = now;
    }
}

void LEDManager::precomputeStaticUV() {
    if (!_ledLayout || !_imageManager) {
        return;
    }
    _pxLUT = (uint16_t*)malloc(_numLEDs * sizeof(uint16_t));
    _pyLUT = (uint16_t*)malloc(_numLEDs * sizeof(uint16_t));
    if (!_pxLUT || !_pyLUT) {
        Serial.println("[LEDManager] Static UV LUT alloc failed (fallback: per-frame calc)");
        if (_pxLUT) { free(_pxLUT); _pxLUT = nullptr; }
        if (_pyLUT) { free(_pyLUT); _pyLUT = nullptr; }
        return;
    }
    uint16_t w = _imageManager->getWidth();
    uint16_t h = _imageManager->getHeight();
    for (uint16_t i = 0; i < _numLEDs; i++) {
        float u, v;
        sphereToUV(_ledLayout[i].x, _ledLayout[i].y, _ledLayout[i].z, u, v);
        _pxLUT[i] = (uint16_t)(u * (w - 1));
        _pyLUT[i] = (uint16_t)(v * (h - 1));
    }
    Serial.printf("[LEDManager] Precomputed static UV LUT (%d LEDs)\n", _numLEDs);
}

void LEDManager::updateLEDBuffer() {
    if (!_imageManager || !_ledLayout || !_ledBuffer) {
        return;
    }

    const uint16_t imgWidth = _imageManager->getWidth();
    const uint16_t imgHeight = _imageManager->getHeight();

    // IMU姿勢補正用のquaternion(共役=逆回転)を1回だけ取得
    float qw = 1.0f, qx = 0.0f, qy = 0.0f, qz = 0.0f;
    bool useIMU = false;
    if (_imuCompensationEnabled && _imuManager && _imuManager->isInitialized()) {
        if (_imuManager->getQuaternion(qw, qx, qy, qz)) {
            qx = -qx; qy = -qy; qz = -qz;
            useIMU = true;

            // 姿勢の鮮度を計測する。描画が前フレームと同じ姿勢を使い回した回数を
            // 数えると、「IMUが遅い」のか「描画が速すぎて姿勢が追いつかない」のか
            // を切り分けられる。stale が多い = IMU側のレート不足。
            const uint32_t seq = _imuManager->quatSeq();
            if (seq == _lastQuatSeq) {
                _stats.imu_stale_frames++;
            }
            _lastQuatSeq = seq;

            // 姿勢の健全性診断 (ortho/norm/step の最大値。[QDIAG] が 2 秒ごとにリセット)。
            // 実体は imu/AttitudeStepDiag.h (純粋関数、native テスト済み)。
            _stepDiag.observe(qw, qx, qy, qz, _stats.imu_ortho_err_max,
                              _stats.imu_norm_err_max, _stats.imu_step_deg_max);
        }
    }

    // 全LEDを1パスで処理 (旧: strip毎に4回×全LED走査=3200反復 → 800反復)
    for (uint16_t i = 0; i < _numLEDs; i++) {
        uint16_t px, py;
        // 軸オーバーレイ用の(ワールド系)座標
        float wx = _ledLayout[i].x, wy = _ledLayout[i].y, wz = _ledLayout[i].z;

        if (useIMU) {
            // 姿勢が毎フレーム変わるので回転 + UV変換を実施
            rotateByQuaternion(wx, wy, wz, qw, qx, qy, qz);
            float u, v;
            sphereToUV(wx, wy, wz, u, v);
            px = (uint16_t)(u * (imgWidth - 1));
            py = (uint16_t)(v * (imgHeight - 1));
        } else if (_pxLUT) {
            // IMU補正OFF: 事前計算したピクセル座標を引くだけ (三角関数ゼロ)
            px = _pxLUT[i];
            py = _pyLUT[i];
        } else {
            float u, v;
            sphereToUV(wx, wy, wz, u, v);
            px = (uint16_t)(u * (imgWidth - 1));
            py = (uint16_t)(v * (imgHeight - 1));
        }

        uint8_t r, g, b;
        sampleAveraged(px, py, r, g, b);  // 中心+六角形6点の画像空間平均 (K=7)
        _ledBuffer[i] = CRGB(r, g, b);

        // XYZ軸インジケータを重畳 (IMU時は wx,wy,wz=ワールド座標, OFF時はbody座標)
        if (_axisIndicatorEnabled) {
            overlayAxisIndicator(_ledBuffer[i], wx, wy, wz);
        }
    }
}

namespace {
// ストリップ識別色 (led_drive_test の STRIP_ID と同じ並び): 0=R 1=G 2=B 3=Y 4=M。
// 6本目以降は白 (kNumStrips=5 なので未使用)。
CRGB testStripColor(uint8_t strip) {
    switch (strip) {
        case 0: return CRGB::Red;
        case 1: return CRGB::Green;
        case 2: return CRGB::Blue;
        case 3: return CRGB::Yellow;
        case 4: return CRGB::Magenta;
        default: return CRGB::White;
    }
}
// Chase が 1LED 進むまでの時間 [ms]。約16 LED/s で目視しやすい速度。
constexpr uint32_t kChaseStepMs = 60;
}  // namespace

void LEDManager::setTestPattern(TestPattern pattern, uint8_t width) {
    _testPattern = pattern;
    _testWidth = width < 1 ? 1 : width;
}

void LEDManager::updateTestBuffer() {
    if (!_ledBuffer) return;

    // 全消灯してから strip 単位で塗る。IMU/画像は一切参照しない。
    fill_solid(_ledBuffer, _numLEDs, CRGB::Black);

    if (_testPattern == TestPattern::StripId) {
        for (uint8_t s = 0; s < kNumStrips; s++) {
            const uint16_t count = _ledsPerStrip[s];
            if (count == 0) continue;
            fill_solid(_ledBuffer + _stripStartIndex[s], count, testStripColor(s));
        }
        return;
    }

    // TestPattern::Chase — 各 strip を識別色の _testWidth 連ブロックが DIN 側から走る。
    // 進行位置は millis() ベースなので描画fpsに依存しない。ストリップ境界は跨がず折り返す。
    const uint32_t head = (millis() / kChaseStepMs);
    for (uint8_t s = 0; s < kNumStrips; s++) {
        const uint16_t count = _ledsPerStrip[s];
        if (count == 0) continue;
        CRGB* strip = _ledBuffer + _stripStartIndex[s];
        const CRGB color = testStripColor(s);
        const uint16_t base = (uint16_t)(head % count);
        for (uint8_t i = 0; i < _testWidth; i++) {
            strip[(base + i) % count] = color;
        }
    }
}

void LEDManager::setMultisample(bool enabled, float radiusPx, uint8_t points) {
    if (points > kMaxSamplePoints) points = kMaxSamplePoints;
    _multisampleEnabled = enabled;
    _sampleRadiusPx = radiusPx;
    _sampleCount = points;

    // 半径Rの円周上に points 個を等間隔配置したオフセットを前計算 (cos/sin はここだけ)。
    // 以後の毎フレーム描画では整数オフセットを足すだけで三角関数は発生しない。
    for (uint8_t i = 0; i < points; ++i) {
        float ang = (2.0f * (float)M_PI * i) / (float)points;
        _sampleOff[i][0] = (int16_t)lroundf(radiusPx * cosf(ang));
        _sampleOff[i][1] = (int16_t)lroundf(radiusPx * sinf(ang));
    }

    Serial.printf("[LEDManager] Multisample: %s radius=%.1fpx points=%d (K=%d)\n",
                  enabled ? "ON" : "OFF", radiusPx, points,
                  (enabled && points > 0) ? (points + 1) : 1);
}

void LEDManager::sampleAveraged(uint16_t cx, uint16_t cy, uint8_t& r, uint8_t& g, uint8_t& b) {
    // 中心は常にサンプル
    _imageManager->getPixel(cx, cy, r, g, b);

    if (!_multisampleEnabled || _sampleCount == 0 || _sampleRadiusPx <= 0.0f) {
        return;  // 中心1点のみ (従来動作)
    }

    const int w = (int)_imageManager->getWidth();
    const int h = (int)_imageManager->getHeight();

    // 中心の値を含めて加算 (合計 _sampleCount + 1 点)
    uint16_t rs = r, gs = g, bs = b;
    for (uint8_t s = 0; s < _sampleCount; ++s) {
        int sx = (int)cx + _sampleOff[s][0];
        int sy = (int)cy + _sampleOff[s][1];

        // x=経度: ラップ (継ぎ目 u=0↔1 をまたいでも正しい隣を拾う)
        if (w > 0) {
            sx %= w;
            if (sx < 0) sx += w;
        }
        // y=極角(0=北極..h-1=南極): クランプ (極をまたがない)
        if (sy < 0) sy = 0; else if (sy >= h) sy = h - 1;

        uint8_t pr = 0, pg = 0, pb = 0;
        _imageManager->getPixel((uint16_t)sx, (uint16_t)sy, pr, pg, pb);
        rs += pr; gs += pg; bs += pb;
    }

    const uint16_t n = (uint16_t)_sampleCount + 1;
    r = (uint8_t)(rs / n);
    g = (uint8_t)(gs / n);
    b = (uint8_t)(bs / n);
}

void LEDManager::overlayAxisIndicator(CRGB& led, float x, float y, float z) {
    // 単位ベクトル前提。各半軸の中心方向との cos(角) = 対応する座標成分。
    // +X/+Y/+Z は明色 R/G/B、-X/-Y/-Z は暗色で軸線の向きが分かるようにする。
    constexpr float kAxisCos = 0.96f;          // マーカー半径 ≒ 16°
    const float inv = 1.0f / (1.0f - kAxisCos);
    struct AxisMarker { float cosang; uint8_t r, g, b; };
    const AxisMarker markers[6] = {
        { x, 255, 0, 0}, {-x, 48, 0, 0},   // ±X = 赤
        { y, 0, 255, 0}, {-y, 0, 48, 0},   // ±Y = 緑
        { z, 0, 0, 255}, {-z, 0, 0, 48},   // ±Z = 青
    };
    float bestW = 0.0f;
    uint8_t mr = 0, mg = 0, mb = 0;
    for (uint8_t k = 0; k < 6; k++) {
        if (markers[k].cosang > kAxisCos) {
            float w = (markers[k].cosang - kAxisCos) * inv;  // 0..1 (中心で1)
            if (w > bestW) { bestW = w; mr = markers[k].r; mg = markers[k].g; mb = markers[k].b; }
        }
    }
    if (bestW > 0.0f) {
        led.r = (uint8_t)(led.r * (1.0f - bestW) + mr * bestW);
        led.g = (uint8_t)(led.g * (1.0f - bestW) + mg * bestW);
        led.b = (uint8_t)(led.b * (1.0f - bestW) + mb * bestW);
    }
}

void LEDManager::showParallel() {
    // FastLED.show()は内部的にRMT DMAを使用
    // 4つのRMTチャンネルが並列動作し、CPUブロック時間は最大ストリップのみ
    FastLED.show();
    
    // Note: ESP32-S3のRMTは8チャンネルあり、4ストリップは完全に並列出力される
    // 実測: 800 LED でも ~6-8ms (最長ストリップ220 LEDのみ待機)
}

void LEDManager::fillSolid(uint8_t r, uint8_t g, uint8_t b) {
    if (!_ledBuffer) return;
    
    CRGB color(r, g, b);
    for (uint16_t i = 0; i < _numLEDs; i++) {
        _ledBuffer[i] = color;
    }
}

bool LEDManager::setPixel(uint16_t index, uint8_t r, uint8_t g, uint8_t b) {
    if (!_ledBuffer || index >= _numLEDs) {
        return false;
    }

    _ledBuffer[index] = CRGB(r, g, b);
    return true;
}

void LEDManager::show() {
    FastLED.show();
}

// --- オープニングパターン用パラメータ ---
namespace {
constexpr uint8_t  kOpeningBrightness = 76;     // 起動演出の輝度 30% (起動時の電流スパイクで
                                                // 電源が落ちる事象があるため控えめに)
constexpr float    kDotSigma          = 0.13f;  // 光点の角半径(rad) ≒ 7-8° (数ピクセル相当)
constexpr float    kSpinTurns         = 1.5f;   // 降下中に軸まわりに回る回数
constexpr uint8_t  kDotColors[3][3]   = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}};  // R/G/B
constexpr float    kTwoPi             = 6.28318530718f;
}

void LEDManager::renderOpeningDots(const float dir[3][3]) {
    const float invTwoSigma2 = 1.0f / (2.0f * kDotSigma * kDotSigma);
    for (uint16_t i = 0; i < _numLEDs; i++) {
        // LED方向 (レイアウトは単位球だが防御的に正規化)
        float lx = _ledLayout[i].x, ly = _ledLayout[i].y, lz = _ledLayout[i].z;
        float len = sqrtf(lx * lx + ly * ly + lz * lz);
        if (len > 1e-4f) { lx /= len; ly /= len; lz /= len; }

        float r = 0.0f, g = 0.0f, b = 0.0f;
        for (uint8_t d = 0; d < 3; d++) {
            float cosang = lx * dir[d][0] + ly * dir[d][1] + lz * dir[d][2];
            if (cosang > 1.0f) cosang = 1.0f; else if (cosang < -1.0f) cosang = -1.0f;
            float ang = acosf(cosang);                 // 中心からの角距離 0..π
            float w = expf(-(ang * ang) * invTwoSigma2);
            if (w < 0.02f) continue;                    // 遠いLEDは無視
            r += w * kDotColors[d][0];
            g += w * kDotColors[d][1];
            b += w * kDotColors[d][2];
        }
        _ledBuffer[i] = CRGB(r > 255 ? 255 : (uint8_t)r,
                             g > 255 ? 255 : (uint8_t)g,
                             b > 255 ? 255 : (uint8_t)b);
    }
    show();
}

void LEDManager::playOpening(uint16_t durationMs) {
    if (!_ledBuffer || !_ledLayout || _numLEDs == 0) {
        return;
    }
    Serial.printf("[LEDManager] Opening action (%u ms)\n", durationMs);

    uint8_t prevBrightness = FastLED.getBrightness();
    FastLED.setBrightness(kOpeningBrightness);

    // フェーズ配分: 降下50% / 上昇33% / 開花(残り)
    uint32_t descendMs = (uint32_t)durationMs * 50 / 100;
    uint32_t ascendMs  = (uint32_t)durationMs * 33 / 100;
    uint32_t bloomMs   = durationMs - descendMs - ascendMs;

    float dir[3][3];
    uint32_t t0, elapsed;

    // --- フェーズ1: 北極(+Z)→南極(-Z) へ螺旋降下。3点は経度120°間隔。---
    // 極軸は Z (sphereToUV が極角を +Z から測るため)。赤道面は X-Y。
    t0 = millis();
    while ((elapsed = millis() - t0) < descendMs) {
        float t = (float)elapsed / (float)descendMs;     // 0→1
        float zPos = 1.0f - 2.0f * t;                     // +1(北)→-1(南)
        float rr = sqrtf(fmaxf(0.0f, 1.0f - zPos * zPos)); // その緯度の円の半径
        float base = kSpinTurns * kTwoPi * t;             // 回転
        for (uint8_t d = 0; d < 3; d++) {
            float phi = base + d * (kTwoPi / 3.0f);
            dir[d][0] = rr * cosf(phi);                   // X
            dir[d][1] = rr * sinf(phi);                   // Y
            dir[d][2] = zPos;                             // Z(極軸)
        }
        renderOpeningDots(dir);
    }

    // --- フェーズ2: 南極(-Z)→北極(+Z) へ3点が一斉に上昇 (経度固定の3本の子午線)。---
    t0 = millis();
    while ((elapsed = millis() - t0) < ascendMs) {
        float t = (float)elapsed / (float)ascendMs;       // 0→1
        float zPos = -1.0f + 2.0f * t;                    // -1(南)→+1(北)
        float rr = sqrtf(fmaxf(0.0f, 1.0f - zPos * zPos));
        for (uint8_t d = 0; d < 3; d++) {
            float phi = d * (kTwoPi / 3.0f);              // 固定経度
            dir[d][0] = rr * cosf(phi);
            dir[d][1] = rr * sinf(phi);
            dir[d][2] = zPos;
        }
        renderOpeningDots(dir);
    }

    // --- フェーズ3: 全球が虹色(経度=色相)に一瞬光ってフェード = READY ---
    t0 = millis();
    while ((elapsed = millis() - t0) < bloomMs) {
        float t = (float)elapsed / (float)bloomMs;        // 0→1
        uint8_t val = (uint8_t)(sinf(3.14159265f * t) * 255.0f);  // 0→1→0
        for (uint16_t i = 0; i < _numLEDs; i++) {
            // Z軸まわりの経度 (sphereToUV の u と同じ引数順なので色相 ≒ u*255)
            float az = atan2f(_ledLayout[i].x, _ledLayout[i].y);
            uint8_t hue = (uint8_t)((az + 3.14159265f) / kTwoPi * 255.0f);
            _ledBuffer[i] = CHSV(hue, 255, val);
        }
        show();
    }

    // 消灯して輝度を元に戻す
    fillSolid(0, 0, 0);
    show();
    FastLED.setBrightness(prevBrightness);
}

void LEDManager::setBrightness(uint8_t brightness) {
    FastLED.setBrightness(brightness);
}

void LEDManager::printStatus() {
    Serial.println("\n=== LED Manager Status ===");
    Serial.printf("Initialized: %s\n", _initialized ? "Yes" : "No");
    Serial.printf("Task Running: %s\n", _taskRunning ? "Yes" : "No");
    Serial.printf("Total LEDs: %d\n", _numLEDs);
    Serial.printf("Strips: %d [", kNumStrips);
    for (int i = 0; i < kNumStrips; i++) Serial.printf("%s%d", i ? ", " : "", _ledsPerStrip[i]);
    Serial.println("]");
    Serial.println("\n--- Statistics ---");
    Serial.printf("Frames Rendered: %u\n", _stats.frames_rendered);
    Serial.printf("Frames Dropped: %u\n", _stats.frames_dropped);
    Serial.printf("FPS: %.2f\n", _stats.fps);
    Serial.printf("Render Time: %u us\n", _stats.render_time_us);
    Serial.printf("  Mapping: %u us\n", _stats.mapping_time_us);
    Serial.printf("  Output: %u us\n", _stats.output_time_us);
}

} // namespace sastle
