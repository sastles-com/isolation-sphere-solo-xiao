#ifndef __BOARD_CONFIG_H__
#define __BOARD_CONFIG_H__

// ============================================================
//  ハードウェア構成 (Seeed Studio XIAO ESP32S3 + コア基板)
//  ピン・有無などの物理ハード設定をここに集約する。
//  変更時は回路図 (kiban/core-XIAO-04) と docs/xiao_bringup.md のピン表と照合すること。
//
//  XIAO シルク↔実GPIO: D0=1 D1=2 D2=3 D3=4 D4=5 D5=6
//                      D6=43(TX) D7=44(RX) D8=7 D9=8(SCL) D10=9(SDA)
//  (GPIO19/20 は USB D-/D+ のため使わない)
//  注意:
//   - D6 (GPIO43) は UART0 TX。起動時に ROM のブートログが出るので WS2812 には使わない (ブザー)。
//   - D2 (GPIO3) はストラップピン (JTAG 選択)。ストリップのデータ線にするときは起動時の挙動を確認する。
//   - D8 (GPIO7) = PWR_KILL は起動中に Low にしない (基板A で 100 kΩ プルアップ)。
//   - ディープスリープ復帰に使う入力は RTC 対応ピン (D0〜D5, D8〜D10) に置く。
// ============================================================

#include <stdint.h>

#define BOARD_NAME "XIAO-ESP32S3"

namespace sastle {

// --- LED (WS2812) ---
// FastLED の addLeds<> はピンがテンプレート引数のため、コンパイル時定数で持つ
// (config.json には出せない)。LEDManager は kLedPins[] を添字 0..kNumStrips-1 で展開して登録する。
// core-XIAO-04: D0〜D4 = ストリップ 1〜5 (33 Ω 経由で mother-ring の LINE01〜05 へ)。
// D5 (GPIO6) の北極 LED (ストリップ 6, 1 個) は未対応 (RMT 4ch の時分割が必要)。
constexpr uint8_t  kNumStrips = 5;
constexpr uint8_t  kLedPins[kNumStrips] = {1, 2, 3, 4, 5};
constexpr uint16_t kLedsPerStrip = 160;                       // 北 80 + 南 80
constexpr uint16_t kMaxLeds = kNumStrips * kLedsPerStrip;     // 800
constexpr uint8_t  kLedDefaultBrightness = 128;               // デフォルト輝度 50%
// 電源保護: FastLED のパワーリミット (5V 系の合計電流上限)。全LED白点灯のような高負荷フレームでも
// FastLED が輝度を自動スケールしてこの上限内に収める。実測で電源容量が確定したら見直すこと。
constexpr uint32_t kLedMaxPowerMa = 2000;

// --- LED 電源 / 電源制御 (core-XIAO-04) ---
// LED_EN (D7 = GPIO44): ストリップ 1〜5 の電源。基板A のプルダウンで既定 OFF。
// 起動中は入力のままにし、HIGH にしてから 5 ms 以上待ってデータを送る (FW-2)。
constexpr uint8_t kLedEnGpio = 44;
// PWR_KILL (D8 = GPIO7): Low で電源 OFF。起動中は触らない (FW-1)。現状ファームは未使用。
constexpr uint8_t kPwrKillGpio = 7;

// --- IMU (BNO055) I2C --- (D9 = SCL, D10 = SDA。XIAO 標準の D4/D5 ではない)
constexpr uint8_t kImuI2cSda = 9;  // D10
constexpr uint8_t kImuI2cScl = 8;  // D9

// --- ブザー (core-XIAO-04) ---
// GPIO43 は TX なので、起動直後にブートログで小さなノイズが出ることがある。
constexpr uint8_t kBuzzerGpio = 43;  // D6

} // namespace sastle

#endif /* __BOARD_CONFIG_H__ */
