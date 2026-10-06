#include "GestureManager.h"
#include <cmath>

GestureManager::GestureManager()
    : _imu(nullptr)
    , _sound(nullptr)
    , _mode(Mode::NORMAL)
    , _uiModeStartTime(0)
    , _lastAccelMagnitude(0.0f)
    , _shakeCount(0)
    , _lastShakeTime(0)
    , _baseRoll(0.0f)
    , _basePitch(0.0f)
    , _baseHeading(0.0f)
    , _rotationStartTime(0)
    , _currentAxis(Axis::ROLL)
    , _currentDirection(Direction::POSITIVE)
    , _isHolding(false)
{
    for (int i = 0; i < SHAKE_COUNT; i++) {
        _shakeTimestamps[i] = 0;
    }
}

bool GestureManager::begin(IMUManager& imu, SoundManager* sound) {
    _imu = &imu;
    _sound = sound;
    
    if (!_imu->isInitialized()) {
        Serial.println("[Gesture] IMU not initialized");
        return false;
    }
    
    Serial.println("[Gesture] Initialized");
    Serial.printf("  Shake threshold: %.1f m/s²\n", SHAKE_THRESHOLD);
    Serial.printf("  Rotation threshold: %.1f degrees\n", ROTATION_THRESHOLD);
    Serial.printf("  UI timeout: %d ms\n", UI_MODE_TIMEOUT_MS);
    
    return true;
}

void GestureManager::update() {
    if (!_imu || !_imu->isInitialized()) {
        return;
    }
    
    switch (_mode) {
        case Mode::NORMAL:
            // シェイク検出
            if (detectShake()) {
                if (_onTripleShake) {
                    logEvent("triple_shake -> direct action");
                    publishGestureEvent("triple_shake");
                    _onTripleShake();
                } else {
                    enterUIMode();
                }
            }
            break;
            
        case Mode::UI_ACTIVE:
        case Mode::UI_SELECTING:
            // タイムアウトチェック
            if (millis() - _uiModeStartTime > UI_MODE_TIMEOUT_MS) {
                Serial.println("[Gesture] UI mode timeout");
                exitUIMode();
                break;
            }
            
            // 回転検出
            Axis axis;
            Direction dir;
            float angle;
            if (detectRotation(axis, dir, angle)) {
                executeAction(axis, dir);
                exitUIMode();
            }
            break;
    }
}

bool GestureManager::detectShake() {
    imu::Vector<3> accel = _imu->getAccel();
    
    // 加速度の大きさを計算
    float magnitude = sqrt(accel.x() * accel.x() + 
                          accel.y() * accel.y() + 
                          accel.z() * accel.z());
    
    // 加速度変化量を計算
    float delta = fabs(magnitude - _lastAccelMagnitude);
    _lastAccelMagnitude = magnitude;
    
    unsigned long now = millis();
    
    // 閾値を超えたか
    if (delta > SHAKE_THRESHOLD) {
        // 最小間隔チェック
        if (now - _lastShakeTime < SHAKE_MIN_INTERVAL_MS) {
            return false;
        }
        
        _lastShakeTime = now;
        
        // シェイク履歴を更新
        for (int i = SHAKE_COUNT - 1; i > 0; i--) {
            _shakeTimestamps[i] = _shakeTimestamps[i - 1];
        }
        _shakeTimestamps[0] = now;
        
        // 3回のシェイクが時間窓内にあるかチェック
        if (_shakeTimestamps[SHAKE_COUNT - 1] > 0 &&
            (now - _shakeTimestamps[SHAKE_COUNT - 1]) <= SHAKE_WINDOW_MS) {
            
            Serial.println("[Gesture] Triple shake detected!");
            
            // サウンドフィードバック
            if (_sound && _sound->isInitialized()) {
                _sound->playEffect(SoundEffect::SHAKE_DETECTED);
            }
            
            // 履歴をリセット
            for (int i = 0; i < SHAKE_COUNT; i++) {
                _shakeTimestamps[i] = 0;
            }
            
            return true;
        }
    }
    
    return false;
}

bool GestureManager::detectRotation(Axis& axis, Direction& dir, float& angle) {
    imu::Vector<3> euler = _imu->getEuler();
    
    float currentRoll = euler.z();     // Roll
    float currentPitch = euler.y();    // Pitch
    float currentHeading = euler.x();  // Heading
    
    // UIモード突入時の基準角度を記録
    if (!_isHolding) {
        _baseRoll = currentRoll;
        _basePitch = currentPitch;
        _baseHeading = currentHeading;
    }
    
    // 各軸の角度差を計算
    float rollDelta = currentRoll - _baseRoll;
    float pitchDelta = currentPitch - _basePitch;
    float headingDelta = currentHeading - _baseHeading;
    
    // -180~180度の範囲に正規化
    while (headingDelta > 180.0f) headingDelta -= 360.0f;
    while (headingDelta < -180.0f) headingDelta += 360.0f;
    
    // 最大の角度変化を持つ軸を検出
    float maxDelta = 0.0f;
    Axis detectedAxis = Axis::ROLL;
    
    if (fabs(rollDelta) > fabs(maxDelta)) {
        maxDelta = rollDelta;
        detectedAxis = Axis::ROLL;
    }
    if (fabs(pitchDelta) > fabs(maxDelta)) {
        maxDelta = pitchDelta;
        detectedAxis = Axis::PITCH;
    }
    if (fabs(headingDelta) > fabs(maxDelta)) {
        maxDelta = headingDelta;
        detectedAxis = Axis::HEADING;
    }
    
    // 閾値を超えているか
    if (fabs(maxDelta) > ROTATION_THRESHOLD) {
        if (!_isHolding) {
            // 選択開始
            _isHolding = true;
            _rotationStartTime = millis();
            _currentAxis = detectedAxis;
            _currentDirection = (maxDelta > 0) ? Direction::POSITIVE : Direction::NEGATIVE;
            _mode = Mode::UI_SELECTING;
            
            Serial.printf("[Gesture] Rotation detected: %s %s (%.1f degrees)\n",
                         axisToString(_currentAxis),
                         directionToString(_currentDirection),
                         fabs(maxDelta));
            
            // コールバック呼び出し
            if (_onSelection) {
                _onSelection(_currentAxis, _currentDirection);
            }
        }
        
        // 一定時間維持したら確定
        if (millis() - _rotationStartTime > ROTATION_HOLD_MS) {
            axis = _currentAxis;
            dir = _currentDirection;
            angle = fabs(maxDelta);
            return true;
        }
    } else if (_isHolding && fabs(maxDelta) < ROTATION_NEUTRAL) {
        // 中立位置に戻ったら即座に確定
        axis = _currentAxis;
        dir = _currentDirection;
        angle = ROTATION_THRESHOLD; // 閾値を返す
        return true;
    }
    
    return false;
}

