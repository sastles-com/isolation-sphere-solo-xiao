/**
 * @file GestureManager.h
 * @brief IMUベースのジェスチャー検出クラス
 * @author sastle-com
 * @date 2025-12-01
 */

#ifndef GESTURE_MANAGER_H
#define GESTURE_MANAGER_H

#include <Arduino.h>
#include <functional>
#include "IMUManager.h"
#include "SoundManager.h"

using namespace sastle;

/// 加速度変化閾値 [m/s²]
#define SHAKE_THRESHOLD 15.0f
/// シェイク検出回数
#define SHAKE_COUNT 3
/// シェイク検出時間窓 [ms]
#define SHAKE_WINDOW_MS 2000
/// 最小シェイク間隔 [ms]
#define SHAKE_MIN_INTERVAL_MS 200

/// 回転角度閾値 [度]
#define ROTATION_THRESHOLD 45.0f
/// 中立位置範囲 [度]
#define ROTATION_NEUTRAL 15.0f
/// 角度維持時間 [ms]
#define ROTATION_HOLD_MS 1000

/// UIモードタイムアウト [ms]
#define UI_MODE_TIMEOUT_MS 10000

/**
 * @class GestureManager
 * @brief IMUセンサーを使用したジェスチャー検出・UI制御クラス
 * 
 * トリプルシェイク検出でUIモードに入り、デバイスの回転によって
 * 機能選択を行うジェスチャーインターフェースを提供します。
 */
class GestureManager {
public:
    /**
     * @enum Mode
     * @brief ジェスチャーUIモード
     */
    enum class Mode {
        NORMAL,        ///< 通常モード (ジェスチャー検出待機)
        UI_ACTIVE,     ///< UIモード (機能選択可能)
        UI_SELECTING   ///< 選択中 (角度維持中)
    };
    
    /**
     * @enum Axis
     * @brief 回転検出軸
     */
    enum class Axis {
        ROLL,   ///< X軸回転 (左右傾き)
        PITCH,  ///< Y軸回転 (前後傾き)
        HEADING ///< Z軸回転 (左右回転)
    };
    
    /**
     * @enum Direction
     * @brief 回転方向
     */
    enum class Direction {
        POSITIVE,  ///< 正方向 (右/前/右回転)
        NEGATIVE   ///< 負方向 (左/後/左回転)
    };
    
    GestureManager();
    
    /**
     * @brief ジェスチャー検出システムを初期化
     * @param imu IMUマネージャー参照
     * @param sound サウンドマネージャー参照 (オプション)
     * @return true 初期化成功, false 初期化失敗
     */
    bool begin(IMUManager& imu, SoundManager* sound = nullptr);
    
    /**
     * @brief ジェスチャー検出を更新
     * @note メインループ内で定期的に呼び出す必要があります
     */
    void update();
    
    /**
     * @brief UIモード変更時のコールバック関数を設定
     * @param callback コールバック関数 (引数: Mode)
     * @note 音声/LED フィードバックの実装に使用します
     */
    void setOnModeChange(std::function<void(Mode)> callback);
    
    /**
     * @brief ジェスチャー選択時のコールバック関数を設定
     * @param callback コールバック関数 (引数: Axis, Direction)
     * @note 音声/LED フィードバックの実装に使用します
     */
    void setOnSelection(std::function<void(Axis, Direction)> callback);
    
    /**
     * @brief トリプルシェイクの直接ハンドラを登録する
     * @param callback 登録するとトリプルシェイクは UI モードに入らず、これだけを呼ぶ
     *                 (solo では AP の ON/OFF 切替。UI モードの回転アクションは未実装のため)
     */
    void setOnTripleShake(std::function<void()> callback) { _onTripleShake = callback; }

    /**
     * @brief 現在のモードを取得
     * @return 現在のMode
     */
    Mode getMode() const { return _mode; }

    /**
     * @brief 検出イベントの外部通知先を登録する (server モードでは MQTT publish)
     * @param sink (suffix, json) を受ける関数。suffix は "gesture" / "ui_mode"
     *             (派生元 core と同じトピック sphere/<id>/<suffix>、同じ JSON)
     */
    void setEventSink(std::function<void(const char* suffix, const char* json)> sink) { _sink = sink; }
    
private:
    IMUManager* _imu;           ///< IMUマネージャーポインタ
    SoundManager* _sound;       ///< サウンドマネージャーポインタ (オプション)
    
    Mode _mode;                 ///< 現在のモード
    unsigned long _uiModeStartTime;  ///< UIモード開始時刻
    
    // シェイク検出用
    float _lastAccelMagnitude;  ///< 前回の加速度ノルム
    unsigned long _shakeTimestamps[SHAKE_COUNT];  ///< シェイク発生時刻配列
    int _shakeCount;            ///< 検出したシェイク回数
    unsigned long _lastShakeTime;  ///< 最終シェイク時刻
    
    // 回転検出用
    float _baseRoll;            ///< 基準ロール角
    float _basePitch;           ///< 基準ピッチ角
    float _baseHeading;         ///< 基準ヘディング角
    unsigned long _rotationStartTime;  ///< 回転開始時刻
    Axis _currentAxis;          ///< 現在検出中の軸
    Direction _currentDirection; ///< 現在検出中の方向
    bool _isHolding;            ///< 角度維持中フラグ
    
    // コールバック
    std::function<void()> _onTripleShake;  ///< 登録時はトリプルシェイクで UI モードに入らず呼ぶ
    std::function<void(Mode)> _onModeChange;  ///< モード変更コールバック
    std::function<void(Axis, Direction)> _onSelection;  ///< 選択コールバック
    std::function<void(const char*, const char*)> _sink;  ///< 外部通知 (MQTT)。未登録ならログのみ

    /// 派生元と同じ JSON を組んで sink に渡す
    void publishGestureEvent(const char* event);
    void publishRotationEvent(Axis axis, Direction dir, float angle, const char* action);
    void publishUIModeEvent(const char* mode);
    
    /**
     * @brief シェイク検出処理
     * @return true シェイク検出, false 未検出
     */
    bool detectShake();
    
    /**
     * @brief シェイク履歴を更新
     */
    void updateShakeHistory();
    
    /**
     * @brief 回転検出処理
     * @param axis 検出した回転軸 (出力)
     * @param dir 検出した回転方向 (出力)
     * @param angle 検出した回転角度 (出力)
     * @return true 回転検出, false 未検出
     */
    bool detectRotation(Axis& axis, Direction& dir, float& angle);
    
    /**
     * @brief UIモードに入る
     */
    void enterUIMode();
    
    /**
     * @brief UIモードから出る
     */
    void exitUIMode();
    
    /**
     * @brief ジェスチャーアクションを実行
     * @param axis 軸
     * @param dir 方向
     */
    void executeAction(Axis axis, Direction dir);
    
    /**
     * @brief 検出イベントをログ出力する
     * @note solo 構成では外部への通知先が無いため、検出結果は Serial ログに残すだけ。
     *       LED/サウンドのフィードバックは setOnModeChange / setOnSelection で受ける。
     */
    void logEvent(const char* event);
    
    /**
     * @brief 軸を文字列に変換
     * @param axis 軸
     * @return 軸名文字列
     */
    const char* axisToString(Axis axis);
    
    /**
     * @brief 方向を文字列に変換
     * @param dir 方向
     * @return 方向名文字列
     */
    const char* directionToString(Direction dir);
    
    /**
     * @brief アクション名を取得
     * @param axis 軸
     * @param dir 方向
     * @return アクション名文字列
     */
    const char* actionToString(Axis axis, Direction dir);
};

#endif // GESTURE_MANAGER_H
