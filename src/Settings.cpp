/**
 * @file Settings.cpp
 * @brief Settings実装
 */

#include "Settings.h"

#include <Arduino.h>
#include <Preferences.h>

namespace sastle {

namespace {
constexpr const char* kNamespace = "solo";   // STA 資格情報と同じ namespace
constexpr const char* kKeyBrightness = "bri";
constexpr const char* kKeyAxis = "axis";
constexpr const char* kKeySmooth = "smooth";
constexpr const char* kKeyApIdle = "apidle";
constexpr const char* kKeyMSleep = "msleep";

bool s_ready = false;
bool s_dirty = false;
uint32_t s_dirtyAtMs = 0;
uint8_t s_brightness = 0;
bool s_hasBrightness = false;
bool s_axis = false;
bool s_hasAxis = false;
uint8_t s_smooth = 1;
bool s_hasSmooth = false;
uint16_t s_apIdle = 0;
bool s_hasApIdle = false;
bool s_msleep = false;
bool s_hasMSleep = false;

/// 1 回だけ開いて読み、以降は RAM 上の値で応答する
void writeAll() {
    Preferences prefs;
    if (!prefs.begin(kNamespace, false)) {
        Serial.println("[Settings] NVS open failed (settings not saved)");
        return;
    }
    if (s_hasBrightness) {
        prefs.putUChar(kKeyBrightness, s_brightness);
    }
    if (s_hasAxis) {
        prefs.putBool(kKeyAxis, s_axis);
    }
    if (s_hasSmooth) {
        prefs.putUChar(kKeySmooth, s_smooth);
    }
    if (s_hasApIdle) {
        prefs.putUShort(kKeyApIdle, s_apIdle);
    }
    if (s_hasMSleep) {
        prefs.putBool(kKeyMSleep, s_msleep);
    }
    prefs.end();
    Serial.printf("[Settings] saved brightness=%u%% axis=%d\n", (unsigned)s_brightness, s_axis ? 1 : 0);
}
}  // namespace

void Settings::begin() {
    Preferences prefs;
    if (!prefs.begin(kNamespace, true)) {
        Serial.println("[Settings] NVS not available (using config.json defaults)");
        s_ready = true;  // 読めなくても動作は継続する
        return;
    }
    if (prefs.isKey(kKeySmooth)) {
        s_smooth = prefs.getUChar(kKeySmooth, 1);
        s_hasSmooth = true;
    }
    if (prefs.isKey(kKeyApIdle)) {
        s_apIdle = prefs.getUShort(kKeyApIdle, 0);
        s_hasApIdle = true;
    }
    if (prefs.isKey(kKeyMSleep)) {
        s_msleep = prefs.getBool(kKeyMSleep, false);
        s_hasMSleep = true;
    }
    if (prefs.isKey(kKeyAxis)) {
        s_axis = prefs.getBool(kKeyAxis, false);
        s_hasAxis = true;
    }
    if (prefs.isKey(kKeyBrightness)) {
        s_brightness = prefs.getUChar(kKeyBrightness, 50);
        if (s_brightness > 100) {
            s_brightness = 100;
        }
        s_hasBrightness = true;
    }
    prefs.end();
    s_ready = true;
    if (s_hasBrightness) {
        Serial.printf("[Settings] restored brightness=%u%% axis=%d\n", (unsigned)s_brightness, s_axis ? 1 : 0);
    } else {
        Serial.println("[Settings] no saved settings yet (using config.json defaults)");
    }
}

uint8_t Settings::brightness(uint8_t fallback) {
    return s_hasBrightness ? s_brightness : fallback;
}

uint8_t Settings::imuSmoothFrames(uint8_t fallback) {
    return s_hasSmooth ? s_smooth : fallback;
}

void Settings::setImuSmoothFrames(uint8_t n) {
    if (s_hasSmooth && s_smooth == n) {
        return;
    }
    s_smooth = n;
    s_hasSmooth = true;
    s_dirty = true;
    s_dirtyAtMs = millis();
}

bool Settings::axisIndicator(bool fallback) {
    return s_hasAxis ? s_axis : fallback;
}

void Settings::setAxisIndicator(bool enabled) {
    if (s_hasAxis && s_axis == enabled) {
        return;
    }
    s_axis = enabled;
    s_hasAxis = true;
    s_dirty = true;
    s_dirtyAtMs = millis();
}

void Settings::setBrightness(uint8_t percent) {
    if (percent > 100) {
        percent = 100;
    }
    if (s_hasBrightness && s_brightness == percent) {
        return;  // 値が変わっていなければ書かない
    }
    s_brightness = percent;
    s_hasBrightness = true;
    s_dirty = true;
    s_dirtyAtMs = millis();
}

uint16_t Settings::apIdleMinutes(uint16_t fallback) {
    return s_hasApIdle ? s_apIdle : fallback;
}

void Settings::setApIdleMinutes(uint16_t minutes) {
    if (s_hasApIdle && s_apIdle == minutes) {
        return;
    }
    s_apIdle = minutes;
    s_hasApIdle = true;
    s_dirty = true;
    s_dirtyAtMs = millis();
}

bool Settings::modemSleep(bool fallback) {
    return s_hasMSleep ? s_msleep : fallback;
}

void Settings::setModemSleep(bool on) {
    if (s_hasMSleep && s_msleep == on) {
        return;
    }
    s_msleep = on;
    s_hasMSleep = true;
    s_dirty = true;
    s_dirtyAtMs = millis();
}

void Settings::tick() {
    if (!s_ready || !s_dirty) {
        return;
    }
    if (millis() - s_dirtyAtMs < kSaveDelayMs) {
        return;  // まだ操作中かもしれないので待つ
    }
    s_dirty = false;
    writeAll();
}

void Settings::flush() {
    if (!s_ready || !s_dirty) {
        return;
    }
    s_dirty = false;
    writeAll();
}

}  // namespace sastle
