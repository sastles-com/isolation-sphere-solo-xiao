/**
 * @file SoundManager.h
 * @brief PWMブザー制御による効果音出力管理クラス
 * @author sastle-com
 * @date 2025-12-01
 */

#pragma once

#include <Arduino.h>
#include "driver/ledc.h"
#include "ConfigManager.h"
#include "BoardConfig.h"

namespace sastle {

/// デフォルトGPIOピン番号 (ボード別ヘッダ src/boards/board_*.h で定義)
constexpr uint8_t BUZZER_DEFAULT_GPIO = kBuzzerGpio;
/// LEDCチャンネル番号
constexpr uint8_t BUZZER_LEDC_CHANNEL = 1;
/// LEDC基本周波数
constexpr uint32_t BUZZER_LEDC_BASE_FREQ = 12000;
/// LEDC分解能（ビット）
constexpr uint8_t BUZZER_LEDC_RESOLUTION = 8;
/// デフォルト音量
constexpr uint8_t BUZZER_DEFAULT_VOLUME = 50;
/// 最大音量
constexpr uint8_t BUZZER_MAX_VOLUME = 100;
/// メロディ最大音符数
constexpr size_t BUZZER_MAX_MELODY_NOTES = 32;

/**
 * @enum SoundEffect
 * @brief 効果音の種類
 */
enum class SoundEffect {
    BEEP,           ///< 短いビープ音 (UI入力フィードバック)
    CONFIRM,        ///< 確認音 (選択決定時)
    CANCEL,         ///< キャンセル音 (UI終了時)
    ERROR,          ///< エラー音
    STARTUP,        ///< 起動音
    SHAKE_DETECTED, ///< シェイク検出音
    UI_MODE_ENTER,  ///< UIモード開始音
    UI_MODE_EXIT,   ///< UIモード終了音
    SHUTDOWN        ///< 電源 OFF (起動音の逆)
};

/**
 * @enum BuzzerNote
 * @brief 音階定義
 */
enum class BuzzerNote {
    C4 = 0,   ///< ド (261.63 Hz)
    CS4,      ///< ド# (277.18 Hz)
    D4,       ///< レ (293.66 Hz)
    DS4,      ///< レ# (311.13 Hz)
    E4,       ///< ミ (329.63 Hz)
    F4,       ///< ファ (349.23 Hz)
    FS4,      ///< ファ# (369.99 Hz)
    G4,       ///< ソ (392.00 Hz)
    GS4,      ///< ソ# (415.30 Hz)
    A4,       ///< ラ (440.00 Hz)
    AS4,      ///< ラ# (466.16 Hz)
    B4,       ///< シ (493.88 Hz)
    C5,       ///< ド (523.25 Hz)
    D5,       ///< レ (587.33 Hz)
    E5,       ///< ミ (659.25 Hz)
    G5,       ///< ソ (783.99 Hz)
    SILENCE   ///< 無音
};

/**
 * @struct SoundStats
 * @brief サウンド統計情報
 */
struct SoundStats {
    uint32_t total_plays;      ///< 総再生回数
    uint32_t effect_plays;     ///< 効果音再生回数
    uint32_t last_play_time;   ///< 最終再生時刻 (ms)
    float current_frequency;   ///< 現在の周波数 (Hz)
    uint8_t current_volume;    ///< 現在の音量 (0-100)
    bool is_playing;           ///< 再生中フラグ
    bool is_muted;             ///< ミュート状態
};

/**
 * @class SoundManager
 * @brief PWMブザーを使用した効果音出力管理クラス
 * 
 * ESP32のLEDC PWMを使用して圧電ブザーを制御し、
 * システムイベントやジェスチャーフィードバック用の効果音を再生します。
 */
class SoundManager {
public:
    SoundManager();
    ~SoundManager();
    
    /**
     * @brief ブザーシステムを初期化
     * @param config 設定マネージャー参照
     * @param gpio 出力GPIOピン番号 (デフォルト: BUZZER_DEFAULT_GPIO)
     * @return true 初期化成功, false 初期化失敗
     */
    bool begin(ConfigManager& config, uint8_t gpio = BUZZER_DEFAULT_GPIO);
    
