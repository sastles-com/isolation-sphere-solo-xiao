#include "BatteryGauge.h"

#include <Wire.h>

namespace sastle {

namespace {
constexpr uint8_t kGaugeAddr = 0x55;
// BQ28Z620 の標準コマンド (2 バイト、リトルエンディアン)
constexpr uint8_t kCmdTemperature = 0x06;   // 0.1 K
constexpr uint8_t kCmdVoltage = 0x08;       // mV
constexpr uint8_t kCmdBatteryStatus = 0x0A;
constexpr uint8_t kCmdCurrent = 0x0C;       // mA (符号付き)
constexpr uint8_t kCmdRemaining = 0x10;     // mAh
constexpr uint8_t kCmdFullCharge = 0x12;    // mAh
constexpr uint8_t kCmdRsoc = 0x2C;          // %
constexpr uint32_t kPollMs = 5000;
constexpr uint32_t kRetryMs = 30000;        // 応答が無いとき (基板B 未接続など)
}  // namespace

void BatteryGauge::begin(I2cLock* lock) {
    _lock = lock;
    _nextMs = 0;   // 最初の poll() ですぐ読む
}

bool BatteryGauge::readWord(uint8_t reg, uint16_t& out, uint8_t& err) {
    Wire.beginTransmission(kGaugeAddr);
    Wire.write(reg);
    // Arduino-ESP32 2.x の endTransmission(false) は送らずに 0 を返し、実際の転送は requestFrom で行う。
    // 失敗したらアドレスだけを送り直して、応答なし (2) か、それ以外 (途中で失敗 = 10) かを分ける。
    const uint8_t e = Wire.endTransmission(false);
    if (e != 0) { err = e; return false; }
    if (Wire.requestFrom(kGaugeAddr, (uint8_t)2) != 2) {
        Wire.beginTransmission(kGaugeAddr);
        const uint8_t p = Wire.endTransmission();
        err = p ? p : 10;
        return false;
    }
    const uint8_t lo = Wire.read();
    const uint8_t hi = Wire.read();
    out = (uint16_t)(lo | (hi << 8));
    return true;
}

void BatteryGauge::readAll() {
    Reading r;
    uint16_t v = 0, i = 0, soc = 0, rem = 0, full = 0, t = 0, st = 0;
    bool ok;
    uint8_t err = 0;
    {
        // 1 ワードずつロックを取り直し、IMU の 100 Hz 読み出しを長く止めない
        auto rd = [&](uint8_t reg, uint16_t& out) {
            if (_lock) { I2cGuard g(*_lock); return readWord(reg, out, err); }
            return readWord(reg, out, err);
        };
        ok = rd(kCmdVoltage, v);
        if (ok) {
            rd(kCmdCurrent, i);
            rd(kCmdRsoc, soc);
            rd(kCmdRemaining, rem);
            rd(kCmdFullCharge, full);
            rd(kCmdTemperature, t);
            rd(kCmdBatteryStatus, st);
        }
    }
    r.present = ok;
    if (ok) { _okCount++; } else { _failCount++; _lastError = err; }
    r.lastError = _lastError;
    r.okCount = _okCount;
    r.failCount = _failCount;
    if (ok) {
        r.voltageMv = v;
        r.currentMa = (int16_t)i;
        r.socPct = soc > 100 ? 100 : (uint8_t)soc;
        r.remainingMah = rem;
        r.fullMah = full;
        r.temperatureC = t / 10.0f - 273.15f;
        r.status = st;
    }
    portENTER_CRITICAL(&_mux);
    _r = r;
    _lastReadMs = millis();
    portEXIT_CRITICAL(&_mux);
}

void BatteryGauge::poll() {
    const uint32_t now = millis();
    if ((int32_t)(now - _nextMs) < 0) return;
    readAll();
    _nextMs = now + (_r.present ? kPollMs : kRetryMs);
}

BatteryGauge::Reading BatteryGauge::reading() const {
    portENTER_CRITICAL(&_mux);
    Reading r = _r;
    const uint32_t last = _lastReadMs;
    portEXIT_CRITICAL(&_mux);
    r.ageMs = last ? millis() - last : 0;
    return r;
}

int BatteryGauge::toJson(char* buf, size_t cap) const {
    const Reading r = reading();
    if (!r.present) {
        return snprintf(buf, cap, "{\"present\":false,\"err\":%u,\"ok_n\":%lu,\"fail_n\":%lu,\"age_ms\":%lu}",
                        (unsigned)r.lastError, (unsigned long)r.okCount, (unsigned long)r.failCount,
                        (unsigned long)r.ageMs);
    }
    return snprintf(buf, cap,
                    "{\"present\":true,\"mv\":%u,\"ma\":%d,\"soc\":%u,\"rem_mah\":%u,\"full_mah\":%u,"
                    "\"temp_c\":%.1f,\"status\":%u,\"age_ms\":%lu,\"err\":%u,\"ok_n\":%lu,\"fail_n\":%lu}",
                    (unsigned)r.voltageMv, (int)r.currentMa, (unsigned)r.socPct, (unsigned)r.remainingMah,
                    (unsigned)r.fullMah, r.temperatureC, (unsigned)r.status, (unsigned long)r.ageMs,
                    (unsigned)r.lastError, (unsigned long)r.okCount, (unsigned long)r.failCount);
}

int BatteryGauge::scanBus(char* buf, size_t cap) {
    int found = 0;
    size_t n = 0;
    if (cap) buf[0] = '\0';
    for (uint8_t a = 0x08; a <= 0x77; a++) {
        uint8_t e;
        if (_lock) {
            I2cGuard g(*_lock);   // 1 アドレスずつ取り直す (IMU を長く止めない)
            Wire.beginTransmission(a);
            e = Wire.endTransmission();
        } else {
            Wire.beginTransmission(a);
            e = Wire.endTransmission();
        }
        if (e == 0) {
            found++;
            if (n + 6 < cap) n += snprintf(buf + n, cap - n, "%s0x%02X", found > 1 ? " " : "", a);
        }
    }
    return found;
}

void BatteryGauge::print() const {
    const Reading r = reading();
    if (!r.present) {
        Serial.println("[BAT] BQ28Z620 (0x55): 応答なし");
        return;
    }
    Serial.printf("[BAT] %u%%  %u mV  %d mA  %u/%u mAh  %.1f C  status=0x%04X (%lu ms 前)\n",
                  (unsigned)r.socPct, (unsigned)r.voltageMv, (int)r.currentMa, (unsigned)r.remainingMah,
                  (unsigned)r.fullMah, r.temperatureC, (unsigned)r.status, (unsigned long)r.ageMs);
}

}  // namespace sastle
