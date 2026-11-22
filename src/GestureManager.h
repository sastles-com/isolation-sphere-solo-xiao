/**
 * @file GestureManager.h
 * @brief IMU のジェスチャー操作 (トリプルシェイク → 回転メニュー → AP 切替 / 電源 OFF)
 * @author sastle-com
 *
 * 判定は GestureLogic.h (純粋ロジック、native テスト済み)。このクラスは IMU から値を
 * 読んで渡し、結果を効果音・コールバックに変換するだけ。操作の一覧は GestureLogic.h の冒頭。
 */

#ifndef GESTURE_MANAGER_H
#define GESTURE_MANAGER_H

#include <Arduino.h>
#include <functional>
#include "IMUManager.h"
#include "SoundManager.h"
#include "GestureLogic.h"

using namespace sastle;

class GestureManager {
public:
    using UiState = sastle::gesture_logic::UiState;

    /**
     * @brief 初期化。起動からの保護時間 (kBootGuardMs) はここから数える
     * @param sound 効果音 (nullptr なら鳴らさない)
     */
    bool begin(IMUManager& imu, SoundManager* sound = nullptr);

    /// メインループから毎回呼ぶ
    void update();

    /// Z− 確定: AP の ON/OFF 切替
    void setOnApToggle(std::function<void()> cb) { _onApToggle = cb; }
    /// Z+ の予告が終わった: 電源を切る
    void setOnPowerOff(std::function<void()> cb) { _onPowerOff = cb; }
    /// 状態が変わった (LED の表示用)。sinceMs はその状態に入った millis()
    void setOnUiState(std::function<void(UiState, uint32_t sinceMs)> cb) { _onUiState = cb; }

    UiState state() const { return _fsm.state(); }

    /// 電源 OFF に失敗した (USB 給電中など) ときに呼ぶ。操作と LED 表示を通常に戻す
    void recoverFromFailedPowerOff();

    /**
     * @brief 検出イベントの外部通知先を登録する (server モードでは MQTT publish)
     * @param sink (suffix, json) を受ける関数。suffix は "gesture" / "ui_mode"
     */
    void setEventSink(std::function<void(const char* suffix, const char* json)> sink) { _sink = sink; }

private:
    IMUManager* _imu = nullptr;
    SoundManager* _sound = nullptr;
    sastle::gesture_logic::ShakeDetector _shake;
    sastle::gesture_logic::GestureFsm _fsm;
    int8_t _lastBeepSec = -1;   ///< 予告中の毎秒の音 (同じ秒で 2 回鳴らさない)

    std::function<void()> _onApToggle;
    std::function<void()> _onPowerOff;
    std::function<void(UiState, uint32_t)> _onUiState;
    std::function<void(const char*, const char*)> _sink;

    void handle(sastle::gesture_logic::Action a);
    void play(SoundEffect e);
    void publishGesture(const char* event, const char* direction, const char* action);
    void publishUiMode(const char* mode);
};

#endif // GESTURE_MANAGER_H
