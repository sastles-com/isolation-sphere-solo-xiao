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

bool BatteryGauge::readRegs(uint8_t addr, uint8_t reg, uint8_t* out, size_t n) {
    if (n == 0 || n > 128) return false;
    auto rd = [&]() {
        Wire.beginTransmission(addr);
        Wire.write(reg);
        if (Wire.endTransmission(false) != 0) return false;
        if (Wire.requestFrom(addr, (uint8_t)n) != n) return false;
        for (size_t k = 0; k < n; k++) out[k] = Wire.read();
        return true;
    };
    if (_lock) { I2cGuard g(*_lock); return rd(); }
    return rd();
}

bool BatteryGauge::writeReg(uint8_t addr, uint8_t reg, uint8_t val) {
    auto wr = [&]() {
        Wire.beginTransmission(addr);
        Wire.write(reg);
        Wire.write(val);
        return Wire.endTransmission() == 0;
    };
    if (_lock) { I2cGuard g(*_lock); return wr(); }
    return wr();
}

int BatteryGauge::macRead(uint16_t subcmd, uint8_t* data) {
    constexpr uint8_t kCmdMacSubcmd = 0x3E;   // 0x3E/3F = サブコマンド、0x40〜0x5F = データ、0x60 = チェックサム、0x61 = 長さ
    const uint8_t cmd[2] = {static_cast<uint8_t>(subcmd & 0xFF), static_cast<uint8_t>(subcmd >> 8)};
    auto wr = [&]() {
        Wire.beginTransmission(kGaugeAddr);
        Wire.write(kCmdMacSubcmd);
        Wire.write(cmd, 2);
        return Wire.endTransmission() == 0;
    };
    bool ok;
    if (_lock) { I2cGuard g(*_lock); ok = wr(); } else { ok = wr(); }
    if (!ok) return -1;
    delay(5);   // ロックを離して待つ (IMU を止めない)
    uint8_t blk[36];   // サブコマンド 2 + データ 32 + チェックサム 1 + 長さ 1
    if (!readRegs(kGaugeAddr, kCmdMacSubcmd, blk, sizeof(blk))) return -1;
    if (blk[0] != cmd[0] || blk[1] != cmd[1]) return -1;
    const int len = blk[35] - 4;   // 長さにはサブコマンド・チェックサム・長さの 4 バイトが含まれる
    if (len < 1 || len > 32) return -1;
    uint8_t sum = 0;
    for (int i = 0; i < len + 2; ++i) sum += blk[i];
    if (static_cast<uint8_t>(~sum) != blk[34]) return -1;
    memcpy(data, blk + 2, len);
    return len;
}

bool BatteryGauge::dfWrite(uint16_t addr, const uint8_t* data, size_t len) {
    if (len < 1 || len > 32) return false;
    uint8_t blk[34];
    blk[0] = static_cast<uint8_t>(addr & 0xFF);
    blk[1] = static_cast<uint8_t>(addr >> 8);
    memcpy(blk + 2, data, len);
    uint8_t sum = 0;
    for (size_t i = 0; i < len + 2; i++) sum += blk[i];
    const uint8_t tail[2] = {static_cast<uint8_t>(~sum), static_cast<uint8_t>(len + 4)};
    auto wr = [&]() {
        Wire.beginTransmission(kGaugeAddr);
        Wire.write(0x3E);
        Wire.write(blk, len + 2);
        if (Wire.endTransmission() != 0) return false;
        Wire.beginTransmission(kGaugeAddr);
        Wire.write(0x60);
        Wire.write(tail, 2);
        return Wire.endTransmission() == 0;
    };
    if (_lock) { I2cGuard g(*_lock); return wr(); }
    return wr();
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
