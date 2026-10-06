#include "CommandHandler.h"

#include "Log.h"
#include "MQTTManager.h"   // kMqttBufferSize
#include "SoundManager.h"

// main.cpp のグローバルインスタンス。ブザー配線ピンの実機診断 (action:"sound_pin_test")
// のためだけに直接参照する。
extern sastle::SoundManager sound;

namespace sastle {

// led コマンド用 JSON ドキュメント容量 (ヒープ確保)。
// pixels 1要素 {"index":799,"r":255,"g":255,"b":255} は JSON 文字列で約39B に対し、
// ArduinoJson v6 のメモリプールでは JSON_OBJECT_SIZE(4)=約72B を占める。受信上限
// (kMqttBufferSize) 全量が pixels のとき約52要素 → 約4.5KB 必要になるため、
// 溢れない容量を確保する。足りないと DeserializationError::NoMemory で丸ごと捨てる。
constexpr size_t kLedDocCapacity = kMqttBufferSize * 4;

static bool parseJsonPayload(const char* payload, JsonDocument& doc) {
    DeserializationError error = deserializeJson(doc, payload);
    if (error) {
        // MQTT へも出す: パース失敗はリモートから見えないと切り分けできない
        Log.printf("[CommandHandler] JSON parse error: %s\n", error.c_str());
        return false;
    }
    return true;
}

bool CommandHandler::begin(DeviceController* ctl) {
    _ctl = ctl;
    Log.println("[CommandHandler] ready (params/playback/led/system -> DeviceController)");
    return _ctl != nullptr;
}

bool CommandHandler::handleMessage(const char* topic, const uint8_t* payload, unsigned int length) {
    if (!_ctl) return false;
    // ペイロードを文字列に変換。受信バッファと同容量にしないと led コマンドの
    // pixels 配列が途中で切れ、JSON パースが丸ごと失敗する。
    // 2KB をスタックに積むと呼び出し元 (loop タスク) を圧迫するため static。
    // 呼び出しは mqttCallback 経由の loop タスクのみなので再入はしない。
    static char message[kMqttBufferSize];
    const unsigned int len = (length < sizeof(message) - 1) ? length : sizeof(message) - 1;
    memcpy(message, payload, len);
    message[len] = '\0';

    // Topic/Payload (最大 2KB) は Serial のみ: RemoteLog は 1 行 240 文字。
    Serial.printf("[CommandHandler] Topic: %s\n", topic);
    Serial.printf("[CommandHandler] Payload: %s\n", message);

    const char* cmdType = _extractCommandType(topic);
    if (strcmp(cmdType, "params") == 0)   return _handleParams(message);
    if (strcmp(cmdType, "playback") == 0) return _handlePlayback(message);
    if (strcmp(cmdType, "led") == 0)      return _handleLed(message);
    if (strcmp(cmdType, "system") == 0)   return _handleSystem(message);
    Log.printf("[CommandHandler] Unknown command type: %s\n", cmdType);
    return false;
}

bool CommandHandler::_handleParams(const char* payload) {
    StaticJsonDocument<256> doc;
    if (!parseJsonPayload(payload, doc)) return false;

    bool updated = false;
    if (doc.containsKey("brightness")) {
        const int b = doc["brightness"] | 50;
        _ctl->setBrightnessPct((uint8_t)(b < 0 ? 0 : (b > 100 ? 100 : b)));
        Log.printf("[CommandHandler] params brightness=%d%%\n", b);
        updated = true;
    }
    if (doc.containsKey("speed"))      { _ctl->setSpeed(doc["speed"] | 50);            updated = true; }
    if (doc.containsKey("hue"))        { _ctl->setHue(doc["hue"] | 120);               updated = true; }
    if (doc.containsKey("saturation")) { _ctl->setSaturation(doc["saturation"] | 100); updated = true; }
    return updated;
}

bool CommandHandler::_handlePlayback(const char* payload) {
    StaticJsonDocument<256> doc;
    if (!parseJsonPayload(payload, doc)) return false;
    if (!doc.containsKey("action")) return false;

    const char* action = doc["action"] | "";
    DeviceController::PlayResult r;
    if (strcmp(action, "play") == 0)        r = _ctl->play();
    else if (strcmp(action, "pause") == 0)  r = _ctl->pause();
    else if (strcmp(action, "stop") == 0)   r = _ctl->stop();
    else if (strcmp(action, "toggle") == 0) r = _ctl->toggle();
    else {
        Log.printf("[CommandHandler] playback: unknown action %s\n", action);
        return false;
    }
    // ローカル動画の再生制御。配信 (UDP) が生きている間は表示は配信が握るので、
    // ここでの stop は「配信が止まったあと黒にする」予約として効く。
    Log.printf("[CommandHandler] playback %s -> %s (state=%s)\n", action,
               DeviceController::playResultMessage(r), _ctl->playbackStatus());
    return true;
}

bool CommandHandler::_handleLed(const char* payload) {
    DynamicJsonDocument doc(kLedDocCapacity);
    if (!parseJsonPayload(payload, doc)) return false;

    bool handled = false;

    // test のパターン/幅は mode より先に反映する (mode:"test" と同一メッセージで来る)
    if (doc.containsKey("pattern") || doc.containsKey("width")) {
        const char* pattern = doc["pattern"] | "chase";
        const int width = doc["width"] | 5;
        if (!_ctl->setTestPattern(pattern, width)) {
            Log.printf("[CommandHandler] led: bad pattern/width (%s/%d)\n", pattern, width);
        }
    }

    if (doc.containsKey("mode")) {
        const char* mode = doc["mode"] | "";
        DeviceController::LedMode m;
        if (DeviceController::parseLedMode(mode, m)) {
            _ctl->setLedMode(m);
        } else {
            Log.printf("[CommandHandler] led: unknown mode %s\n", mode);
        }
        handled = true;
    }

    // pixels 配列は mode と同一メッセージでも、pixels モード中の逐次更新でも受け付ける
    if (doc.containsKey("pixels")) {
        if (_ctl->ledMode() == DeviceController::LedMode::Pixels) {
            JsonArrayConst pixels = doc["pixels"].as<JsonArrayConst>();
            if (pixels.isNull()) {
                Log.println("[CommandHandler] led: pixels is not an array, ignored");
            } else {
                Log.printf("[CommandHandler] led: %u pixel(s) applied\n", (unsigned)_ctl->applyPixels(pixels));
                handled = true;
            }
        } else {
            Log.printf("[CommandHandler] led: pixels ignored (mode is %s)\n", _ctl->ledModeName());
        }
    }

    if (doc.containsKey("axis")) {
        _ctl->setAxisIndicator(doc["axis"].as<bool>());
        handled = true;
    }
    if (doc.containsKey("imu_comp")) {
        _ctl->setImuCompensation(doc["imu_comp"].as<bool>());
        handled = true;
    }
    // IMU の実行時スイッチ (Web UI の /api/imu と同じ setter)
    if (doc.containsKey("imu_aux"))      { _ctl->setImuAux(doc["imu_aux"].as<bool>());           handled = true; }
    if (doc.containsKey("imu_wordread")) { _ctl->setImuWordRead(doc["imu_wordread"].as<bool>()); handled = true; }
    if (doc.containsKey("imu_i2c_khz")) {
        const int khz = doc["imu_i2c_khz"].as<int>();
        if (!_ctl->setImuI2cKhz(khz)) Log.printf("[CommandHandler] led: imu_i2c_khz %d out of range (50-400)\n", khz);
        handled = true;
    }
    if (doc.containsKey("imu_smooth")) {
        const int n = doc["imu_smooth"].as<int>();
        if (!_ctl->setImuSmooth(n)) Log.printf("[CommandHandler] led: imu_smooth %d out of range\n", n);
        handled = true;
    }
    if (doc.containsKey("imu_dump")) {
        const int n = doc["imu_dump"].as<int>();
        Log.printf("[CommandHandler] led: IMU raw dump %d samples: %s\n", n,
                   _ctl->imuDump(n) ? "started" : "REFUSED");
        handled = true;
    }
    if (doc.containsKey("imu_reset") && doc["imu_reset"].as<bool>()) {
        _ctl->imuReset();
        Log.println("[CommandHandler] led: IMU reset requested");
        handled = true;
    }
    return handled;
}

bool CommandHandler::_handleSystem(const char* payload) {
    StaticJsonDocument<192> doc;
    if (!parseJsonPayload(payload, doc)) return false;
    if (!doc.containsKey("action")) return false;

    const char* action = doc["action"] | "";
    Log.printf("[CommandHandler] system action: %s\n", action);

    if (strcmp(action, "restart") == 0) {
        // 予約制: 設定を flush し、応答ログが MQTT に出てから再起動する
        _ctl->stop();
        _ctl->scheduleReboot(1000);
    } else if (strcmp(action, "ap") == 0) {
        // {"action":"ap","on":bool}: server モードなら MQTT で AP を戻せる
        _ctl->requestAp(doc["on"] | true);
    } else if (strcmp(action, "ap_idle") == 0) {
        // {"action":"ap_idle","minutes":0..1440}
        int m = doc["minutes"] | 0;
        _ctl->setApIdleMinutes((uint16_t)(m < 0 ? 0 : (m > 1440 ? 1440 : m)));
    } else if (strcmp(action, "modem_sleep") == 0) {
        _ctl->setModemSleep(doc["on"] | false);
    } else if (strcmp(action, "sound_pin_test") == 0) {
        // ブザー配線ピンの実機診断: 底面露出6ピンを順に鳴らす。N 番目のピンは (N+1) 回。
        static const uint8_t kCandidatePins[] = {5, 6, 7, 8, 38, 39};
        ConfigManager* cfg = _ctl->config();
        Log.println("[SoundTest] Pin scan start: 1st pin=1 beep, 2nd=2 beeps, ... (GPIO 5,6,7,8,38,39)");
        for (size_t i = 0; i < sizeof(kCandidatePins) && cfg; i++) {
            const uint8_t pin = kCandidatePins[i];
            Log.printf("[SoundTest] GPIO%u -> %u beep(s)\n", pin, (unsigned)(i + 1));
            sound.end();
            sound.begin(*cfg, pin);
            for (size_t b = 0; b <= i; b++) {
                sound.playEffect(SoundEffect::BEEP);
                delay(150);
            }
            delay(700);
        }
        sound.end();
        if (cfg) sound.begin(*cfg);
        Log.println("[SoundTest] Done. Restored default buzzer pin.");
    } else if (strcmp(action, "calibrate") == 0 || strcmp(action, "config_reload") == 0) {
        Log.printf("[CommandHandler] %s: not implemented\n", action);
    }
    return true;
}

const char* CommandHandler::_extractCommandType(const char* topic) {
    // sphere/all/command/params → "params"
    const char* slash = strrchr(topic, '/');
    return slash ? slash + 1 : "";
}

} // namespace sastle
