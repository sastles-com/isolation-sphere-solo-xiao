/**
 * @file GestureLogic.h
 * @brief シェイク / 回転メニュー / 電源 OFF 受付の判定ロジック (純粋、Arduino 非依存)
 *
 * 操作:
 *   1. トリプルシェイク (2 秒以内に 3 回) で回転メニューに入る。映像が暗くなり ±Z の点が出る。
 *   2. Z 軸 (青い点の軸) のまわりに 45° 以上回して 1 秒保持すると確定する。
 *        Z− : AP の ON/OFF 切替
 *        Z+ : 電源 OFF の受付 → 4 秒の予告 (明滅が速くなりながら暗くなる)。途中でシェイク 1 回で取り消し
 *      X / Y 軸の回転は今は何も割り当てていない (無視して待ち続ける)。
 *   3. 10 秒何も確定しなければメニューを抜ける。
 *   基準姿勢は、メニューに入ってから 0.5 秒 (振り終わりの揺れ) の最後の姿勢。
 *
 * 時刻・加速度・姿勢は呼び出し側が注入する (GestureManager が IMU から渡す)。
 * native テスト: test/test_gesture_logic
 */
#pragma once
#include <math.h>
#include <stdint.h>
#include "imu/Quat.h"

namespace sastle {
namespace gesture_logic {

// --- シェイク ---
constexpr float    kShakeThreshold     = 15.0f;  ///< 加速度ノルムの前回サンプルとの差 [m/s²]
constexpr uint32_t kShakeMinIntervalMs = 200;    ///< 1 回のシェイクで複数回数えない間隔
constexpr uint8_t  kShakeCount         = 3;      ///< メニューに入るシェイク回数
constexpr uint32_t kShakeWindowMs      = 2000;   ///< その回数を数える時間窓

// --- メニュー ---
constexpr uint32_t kBootGuardMs   = 5000;   ///< 起動直後 (磁石を当てて電源を入れた直後) はメニューに入らない
constexpr uint32_t kMenuTimeoutMs = 10000;  ///< メニューで何も確定しないまま経つと抜ける
constexpr uint32_t kMenuSettleMs  = 500;    ///< メニューに入ってからこの間は振り終わりの揺れとみなし、基準姿勢を取り直し続ける
constexpr float    kSelectDeg     = 45.0f;  ///< 選択に必要な回転角 [度]
constexpr uint32_t kSelectHoldMs  = 1000;   ///< その角度を保持する時間

// --- 電源 OFF の受付 ---
constexpr uint32_t kPowerOffConfirmMs = 4000;  ///< 予告の長さ。この間にシェイク 1 回で取り消し
constexpr float    kBlinkStartHz      = 1.0f;  ///< 予告の明滅: 開始時の周波数
constexpr float    kBlinkEndHz        = 6.0f;  ///< 予告の明滅: 終了時の周波数
constexpr float    kDimEnd            = 0.1f;  ///< 予告の明るさ: 終了時 (開始時 1.0 から直線で下げる)
constexpr uint8_t  kMenuDimScale      = 64;    ///< メニュー中の映像の明るさ (255 = そのまま)
constexpr uint8_t  kWarnTint          = 160;   ///< 予告中に映像を赤へ寄せる割合 (255 = 赤一色)。暗い映像でも見えるように

/// シェイク検出。加速度ノルムを毎回渡す。
class ShakeDetector {
public:
    struct Result {
        bool shake = false;   ///< 今回 1 回のシェイクを検出した
        bool triple = false;  ///< 今回のシェイクで時間窓内 kShakeCount 回に達した
    };

