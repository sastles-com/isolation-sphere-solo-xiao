/**
 * @file BatteryGauge.h
 * @brief 基板B の残量計 BQ28Z620 (I2C 0x55) を定期的に読む (読むだけ。設定は変えない)
 *
 * BNO055 と同じ I2C バス (SDA=GPIO9 / SCL=GPIO8) にいるので、IMU タスクの読み出しに
 * 割り込まないよう IMUManager の I2cLock を取ってから読む。
 * loop() から poll() を呼ぶ。読み出しは 5 秒ごと、応答が無いときは 30 秒ごとに再試行。
 * 値の意味と読み方は tools/boardB_gauge_check/src/main.cpp と同じ (TI SLUUCO9B)。
 */
#pragma once

#include <Arduino.h>

#include "imu/I2cLock.h"

namespace sastle {

class BatteryGauge {
public:
    struct Reading {
        bool present = false;     ///< 直近の読み出しで応答があった
        uint32_t ageMs = 0;       ///< 直近の読み出しからの経過 [ms]
        uint16_t voltageMv = 0;   ///< Voltage() セル合計 [mV]
        int16_t currentMa = 0;    ///< Current() [mA] (+ 充電 / - 放電)
        uint8_t socPct = 0;       ///< RelativeStateOfCharge() [%]
        uint16_t remainingMah = 0;
        uint16_t fullMah = 0;
        float temperatureC = 0;
        uint16_t status = 0;      ///< BatteryStatus()
        uint8_t lastError = 0;    ///< 直近の失敗: Wire.endTransmission の値 (2=アドレス NACK, 3=データ NACK,
                                  ///< 4=その他, 5=タイムアウト)、10=アドレスは応答したが読み出しが失敗。0=失敗なし
        uint32_t okCount = 0;     ///< 読み出し (5 秒ごと) の成功回数
        uint32_t failCount = 0;   ///< 失敗回数
    };

    /// lock = IMU と共有する I2C ロック (IMU 未検出なら nullptr。Wire は scanI2cBus で開始済み)
    void begin(I2cLock* lock);
    void poll();
    Reading reading() const;
    /// /api/status 用の JSON オブジェクト (例 {"present":true,"mv":7600,...})
    int toJson(char* buf, size_t cap) const;
    void print() const;

    /// I2C の全アドレス (0x08〜0x77) を調べ、応答したアドレスを "0x28 0x55" の形で buf に書く。
    /// 診断用。IMU と同じロックを取る。戻り値 = 見つかった数
    int scanBus(char* buf, size_t cap);

private:
    bool readWord(uint8_t reg, uint16_t& out, uint8_t& err);
    void readAll();

    I2cLock* _lock = nullptr;
    Reading _r;
    uint32_t _lastReadMs = 0;
    uint32_t _nextMs = 0;
    uint8_t _lastError = 0;
    uint32_t _okCount = 0;
    uint32_t _failCount = 0;
    mutable portMUX_TYPE _mux = portMUX_INITIALIZER_UNLOCKED;   ///< httpd タスクからの読み出しと排他
};

}  // namespace sastle
