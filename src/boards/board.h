#ifndef BOARD_H
#define BOARD_H

// ============================================================
//  ボード選択ディスパッチャ
//  platformio.ini の build_flags で、対象デバイスに応じて
//    -D BOARD_XIAO_ESP32S3    (XIAO ESP32S3)
//  を定義すること。
// ============================================================

#if defined(BOARD_XIAO_ESP32S3)
  #include "board_xiao_esp32s3.h"
#else
  #error "ボード未定義: build_flags に -D BOARD_XIAO_ESP32S3 を追加してください"
#endif

#include <stdint.h>

namespace sastle {

// --- ボード非依存の共通定数 ---
constexpr int      kWifiConnectRetries = 40;    // 40回 × 250ms = 最大10秒
constexpr uint32_t kWifiRetryDelayMs = 250;

} // namespace sastle

#endif /* BOARD_H */