    Result feed(uint32_t nowMs, float accelMag) {
        Result r;
        const bool first = !_hasLast;
        const float delta = fabsf(accelMag - _last);
        _last = accelMag;
        _hasLast = true;
        if (first || !(delta > kShakeThreshold)) return r;
        if (_hasShake && nowMs - _lastShakeMs < kShakeMinIntervalMs) return r;

        r.shake = true;
        _hasShake = true;
        _lastShakeMs = nowMs;
        for (uint8_t i = kShakeCount - 1; i > 0; i--) _times[i] = _times[i - 1];
        _times[0] = nowMs;
        if (_count < kShakeCount) _count++;
        if (_count >= kShakeCount && nowMs - _times[kShakeCount - 1] <= kShakeWindowMs) {
            r.triple = true;
            _count = 0;   // 続けて振っても次の 3 回までは数え直し
        }
        return r;
    }

private:
    float _last = 0.0f;
    bool _hasLast = false;
    bool _hasShake = false;
    uint32_t _lastShakeMs = 0;            ///< 最小間隔の判定用 (3 回に達して数え直した後も効かせる)
    uint32_t _times[kShakeCount] = {0};   ///< [0] が最新
    uint8_t _count = 0;
};

/// a ⊗ b (Hamilton 積)
static inline Quat quatMul(const Quat& a, const Quat& b) {
    return Quat(a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
                a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w);
}

static inline Quat quatConj(const Quat& q) { return Quat(q.w, -q.x, -q.y, -q.z); }

/**
 * @brief 基準姿勢から今の姿勢までの回転を、表示ワールド系の回転ベクトル [度] で返す
 *
 * q は IMUManager::getQuaternion() の値。描画 (LEDManager::updateLEDBuffer) は LED の
 * 機体座標 p を rot(conj(q)) で表示ワールド系に移すので、相対回転は
 * rot(conj(now)) · rot(conj(base))⁻¹ = rot(conj(now) ⊗ base)。
 * 表示ワールド系は XYZ 軸表示の点と同じ座標系 (+Z = 青の明るい点)。
 * 戻り値の各成分は、その軸まわりの右ねじ (+側から見て反時計回り) の回転角。
 */
static inline void relativeRotationDeg(const Quat& base, const Quat& now, float out[3]) {
    Quat r = quatMul(quatConj(now), base);
    const float n = sqrtf(r.w * r.w + r.x * r.x + r.y * r.y + r.z * r.z);
    if (n < 1e-6f) { out[0] = out[1] = out[2] = 0.0f; return; }
    r = quatScaled(r, (r.w < 0.0f ? -1.0f : 1.0f) / n);   // 短い方の回転 (0..180°) にそろえる
    const float s = sqrtf(r.x * r.x + r.y * r.y + r.z * r.z);
    if (s < 1e-6f) { out[0] = out[1] = out[2] = 0.0f; return; }
    const float angleDeg = 2.0f * atan2f(s, r.w) * (180.0f / (float)M_PI);
    out[0] = r.x / s * angleDeg;
    out[1] = r.y / s * angleDeg;
    out[2] = r.z / s * angleDeg;
}

/// 画面 (LED) と効果音のための状態
enum class UiState : uint8_t {
    Normal,           ///< 通常の再生
    Menu,             ///< 回転メニュー (映像を暗く、±Z の点を表示)
    PowerOffPending,  ///< 電源 OFF の予告中 (明滅が速くなりながら暗くなる)
    PoweringOff,      ///< 電源 OFF を実行した (LED は消灯)
};

/// update() の結果 (呼び出し側が音・動作に変換する)
enum class Action : uint8_t {
    None,
    EnterMenu,       ///< メニューに入った
    MenuTimeout,     ///< 何も確定せずメニューを抜けた
    SelectStart,     ///< Z 軸の回転が 45° を超えた (1 秒保持で確定)
    ApToggle,        ///< Z− 確定: AP の ON/OFF 切替
    PowerOffArm,     ///< Z+ 確定: 電源 OFF の予告を開始
    PowerOffCancel,  ///< 予告中のシェイクで取り消し
    PowerOffNow,     ///< 予告が終わった: 電源を切る
};

struct Input {
    uint32_t nowMs = 0;
    ShakeDetector::Result shake;
    bool quatValid = false;
    Quat q;
};

class GestureFsm {
public:
    void begin(uint32_t nowMs) { _bootMs = nowMs; _state = UiState::Normal; _sinceMs = nowMs; }