    /**
     * @brief ブザーシステムを終了
     */
    void end();
    
    /**
     * @brief 効果音を再生
     * @param effect 効果音の種類
     */
    void playEffect(SoundEffect effect);
    
    /**
     * @brief 音符を再生
     * @param note 音階
     * @param duration_ms 再生時間 (ms)
     */
    void playNote(BuzzerNote note, uint16_t duration_ms);
    
    /**
     * @brief 任意周波数のトーンを再生
     * @param frequency_hz 周波数 (Hz)
     * @param duration_ms 再生時間 (ms)
     */
    void playTone(float frequency_hz, uint16_t duration_ms);
    
    /**
     * @brief 再生を停止
     */
    void stop();
    
    /**
     * @brief 音量を設定
     * @param volume 音量 (0-100)
     */
    void setVolume(uint8_t volume);
    
    /**
     * @brief 現在の音量を取得
     * @return 音量 (0-100)
     */
    uint8_t getVolume() const { return _volume; }
    
    /**
     * @brief ミュート状態を設定
     * @param muted true=ミュート, false=ミュート解除
     */
    void setMute(bool muted);
    
    /**
     * @brief ミュート状態を取得
     * @return true=ミュート中, false=ミュート解除
     */
    bool isMuted() const { return _muted; }
    
    /**
     * @brief 再生中かどうかを取得
     * @return true=再生中, false=停止中
     */
    bool isPlaying() const { return _playing; }
    
    /**
     * @brief 初期化状態を取得
     * @return true=初期化済み, false=未初期化
     */
    bool isInitialized() const { return _initialized; }
    
    /**
     * @brief 統計情報を取得
     * @return SoundStats構造体
     */
    SoundStats getStats() const;
    
    /**
     * @brief 音階から周波数を取得
     * @param note 音階
     * @return 周波数 (Hz), SILENCE の場合は 0.0
     */
    static float getNoteFrequency(BuzzerNote note);
    
private:
    uint8_t _gpio;             ///< 出力GPIOピン番号
    uint8_t _ledcChannel;      ///< LEDCチャンネル
    uint8_t _volume;           ///< 音量 (0-100)
    bool _muted;               ///< ミュート状態
    bool _initialized;         ///< 初期化状態
    bool _playing;             ///< 再生中フラグ
    
    uint32_t _totalPlays;      ///< 総再生回数
    uint32_t _effectPlays;     ///< 効果音再生回数
    uint32_t _lastPlayTime;    ///< 最終再生時刻
    float _currentFrequency;   ///< 現在の周波数
    
    /**
     * @brief LEDC PWMを設定
     * @return true 設定成功, false 設定失敗
     */
    bool configureLedc();
    
    /**
     * @brief トーン出力を開始
     * @param frequency_hz 周波数 (Hz)
     * @param volume 音量 (0-100)
     */
    void startTone(float frequency_hz, uint8_t volume);
    
    /**
     * @brief トーン出力を停止
     */
    void stopTone();
    
    /**
     * @brief 統計情報を更新
     * @param is_effect 効果音フラグ
     */
    void updateStats(bool is_effect);
    
    /**
     * @brief ビープ音を生成 (短い単音)
     */
    void generateBeep();
    
    /**
     * @brief 確認音を生成 (上昇トーン)
     */
    void generateConfirm();
    
    /**
     * @brief キャンセル音を生成 (下降トーン)
     */
    void generateCancel();
    
    /**
     * @brief エラー音を生成 (低い連続音)
     */
    void generateError();
    
    /**
     * @brief 起動音を生成 (上昇メロディ)
     */
    void generateStartup();
    void generateShutdown();
    
    /**
     * @brief シェイク検出音を生成 (3連音)
     */
    void generateShakeDetected();
    
    /**
     * @brief UIモード開始音を生成
     */
    void generateUIModeEnter();
    
    /**
     * @brief UIモード終了音を生成
     */
    void generateUIModeExit();
};

} // namespace sastle
