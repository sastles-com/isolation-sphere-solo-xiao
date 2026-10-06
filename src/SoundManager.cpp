/**
 * @file SoundManager.cpp
 * @brief SoundManager実装
 */

#include "SoundManager.h"

namespace sastle {

// 音階周波数テーブル (Hz)
static const float NOTE_FREQUENCIES[] = {
    261.63f,  // C4
    277.18f,  // C#4
    293.66f,  // D4
    311.13f,  // D#4
    329.63f,  // E4
    349.23f,  // F4
    369.99f,  // F#4
    392.00f,  // G4
    415.30f,  // G#4
    440.00f,  // A4
    466.16f,  // A#4
    493.88f,  // B4
    523.25f,  // C5
    587.33f,  // D5
    659.25f,  // E5
    783.99f,  // G5
    0.0f      // SILENCE
};

SoundManager::SoundManager()
    : _gpio(BUZZER_DEFAULT_GPIO),
      _ledcChannel(BUZZER_LEDC_CHANNEL),
      _volume(BUZZER_DEFAULT_VOLUME),
      _muted(false),
      _initialized(false),
      _playing(false),
      _totalPlays(0),
      _effectPlays(0),
      _lastPlayTime(0),
      _currentFrequency(0.0f) {
}

SoundManager::~SoundManager() {
    end();
}

bool SoundManager::begin(ConfigManager& config, uint8_t gpio) {
    if (_initialized) {
        Serial.println("[SoundManager] Already initialized");
        return true;
    }

    _gpio = gpio;
    
    // config.jsonからサウンド設定を読み込み (将来の拡張用)
    // 現時点ではデフォルト値を使用
    
    Serial.printf("[SoundManager] Initializing on GPIO %d\n", _gpio);
    
    if (!configureLedc()) {
        Serial.println("[SoundManager] LEDC configuration failed");
        return false;
    }
    
    _initialized = true;
    Serial.println("[SoundManager] Initialized successfully");

    return true;
}

void SoundManager::end() {
    if (!_initialized) {
        return;
    }
    
    stop();
    ledcDetachPin(_gpio);
    _initialized = false;
    
    Serial.println("[SoundManager] Deinitialized");
}

bool SoundManager::configureLedc() {
    // LEDC PWM設定
    ledcSetup(_ledcChannel, BUZZER_LEDC_BASE_FREQ, BUZZER_LEDC_RESOLUTION);
    ledcAttachPin(_gpio, _ledcChannel);
    ledcWrite(_ledcChannel, 0);  // 初期状態はオフ
    
    return true;
}

void SoundManager::playEffect(SoundEffect effect) {
    if (!_initialized || _muted) {
        return;
    }
    
    updateStats(true);
    
    switch (effect) {
        case SoundEffect::BEEP:
            generateBeep();
            break;
        case SoundEffect::CONFIRM:
            generateConfirm();
            break;
        case SoundEffect::CANCEL:
            generateCancel();
            break;
        case SoundEffect::ERROR:
            generateError();
            break;
        case SoundEffect::STARTUP:
            generateStartup();
            break;
        case SoundEffect::SHAKE_DETECTED:
            generateShakeDetected();
            break;
        case SoundEffect::UI_MODE_ENTER:
            generateUIModeEnter();
            break;
        case SoundEffect::UI_MODE_EXIT:
            generateUIModeExit();
            break;
        default:
            generateBeep();
            break;
    }
}

void SoundManager::playNote(BuzzerNote note, uint16_t duration_ms) {
    float freq = getNoteFrequency(note);
    playTone(freq, duration_ms);
}

void SoundManager::playTone(float frequency_hz, uint16_t duration_ms) {
    if (!_initialized || _muted || frequency_hz <= 0.0f) {
        return;
    }
    
    updateStats(false);
    
    _playing = true;
    _currentFrequency = frequency_hz;
    
    startTone(frequency_hz, _volume);
    delay(duration_ms);
    stopTone();
    
    _playing = false;
}

void SoundManager::stop() {
    stopTone();
    _playing = false;
    _currentFrequency = 0.0f;
}

void SoundManager::setVolume(uint8_t volume) {
    _volume = min(volume, BUZZER_MAX_VOLUME);
    Serial.printf("[SoundManager] Volume set to %d%%\n", _volume);
}

void SoundManager::setMute(bool muted) {
    _muted = muted;
    if (_muted && _playing) {
        stop();
    }
    Serial.printf("[SoundManager] Mute: %s\n", _muted ? "ON" : "OFF");
}

SoundStats SoundManager::getStats() const {
    SoundStats stats;
    stats.total_plays = _totalPlays;
    stats.effect_plays = _effectPlays;
    stats.last_play_time = _lastPlayTime;
    stats.current_frequency = _currentFrequency;
    stats.current_volume = _volume;
    stats.is_playing = _playing;
    stats.is_muted = _muted;
    return stats;
}

float SoundManager::getNoteFrequency(BuzzerNote note) {
    int index = static_cast<int>(note);
    if (index >= 0 && index < sizeof(NOTE_FREQUENCIES) / sizeof(NOTE_FREQUENCIES[0])) {
        return NOTE_FREQUENCIES[index];
    }
    return 0.0f;
}

void SoundManager::startTone(float frequency_hz, uint8_t volume) {
    if (frequency_hz <= 0.0f) {
        stopTone();
        return;
    }
    
    // 音量を0-100から0-255のduty比に変換
    uint32_t duty = map(volume, 0, 100, 0, 255);
    duty = duty / 2;  // 50% duty cycle maximum for buzzer
    
    ledcWriteTone(_ledcChannel, frequency_hz);
    ledcWrite(_ledcChannel, duty);
}

void SoundManager::stopTone() {
    ledcWrite(_ledcChannel, 0);
}

void SoundManager::updateStats(bool is_effect) {
    _totalPlays++;
    if (is_effect) {
        _effectPlays++;
    }
    _lastPlayTime = millis();
}

// ========== 効果音生成関数 ==========

void SoundManager::generateBeep() {
    // 短いビープ音: 1000Hz, 50ms
    playTone(1000.0f, 50);
}

void SoundManager::generateConfirm() {
    // 上昇トーン: C4 -> E4
    playNote(BuzzerNote::C4, 80);
    delay(10);
    playNote(BuzzerNote::E4, 120);
}

void SoundManager::generateCancel() {
    // 下降トーン: E4 -> C4
    playNote(BuzzerNote::E4, 80);
    delay(10);
    playNote(BuzzerNote::C4, 120);
}

void SoundManager::generateError() {
    // エラー音: 低い音を3回
    for (int i = 0; i < 3; i++) {
        playTone(200.0f, 100);
        delay(50);
    }
}

void SoundManager::generateStartup() {
    // 起動メロディ: C4 -> E4 -> G4 -> C5
    playNote(BuzzerNote::C4, 100);
    delay(30);
    playNote(BuzzerNote::E4, 100);
    delay(30);
    playNote(BuzzerNote::G4, 100);
    delay(30);
    playNote(BuzzerNote::C5, 200);
}

void SoundManager::generateShakeDetected() {
    // 3連音: 短い高音を3回
    for (int i = 0; i < 3; i++) {
        playNote(BuzzerNote::E5, 60);
        delay(40);
    }
}

void SoundManager::generateUIModeEnter() {
    // UIモード開始: 上昇アルペジオ
    playNote(BuzzerNote::C4, 70);
    delay(20);
    playNote(BuzzerNote::E4, 70);
    delay(20);
    playNote(BuzzerNote::G5, 150);
}

void SoundManager::generateUIModeExit() {
    // UIモード終了: 下降トーン
    playNote(BuzzerNote::G4, 80);
    delay(20);
    playNote(BuzzerNote::C4, 120);
}

} // namespace sastle
