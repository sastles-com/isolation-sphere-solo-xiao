#include "DeviceController.h"

#include "Gamma.h"
#include "Log.h"
#include "Settings.h"

namespace sastle {

void DeviceController::begin(const Deps& deps) {
    _d = deps;
    if (_d.config) {
        _brightness = Settings::brightness(_d.config->getParamBrightness());
        _speed = _d.config->getParamSpeed();
        _hue = _d.config->getParamHue();
        _saturation = _d.config->getParamSaturation();
    }
    if (_d.led && _d.led->isInitialized()) {
        applyBrightnessToLed(_brightness);
        _d.led->setAxisIndicator(Settings::axisIndicator(_d.led->getAxisIndicator()));
    }
    Log.printf("[Control] brightness=%u%% (led %u/255, gamma 2.2) axis=%d speed=%u hue=%u sat=%u\n",
               (unsigned)_brightness, (unsigned)brightnessPercentToLed(_brightness),
               axisIndicator() ? 1 : 0, (unsigned)_speed, (unsigned)_hue, (unsigned)_saturation);
}

void DeviceController::tick() {
    Settings::tick();  // 保留中の設定変更を書き出す
    if (_apPending >= 0 && (int32_t)(millis() - _apPendingAtMs) >= 0) {
        const bool on = (_apPending == 1);
        _apPending = -1;
        if (_d.net) {
            if (on) {
                _d.net->startAp();
            } else {
                _d.net->stop();
            }
            Log.printf("[Control] SoftAP %s\n", _d.net->isSoftAP() ? "running" : "stopped");
        }
    }
    if (_rebootAtMs != 0 && (int32_t)(millis() - _rebootAtMs) >= 0) {
        Log.println("[Control] Restarting as requested");
        Serial.flush();
        delay(50);
        ESP.restart();
    }
}

// ---------------------------------------------------------------------------
// 再生
// ---------------------------------------------------------------------------

DeviceController::PlayResult DeviceController::play() {
    if (!_d.player) return PlayResult::Unavailable;
    if (_d.player->state() == SoloPlayer::State::Uploading) return PlayResult::Uploading;
    if (!_d.player->hasVideo()) return PlayResult::NoVideo;
    _d.player->play();
    return PlayResult::Ok;
}

DeviceController::PlayResult DeviceController::pause() {
    if (!_d.player) return PlayResult::Unavailable;
    if (_d.player->state() == SoloPlayer::State::Uploading) return PlayResult::Uploading;
    _d.player->pause();
    return PlayResult::Ok;
}

DeviceController::PlayResult DeviceController::stop() {
    if (!_d.player) return PlayResult::Unavailable;
    if (_d.player->state() == SoloPlayer::State::Uploading) return PlayResult::Uploading;
    _d.player->stop();
    return PlayResult::Ok;
}

DeviceController::PlayResult DeviceController::toggle() {
    if (!_d.player) return PlayResult::Unavailable;
    return _d.player->state() == SoloPlayer::State::Playing ? pause() : play();
}

const char* DeviceController::playResultMessage(PlayResult r) {
    switch (r) {
        case PlayResult::Ok: return "ok";
        case PlayResult::NoVideo: return "no video";
        case PlayResult::Uploading: return "upload in progress";
        default: return "player unavailable";
    }
}

const char* DeviceController::playbackStatus() const {
    if (!_d.player) return "stopped";
    switch (_d.player->state()) {
        case SoloPlayer::State::Playing: return "playing";
        case SoloPlayer::State::Paused: return "paused";
        default: return "stopped";
    }
}

// ---------------------------------------------------------------------------
// 明るさ / LED
// ---------------------------------------------------------------------------

void DeviceController::applyBrightnessToLed(uint8_t pct) {
    if (_d.led) {
        _d.led->setBrightness(brightnessPercentToLed(pct));
    }
}

void DeviceController::setBrightnessPct(uint8_t pct) {
    if (pct > 100) pct = 100;
    _brightness = pct;
    Settings::setBrightness(pct);  // 遅延保存 (スライダー操作をまとめて 1 回書く)
    if (_ledMode != LedMode::Test) {
        applyBrightnessToLed(pct);  // test 中は低輝度固定のまま。戻るときに反映される
    }
}

bool DeviceController::parseLedMode(const char* name, LedMode& out) {
    if (!name) return false;
    if (strcmp(name, "sphere") == 0) { out = LedMode::Sphere; return true; }
    if (strcmp(name, "pixels") == 0) { out = LedMode::Pixels; return true; }
    if (strcmp(name, "off") == 0)    { out = LedMode::Off;    return true; }
    if (strcmp(name, "test") == 0)   { out = LedMode::Test;   return true; }
    return false;
}

const char* DeviceController::ledModeName() const {
    switch (_ledMode) {
        case LedMode::Pixels: return "pixels";
        case LedMode::Off: return "off";
        case LedMode::Test: return "test";
        default: return "sphere";
    }
}

void DeviceController::setLedMode(LedMode mode) {
    const LedMode prev = _ledMode;
    _ledMode = mode;
    if (!_d.led) return;
    switch (mode) {
        case LedMode::Off:
            // 消灯。Manual に切り替えないと次フレームの updateLEDBuffer() で塗り戻される。
            _d.led->setOutputMode(LEDManager::OutputMode::Manual);
            _d.led->fillSolid(0, 0, 0);
            if (!_d.led->isRunning()) _d.led->show();
            break;
        case LedMode::Pixels:
            // ピクセル個別制御。updateLEDBuffer() による毎フレーム上書きを止める。
            if (prev == LedMode::Test) applyBrightnessToLed(_brightness);
            _d.led->setOutputMode(LEDManager::OutputMode::Manual);
            break;
        case LedMode::Test:
            // 点灯/配線確認モード。IMU/画像を通さず strip index から自前描画する。
            _d.led->setBrightness(kTestBrightness);
            _d.led->setOutputMode(LEDManager::OutputMode::Test);
            break;
        default:
            if (prev == LedMode::Test) applyBrightnessToLed(_brightness);
            _d.led->setOutputMode(LEDManager::OutputMode::Sphere);
            break;
    }
    Log.printf("[Control] led mode -> %s\n", ledModeName());
}

bool DeviceController::setTestPattern(const char* pattern, int width) {
    if (!_d.led || !pattern) return false;
    if (width < 1 || width > 60) return false;
    LEDManager::TestPattern tp;
    if (strcmp(pattern, "strip") == 0 || strcmp(pattern, "strip_id") == 0) {
        tp = LEDManager::TestPattern::StripId;
    } else if (strcmp(pattern, "chase") == 0) {
        tp = LEDManager::TestPattern::Chase;
    } else {
        return false;
    }
    _d.led->setTestPattern(tp, (uint8_t)width);
    return true;
}

const char* DeviceController::testPatternName() const {
    if (_d.led && _d.led->getTestPattern() == LEDManager::TestPattern::StripId) return "strip";
    return "chase";
}

uint8_t DeviceController::testWidth() const {
    return _d.led ? _d.led->getTestWidth() : 5;
}

void DeviceController::setAxisIndicator(bool on) {
    if (_d.led) _d.led->setAxisIndicator(on);
    Settings::setAxisIndicator(on);  // 次回起動でも復元する
}

bool DeviceController::axisIndicator() const {
    return _d.led ? _d.led->getAxisIndicator() : false;
}

void DeviceController::setImuCompensation(bool on) {
    if (_d.led) _d.led->setIMUCompensation(on);
}

uint16_t DeviceController::applyPixels(JsonArrayConst pixels) {
    if (!_d.led || pixels.isNull()) return 0;
    uint16_t applied = 0, rejected = 0;
    for (JsonObjectConst px : pixels) {
        // index 必須。r/g/b は省略時 0 (= 消灯) として扱う
        if (!px.containsKey("index")) { ++rejected; continue; }
        const int index = px["index"].as<int>();
        if (index < 0 || index > UINT16_MAX) { ++rejected; continue; }
        const uint8_t r = px["r"] | 0;
        const uint8_t g = px["g"] | 0;
        const uint8_t b = px["b"] | 0;
        if (_d.led->setPixel((uint16_t)index, r, g, b)) ++applied; else ++rejected;
    }
    // 出力は Core1 の描画タスクが行う。ここから FastLED を呼ぶと RMT ドライバを
    // 描画タスクと同時に叩いて競合するため、タスクが止まっている場合のみ直接出す。
    if (applied > 0 && !_d.led->isRunning()) _d.led->show();
    if (rejected > 0) Log.printf("[Control] %u pixel(s) rejected (missing/out-of-range index)\n", rejected);
    return applied;
}

// ---------------------------------------------------------------------------
// IMU
// ---------------------------------------------------------------------------

bool DeviceController::imuAvailable() const {
    return _d.imu && _d.imu->isInitialized();
}

bool DeviceController::setImuSmooth(int frames) {
    if (frames < 1 || frames > (int)IMUManager::kSmoothMax) return false;
    if (_d.imu) _d.imu->setSmoothFrames((uint8_t)frames);
    Settings::setImuSmoothFrames((uint8_t)frames);   // 再起動後も維持する
    return true;
}

bool DeviceController::setImuI2cKhz(int khz) {
    // 10kHz 指定で core1 が飢餓した事故があるため下限 50
    if (khz < 50 || khz > 400) return false;
    if (_d.imu) _d.imu->setI2cClock((uint32_t)khz * 1000UL);
    return true;
}

void DeviceController::setImuAux(bool on) { if (_d.imu) _d.imu->setAuxReads(on); }
void DeviceController::setImuWordRead(bool on) { if (_d.imu) _d.imu->setWordRead(on); }
void DeviceController::imuReset() { if (_d.imu) _d.imu->requestReset(); }
void DeviceController::imuResetTiming() { if (_d.imu) _d.imu->debugResetTiming(); }

bool DeviceController::imuDump(int samples) {
    if (samples < 1 || samples > 2000 || !_d.imu) return false;
    return _d.imu->startRawDump((uint16_t)samples);
}

// ---------------------------------------------------------------------------
// 映像ソース
// ---------------------------------------------------------------------------

bool DeviceController::setSourceMode(const char* name) {
    SourceArbiter::Mode m;
    if (!SourceArbiter::parseMode(name, m)) return false;
    if (_d.pump) _d.pump->setSourceMode(m);
    return true;
}

// ---------------------------------------------------------------------------
// ネットワーク / システム
// ---------------------------------------------------------------------------

bool DeviceController::saveStaCredentials(const String& ssid, const String& password) {
    return NetworkManager::saveStaCredentials(ssid, password);
}

bool DeviceController::setServerEnabled(bool enabled) {
    if (!_d.config) return false;
    _d.config->setServerEnabled(enabled);
    const bool ok = _d.config->saveConfig();
    Log.printf("[Control] server connection %s in config.json: %s\n",
               enabled ? "ENABLED" : "DISABLED", ok ? "saved" : "SAVE FAILED");
    return ok;
}

// ---------------------------------------------------------------------------
// 省電力
// ---------------------------------------------------------------------------

void DeviceController::requestAp(bool on, uint32_t delayMs) {
    _apPendingAtMs = millis() + delayMs;
    _apPending = on ? 1 : 0;
}

void DeviceController::togglePowerSave() {
    const bool apOn = apRunning() || _apPending == 1;
    requestAp(!apOn, 0);
    Log.printf("[Control] power save toggle -> AP %s\n", apOn ? "off" : "on");
}

void DeviceController::setApIdleMinutes(uint16_t minutes) {
    if (_d.net) _d.net->setApIdleTimeoutMin(minutes);
    Settings::setApIdleMinutes(minutes);
}

void DeviceController::setModemSleep(bool on) {
    if (_d.net) _d.net->setModemSleep(on);
    Settings::setModemSleep(on);
}

bool DeviceController::serverConfigured() {
    return _d.config ? _d.config->isServerConfigured() : false;
}

void DeviceController::scheduleReboot(uint32_t delayMs) {
    Settings::flush();  // 再起動で失わないよう確定させる
    uint32_t at = millis() + delayMs;
    if (at == 0) at = 1;
    _rebootAtMs = at;
}

// ---------------------------------------------------------------------------
// MQTT state
// ---------------------------------------------------------------------------

bool DeviceController::getStateJson(char* buffer, size_t bufferSize) {
    // 768: 派生元と同じ上限。呼び手のバッファも同サイズ。
    StaticJsonDocument<768> doc;

    JsonObject params = doc.createNestedObject("params");
    params["brightness"] = _brightness;
    params["speed"] = _speed;
    params["hue"] = _hue;
    params["saturation"] = _saturation;

    JsonObject playback = doc.createNestedObject("playback");
    playback["status"] = playbackStatus();
    playback["playlist"] = "";
    playback["track"] = _d.player ? _d.player->videoPath() : String("");
    playback["position"] = 0.0f;
    playback["duration"] = _d.player ? (float)_d.player->videoFrames() / (float)kSoloFps : 0.0f;

    JsonObject led = doc.createNestedObject("led");
    led["mode"] = ledModeName();
    led["axis"] = axisIndicator();
    led["source"] = activeSourceName();   // 統合ファームの追加キー (server は未知のキーを無視する)
    if (_d.imu) {
        led["imu_aux"] = _d.imu->auxReads();
        led["imu_i2c_khz"] = _d.imu->i2cClock() / 1000;
        led["imu_smooth"] = _d.imu->smoothFrames();
    }

    JsonObject system = doc.createNestedObject("system");
    system["uptime"] = millis() / 1000;
    system["fps"] = _d.led ? (int)_d.led->getStats().fps : 0;
    system["temp"] = 0.0;
    system["free_heap"] = ESP.getFreeHeap();

    doc["timestamp"] = "";
    doc["seq"] = 0;

    // serializeJson は収まらなくても >0 を返して切り詰める (壊れた JSON が publish され、
    // サーバー側の json.loads が失敗して ready 判定から外れる)。収まらないときは出さずに警告する。
    const size_t need = measureJson(doc) + 1;
    if (need > bufferSize) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            Log.printf("[Control] state JSON too large (%u > %u B), not published\n",
                       (unsigned)need, (unsigned)bufferSize);
        }
        return false;
    }
    return serializeJson(doc, buffer, bufferSize) > 0;
}

}  // namespace sastle
