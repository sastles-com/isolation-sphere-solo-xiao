/**
 * @file BatteryGuard.h
 * @brief 電池の低電圧で予告し、放電終止で電源を切る判定 (純粋、Arduino 非依存)
 *
 * 残量計 BQ28Z620 の Voltage() (セル合計) を見る。残量 (%) は使わない
 * (2026-11-23 時点で残量計の GAUGE_EN が無効のままで、放電しても 100% から減らない)。
 *   - kWarnMv を kHoldMs 続けて下回ったら予告 (Warn) を 1 回出す。kWarnMv + kRearmMv まで戻ったら再び出せる。
 *   - kOffMv を kHoldMs 続けて下回ったら電源 OFF (PowerOff) を 1 回だけ出す (以後は出さない)。
 * 負荷の瞬間的な電圧降下 (オープニング、明るいフレーム) で切らないよう、続けて下回ったときだけ数える。
 * 充電中 (電流が +kChargingMa 以上) は数えない。読み出しが古い・失敗したサンプルは無視する (判定を進めも戻しもしない)。
 * 放電終止 6.4 V (1 セル 3.2 V) は設計値 (kiban/EasyEDA/docs/hardware_spec.md: XH コネクタの電流定格)。
 *
 * native テスト: test/test_battery_guard
 */
#pragma once
#include <stdint.h>

namespace sastle {
namespace battery_guard {

constexpr uint16_t kWarnMv     = 6600;   ///< 予告 (1 セル 3.3 V)
constexpr uint16_t kOffMv      = 6400;   ///< 放電終止 (1 セル 3.2 V)
constexpr uint16_t kRearmMv    = 200;    ///< 予告の解除幅 (kWarnMv + これ以上に戻ったら再び予告できる)
constexpr uint32_t kHoldMs     = 30000;  ///< この時間続けて下回ったら確定 (残量計は 5 秒ごとに読む)
constexpr int16_t  kChargingMa = 50;     ///< これ以上の充電電流なら充電中とみなし、数えない
constexpr uint32_t kMaxAgeMs   = 15000;  ///< これより古い読み出しは使わない

enum class Event : uint8_t { None, Warn, PowerOff };
enum class Level : uint8_t { Ok, Low, Empty };

inline const char* levelName(Level l) {
    return l == Level::Empty ? "empty" : l == Level::Low ? "low" : "ok";
}

class Guard {
public:
    /**
     * @param valid  残量計が応答し、読み出しが kMaxAgeMs より新しい
     * @param mv     Voltage() [mV]
     * @param ma     Current() [mA] (+ 充電 / − 放電)
     * @param nowMs  millis()
     */
    Event update(bool valid, uint16_t mv, int16_t ma, uint32_t nowMs) {
        if (!valid || _level == Level::Empty) return Event::None;
        if (ma >= kChargingMa) {           // 充電中: 数え直し
            _belowWarnSince = _belowOffSince = 0;
            _hasWarnSince = _hasOffSince = false;
            if (mv >= kWarnMv + kRearmMv) { _warned = false; _level = Level::Ok; }
            return Event::None;
        }
        if (mv < kOffMv) {
            if (!_hasOffSince) { _belowOffSince = nowMs; _hasOffSince = true; }
            if ((uint32_t)(nowMs - _belowOffSince) >= kHoldMs) {
                _level = Level::Empty;
                return Event::PowerOff;
            }
        } else {
            _hasOffSince = false;
        }
        if (mv < kWarnMv) {
            if (!_hasWarnSince) { _belowWarnSince = nowMs; _hasWarnSince = true; }
            if (!_warned && (uint32_t)(nowMs - _belowWarnSince) >= kHoldMs) {
                _warned = true;
                _level = Level::Low;
                return Event::Warn;
            }
        } else {
            _hasWarnSince = false;
            if (mv >= kWarnMv + kRearmMv) { _warned = false; _level = Level::Ok; }
        }
        return Event::None;
    }

    Level level() const { return _level; }

private:
    Level _level = Level::Ok;
    bool _warned = false;
    bool _hasWarnSince = false;
    bool _hasOffSince = false;
    uint32_t _belowWarnSince = 0;
    uint32_t _belowOffSince = 0;
};

}  // namespace battery_guard
}  // namespace sastle