void GestureManager::enterUIMode() {
    _mode = Mode::UI_ACTIVE;
    _uiModeStartTime = millis();
    _isHolding = false;
    
    Serial.println("[Gesture] Entered UI mode");
    
    // サウンドフィードバック
    if (_sound && _sound->isInitialized()) {
        _sound->playEffect(SoundEffect::UI_MODE_ENTER);
    }
    
    // 基準角度を記録
    imu::Vector<3> euler = _imu->getEuler();
    _baseRoll = euler.z();
    _basePitch = euler.y();
    _baseHeading = euler.x();
    
    // コールバック呼び出し
    if (_onModeChange) {
        _onModeChange(_mode);
    }
    
    logEvent("triple_shake -> ui_active");
    publishGestureEvent("triple_shake");
    publishUIModeEvent("active");
}

void GestureManager::exitUIMode() {
    _mode = Mode::NORMAL;
    _isHolding = false;
    
    Serial.println("[Gesture] Exited UI mode");
    
    // サウンドフィードバック
    if (_sound && _sound->isInitialized()) {
        _sound->playEffect(SoundEffect::UI_MODE_EXIT);
    }
    
    // コールバック呼び出し
    if (_onModeChange) {
        _onModeChange(_mode);
    }
    
    logEvent("ui_normal");
    publishUIModeEvent("normal");
}

void GestureManager::executeAction(Axis axis, Direction dir) {
    const char* action = actionToString(axis, dir);
    
    Serial.printf("[Gesture] Action: %s\n", action);
    
    // サウンドフィードバック
    if (_sound && _sound->isInitialized()) {
        _sound->playEffect(SoundEffect::CONFIRM);
    }
    
    logEvent(action);
    publishRotationEvent(axis, dir, ROTATION_THRESHOLD, action);

    // TODO: 実際のアクション実行（画像切り替え、輝度変更など）
    // これは後でImageManager、LEDManagerと連携
}

void GestureManager::logEvent(const char* event) {
    Serial.printf("[Gesture] %s (t=%lu)\n", event ? event : "?", millis());
}

// 外部通知 (server モードでは sphere/<id>/gesture, sphere/<id>/ui_mode)。JSON は派生元と同一。
void GestureManager::publishGestureEvent(const char* event) {
    if (!_sink) return;
    char json[96];
    snprintf(json, sizeof(json), "{\"event\":\"%s\",\"timestamp\":%lu}", event, (unsigned long)millis());
    _sink("gesture", json);
}

void GestureManager::publishRotationEvent(Axis axis, Direction dir, float angle, const char* action) {
    if (!_sink) return;
    char json[160];
    snprintf(json, sizeof(json),
             "{\"event\":\"rotation\",\"axis\":\"%s\",\"direction\":\"%s\",\"angle\":%.1f,\"action\":\"%s\"}",
             axisToString(axis), directionToString(dir), angle, action);
    _sink("gesture", json);
}

void GestureManager::publishUIModeEvent(const char* mode) {
    if (!_sink) return;
    char json[64];
    snprintf(json, sizeof(json), "{\"mode\":\"%s\",\"timeout\":%d}", mode, (int)UI_MODE_TIMEOUT_MS);
    _sink("ui_mode", json);
}

void GestureManager::setOnModeChange(std::function<void(Mode)> callback) {
    _onModeChange = callback;
}

void GestureManager::setOnSelection(std::function<void(Axis, Direction)> callback) {
    _onSelection = callback;
}

const char* GestureManager::axisToString(Axis axis) {
    switch (axis) {
        case Axis::ROLL:    return "roll";
        case Axis::PITCH:   return "pitch";
        case Axis::HEADING: return "heading";
        default:            return "unknown";
    }
}

const char* GestureManager::directionToString(Direction dir) {
    switch (dir) {
        case Direction::POSITIVE: return "positive";
        case Direction::NEGATIVE: return "negative";
        default:                  return "unknown";
    }
}

const char* GestureManager::actionToString(Axis axis, Direction dir) {
    if (axis == Axis::ROLL) {
        return (dir == Direction::POSITIVE) ? "next_image" : "prev_image";
    } else if (axis == Axis::PITCH) {
        return (dir == Direction::POSITIVE) ? "brightness_up" : "brightness_down";
    } else if (axis == Axis::HEADING) {
        return (dir == Direction::POSITIVE) ? "next_mode" : "prev_mode";
    }
    return "unknown";
}
