#ifndef BOARD_XIAO_ESP32S3_H
#define BOARD_XIAO_ESP32S3_H

// ============================================================
//  Seeed Studio XIAO ESP32S3 ボード定義
//  デバイス個別の物理ハード設定 (ピン・有無) をここに集約する。
//
//  XIAO シルク↔実GPIO: D0=1 D1=2 D2=3 D3=4 D4=5(SDA) D5=6(SCL)
//                      D6=43 D7=44 D8=7 D9=8 D10=9
//  (GPIO19/20 は USB D-/D+ のため LED/I2C には使わない)
//  構成: 4ストリップ (D0-D3) + IMU I2C (D4/D5)。LCD/ブザーなし。
// ============================================================

#include <stdint.h>

// --- ボード機能フラグ ---
#define BOARD_NAME       "XIAO-ESP32S3"
#define BOARD_HAS_LCD    0   // 内蔵LCDなし
#define BOARD_HAS_BUZZER 0   // 内蔵スピーカーなし

// --- ストリップ本数 (XIAO: 4ストリップ) ---
#ifndef BOARD_NUM_STRIPS
#define BOARD_NUM_STRIPS 4
#endif

namespace sastle {

// --- LED (D0-D3 の4本) ---
constexpr uint8_t  kLedPin0 = 1;   // D0 -> GPIO 1
constexpr uint8_t  kLedPin1 = 2;   // D1 -> GPIO 2
constexpr uint8_t  kLedPin2 = 3;   // D2 -> GPIO 3
constexpr uint8_t  kLedPin3 = 4;   // D3 -> GPIO 4
constexpr uint8_t  kNumStrips = BOARD_NUM_STRIPS;
constexpr uint16_t kMaxLeds = 800;
constexpr uint8_t  kTargetFps = 30;
constexpr uint32_t kFrameDelayMs = 1000 / kTargetFps;
constexpr uint8_t  kLedDefaultBrightness = 128;  // デフォルト輝度 50%
// FastLED の電流リミッタ設定値。5V/2A 給電を前提にする。
constexpr uint32_t kLedMaxPowerMa = 2000;

// --- IMU (BNO055) I2C ---
constexpr uint8_t kImuI2cSda = 5;  // D4 -> GPIO 5
constexpr uint8_t kImuI2cScl = 6;  // D5 -> GPIO 6

// --- ブザー (未搭載: BOARD_HAS_BUZZER=0 のため値は未使用) ---
constexpr uint8_t kBuzzerGpio = 0xFF;

} // namespace sastle

#endif /* BOARD_XIAO_ESP32S3_H */
