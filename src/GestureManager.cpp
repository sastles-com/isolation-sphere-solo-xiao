#include "GestureManager.h"
#include <cmath>

using namespace sastle::gesture_logic;

bool GestureManager::begin(IMUManager& imu, SoundManager* sound) {
    _imu = &imu;
    _sound = sound;
    _fsm.begin(millis());

    if (!_imu->isInitialized()) {
        Serial.println("[Gesture] IMU not initialized");
        return false;
    }
    Serial.println("[Gesture] Initialized: triple shake -> menu, Z- = AP toggle, Z+ = power off (4 s, shake to cancel)");
    return true;
}

void GestureManager::update() {
    if (!_imu || !_imu->isInitialized()) {
        return;
    }

    Input in;
    in.nowMs = millis();
    float ax, ay, az;
    if (_imu->getAccel(ax, ay, az)) {
        in.shake = _shake.feed(in.nowMs, sqrtf(ax * ax + ay * ay + az * az));
    }
    float w, x, y, z;
    in.quatValid = _imu->getQuaternion(w, x, y, z);
    in.q = Quat(w, x, y, z);

    const UiState before = _fsm.state();
    const Action a = _fsm.update(in);
    handle(a);
    if (_fsm.state() != before && _onUiState) {
        _onUiState(_fsm.state(), _fsm.stateSinceMs());
    }

    // 予告中は 1 秒ごとに短い音 (だんだん高く)
    if (_fsm.state() == UiState::PowerOffPending) {
        const int8_t sec = (int8_t)((in.nowMs - _fsm.stateSinceMs()) / 1000);
        if (sec != _lastBeepSec) {
            _lastBeepSec = sec;
            if (_sound && _sound->isInitialized()) _sound->playTone(880.0f + 220.0f * sec, 60);
        }
    } else {
        _lastBeepSec = -1;
    }
}

void GestureManager::handle(Action a) {
    switch (a) {
    case Action::None:
        return;
    case Action::EnterMenu:
        Serial.println("[Gesture] triple shake -> menu");
        play(SoundEffect::UI_MODE_ENTER);
        publishGesture("triple_shake", nullptr, nullptr);
        publishUiMode("active");
        return;
    case Action::MenuTimeout:
        Serial.println("[Gesture] menu timeout");
        play(SoundEffect::UI_MODE_EXIT);
        publishUiMode("normal");
        return;
    case Action::SelectStart:
        Serial.println("[Gesture] Z rotation > 45 deg, hold 1 s to select");
        play(SoundEffect::BEEP);
        return;
    case Action::ApToggle:
        Serial.println("[Gesture] Z- -> AP toggle");
        play(SoundEffect::CONFIRM);
        publishGesture("rotation", "negative", "ap_toggle");
        publishUiMode("normal");
        if (_onApToggle) _onApToggle();
        return;
    case Action::PowerOffArm:
        Serial.println("[Gesture] Z+ -> power off in 4 s (shake to cancel)");
        publishGesture("rotation", "positive", "power_off");
        return;
    case Action::PowerOffCancel:
        Serial.println("[Gesture] power off cancelled");
        play(SoundEffect::CANCEL);
        publishUiMode("normal");
        return;
    case Action::PowerOffNow:
        Serial.println("[Gesture] power off");
        if (_onPowerOff) _onPowerOff();
        return;
    }
}

void GestureManager::recoverFromFailedPowerOff() {
    if (!_fsm.recoverFromFailedPowerOff(millis())) return;
    Serial.println("[Gesture] power off failed (USB power?) -> gestures re-enabled");
    if (_onUiState) _onUiState(_fsm.state(), _fsm.stateSinceMs());
}

void GestureManager::play(SoundEffect e) {
    if (_sound && _sound->isInitialized()) _sound->playEffect(e);
}

// 外部通知 (server モードでは sphere/<id>/gesture, sphere/<id>/ui_mode)。
// JSON は派生元の仕様 (sastle-isolation-sphere/server/docs/mqtt_spec.md) と同じ形。Z 軸は旧名の "heading"。
void GestureManager::publishGesture(const char* event, const char* direction, const char* action) {
    if (!_sink) return;
    char json[160];
    if (direction) {
        snprintf(json, sizeof(json),
                 "{\"event\":\"%s\",\"axis\":\"heading\",\"direction\":\"%s\",\"angle\":%.1f,\"action\":\"%s\"}",
                 event, direction, (double)kSelectDeg, action);
    } else {
        snprintf(json, sizeof(json), "{\"event\":\"%s\",\"timestamp\":%lu}", event, (unsigned long)millis());
    }
    _sink("gesture", json);
}

void GestureManager::publishUiMode(const char* mode) {
    if (!_sink) return;
    char json[64];
    snprintf(json, sizeof(json), "{\"mode\":\"%s\",\"timeout\":%lu}", mode, (unsigned long)kMenuTimeoutMs);
    _sink("ui_mode", json);
}