    Action update(const Input& in) {
        const uint32_t now = in.nowMs;
        switch (_state) {
        case UiState::Normal:
            if (in.shake.triple && in.quatValid && now - _bootMs >= kBootGuardMs) {
                enter(UiState::Menu, now);
                _base = in.q;
                _holdSign = 0;
                return Action::EnterMenu;
            }
            return Action::None;

        case UiState::Menu: {
            if (now - _sinceMs >= kMenuTimeoutMs) {
                enter(UiState::Normal, now);
                return Action::MenuTimeout;
            }
            if (!in.quatValid) return Action::None;
            if (now - _sinceMs < kMenuSettleMs) {
                _base = in.q;   // 振っている最中の姿勢を基準にしない
                return Action::None;
            }
            float rv[3];
            relativeRotationDeg(_base, in.q, rv);
            const int8_t sign = zSelection(rv);
            if (sign == 0) {
                _holdSign = 0;   // 45° を下回ったら保持をやり直し
                return Action::None;
            }
            if (sign != _holdSign) {
                _holdSign = sign;
                _holdStartMs = now;
                return Action::SelectStart;
            }
            if (now - _holdStartMs < kSelectHoldMs) return Action::None;
            if (sign > 0) {
                enter(UiState::PowerOffPending, now);
                return Action::PowerOffArm;
            }
            enter(UiState::Normal, now);
            return Action::ApToggle;
        }

        case UiState::PowerOffPending:
            if (in.shake.shake) {
                enter(UiState::Normal, now);
                return Action::PowerOffCancel;
            }
            if (now - _sinceMs >= kPowerOffConfirmMs) {
                enter(UiState::PoweringOff, now);
                return Action::PowerOffNow;
            }
            return Action::None;

        case UiState::PoweringOff:
            return Action::None;   // 電源が落ちるまで何も受け付けない
        }
        return Action::None;
    }

    UiState state() const { return _state; }
    uint32_t stateSinceMs() const { return _sinceMs; }

    /// 電源 OFF に失敗した (USB 給電中など) ときに通常へ戻す。PoweringOff 以外では何もしない
    bool recoverFromFailedPowerOff(uint32_t nowMs) {
        if (_state != UiState::PoweringOff) return false;
        enter(UiState::Normal, nowMs);
        return true;
    }

    /// Z 軸が主な回転で 45° 以上なら ±1、それ以外 (X/Y が主、角度不足) は 0
    static int8_t zSelection(const float rv[3]) {
        const float az = fabsf(rv[2]);
        if (az < kSelectDeg) return 0;
        if (fabsf(rv[0]) >= az || fabsf(rv[1]) >= az) return 0;
        return rv[2] > 0.0f ? 1 : -1;
    }

private:
    void enter(UiState s, uint32_t now) { _state = s; _sinceMs = now; }

    UiState _state = UiState::Normal;
    uint32_t _sinceMs = 0;
    uint32_t _bootMs = 0;
    Quat _base;
    int8_t _holdSign = 0;
    uint32_t _holdStartMs = 0;
};

/**
 * @brief 電源 OFF 予告中の LED の倍率 (0..255)
 *
 * 明滅 (点灯 / 消灯 半々) の周波数を kBlinkStartHz → kBlinkEndHz へ直線で上げ、
 * 点灯側の明るさを 1.0 → kDimEnd へ直線で下げる。4 秒で 14 回点滅。
 */
static inline uint8_t powerOffScale(uint32_t elapsedMs) {
    if (elapsedMs >= kPowerOffConfirmMs) return 0;
    const float T = kPowerOffConfirmMs / 1000.0f;
    const float t = elapsedMs / 1000.0f;
    // 周波数を積分した位相 [周期]
    const float cycles = kBlinkStartHz * t + (kBlinkEndHz - kBlinkStartHz) * t * t / (2.0f * T);
    if (cycles - floorf(cycles) >= 0.5f) return 0;
    const float level = 1.0f - (1.0f - kDimEnd) * (t / T);
    return (uint8_t)(255.0f * level + 0.5f);
}

} // namespace gesture_logic
} // namespace sastle
