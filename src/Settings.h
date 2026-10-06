/**
 * @file Settings.h
 * @brief 利用者が UI で変えた設定の永続化 (NVS)
 *
 * config.json は「出荷時の既定値」、NVS は「利用者が変えた値」という役割分担。
 * 起動時は NVS があればそれを、無ければ config.json を使う。
 *
 * スライダー操作は毎フレーム値が飛んでくるため、変更のたびに書くとフラッシュを
 * 無駄に消耗する。setBrightness() は RAM を更新して「保留」にするだけで、
 * tick() が最後の変更から kSaveDelayMs 経ってから 1 回書く。再起動要求の前には
 * flush() で確定させる。
 */

#ifndef __SETTINGS_H__
#define __SETTINGS_H__

#include <stdint.h>

namespace sastle {

class Settings {
public:
    /// NVS を開く (失敗しても以降の呼び出しは安全に無効化される)
    static void begin();

    /// 保存済みの明るさ (%) を返す。無ければ fallback をそのまま返す
    static uint8_t brightness(uint8_t fallback);

    /// 明るさを更新し、遅延保存を予約する
    static void setBrightness(uint8_t percent);

    /// 保存済みの XYZ 軸インジケータ表示 (無ければ fallback)
    static bool axisIndicator(bool fallback);

    /// XYZ 軸インジケータの表示状態を更新し、遅延保存を予約する
    static void setAxisIndicator(bool enabled);

    /// 保存済みの IMU 平滑フレーム数 (無ければ fallback)
    static uint8_t imuSmoothFrames(uint8_t fallback);
    static void setImuSmoothFrames(uint8_t n);

    /// 省電力設定。AP 無操作自動停止 (分、0=常時ON) / モデム省電力
    static uint16_t apIdleMinutes(uint16_t fallback);
    static void setApIdleMinutes(uint16_t minutes);
    static bool modemSleep(bool fallback);
    static void setModemSleep(bool on);

    /// 保留中の変更があれば書き込む (loop から呼ぶ)
    static void tick();

    /// 保留中の変更を即座に書き込む (再起動前)
    static void flush();

private:
    static constexpr uint32_t kSaveDelayMs = 3000;  ///< 最後の変更からこの時間だけ待つ
};

}  // namespace sastle

#endif  // __SETTINGS_H__
