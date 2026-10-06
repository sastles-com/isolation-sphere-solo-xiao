#ifndef __BOARD_CONFIG_H__
#define __BOARD_CONFIG_H__

// ============================================================
//  ハードウェア構成 (Seeed Studio XIAO ESP32S3 + コア基板)
//  ピン・有無などの物理ハード設定をここに集約する。
//  変更時は配線図 (FPC-isolation-sphere/kiban/core-XIAO-*) と照合すること。
//
//  XIAO シルク↔実GPIO: D0=1 D1=2 D2=3 D3=4 D4=5(SDA) D5=6(SCL)
//                      D6=43(TX) D7=44(RX) D8=7 D9=8 D10=9
//  (GPIO19/20 は USB D-/D+ のため使わない)
//  注意:
//   - D6 (GPIO43) は UART0 TX。起動時に ROM のブートログが出るので WS2812 には使わない。
//   - D2 (GPIO3) はストラップピン (JTAG 選択)。ストリップのデータ線にするときは起動時の挙動を確認する。
//   - ディープスリープ復帰に使う入力は RTC 対応ピン (D0〜D5, D8〜D10) に置く。
// ============================================================

#include <stdint.h>

#define BOARD_NAME "XIAO-ESP32S3"

namespace sastle {

// --- LED (WS2812) ---
// FastLED の addLeds<> はピンがテンプレート引数のため、コンパイル時定数で持つ
// (config.json には出せない)。LEDManager は kLedPins[] を添字 0..kNumStrips-1 で展開して登録する。
// core-XIAO-03: J4 = D0〜D3 + 8 番パッド。回路図のネット名は "GPIO09" だが、XIAO の 8 番パッドは
// D7 = GPIO44。基板の再設計まで暫定で GPIO44 とする (2026-10-06)。
constexpr uint8_t  kNumStrips = 5;
constexpr uint8_t  kLedPins[kNumStrips] = {1, 2, 3, 4, 44};
constexpr uint16_t kLedsPerStrip = 160;                       // 北 80 + 南 80
constexpr uint16_t kMaxLeds = kNumStrips * kLedsPerStrip;     // 800
constexpr uint8_t  kLedDefaultBrightness = 128;               // デフォルト輝度 50%
// 電源保護: FastLED のパワーリミット (5V 系の合計電流上限)。全LED白点灯のような高負荷フレームでも
// FastLED が輝度を自動スケールしてこの上限内に収める。実測で電源容量が確定したら見直すこと。
constexpr uint32_t kLedMaxPowerMa = 2000;

// --- IMU (BNO055) I2C ---
constexpr uint8_t kImuI2cSda = 5;  // D4
constexpr uint8_t kImuI2cScl = 6;  // D5

// --- ブザー (core-XIAO-03 の LS1) ---
// GPIO43 は TX なので、起動直後にブートログで小さなノイズが出ることがある。
constexpr uint8_t kBuzzerGpio = 43;  // D6

} // namespace sastle

#endif /* __BOARD_CONFIG_H__ */
