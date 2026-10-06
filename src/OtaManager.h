/**
 * @file OtaManager.h
 * @brief WiFi 経由 (espota / ArduinoOTA) のファームウェア無線更新
 * @author sastle-com
 *
 * ボール封止後など USB が届かない状態でも、AP (192.168.4.1) または STA (LAN / P2P 網) から
 *   pio run -e xiao_esp32s3_ota -t upload           (AP 経由)
 *   pio run -e xiao_esp32s3_lan_ota -t upload --upload-port <STA IP>
 * でファーム/LittleFS を無線更新できるようにする。
 * OTA セッション開始時にフレーム供給 (FramePump: ローカル再生 + UDP 受信) と LED
 * レンダリングタスクを協調停止し、転送完了まで handle() がブロックする。
 */

#ifndef __OTA_MANAGER_H__
#define __OTA_MANAGER_H__

#include <Arduino.h>

namespace sastle {

class LEDManager;   // 前方宣言
class SoloPlayer;
class FramePump;
class MQTTManager;

class OtaManager {
public:
    /**
     * @brief OTA を初期化する (WiFi 起動後に呼ぶ)
     * @param led    OTA 開始時にレンダリングタスクを止める (nullptr 可)
     * @param pump   OTA 開始時にフレーム供給タスクと UDP 受信を止める (nullptr 可)
     * @param player OTA 開始時に再生状態を Stopped にする (nullptr 可)
     * @param hostname mDNS / espota 上の識別名 (sphere id)
     * @param mqtt   OTA 開始時に offline を publish して切る (nullptr 可)
     * @return true 初期化成功
     */
    bool begin(LEDManager* led, FramePump* pump, SoloPlayer* player, const char* hostname,
               MQTTManager* mqtt = nullptr);

    /**
     * @brief OTA 要求を処理する (メインループから毎回呼ぶ)
     */
    void handle();

    bool isStarted() const { return _started; }

private:
    bool _started = false;
    SoloPlayer* _player = nullptr;
    FramePump* _pump = nullptr;
    LEDManager* _led = nullptr;
    MQTTManager* _mqtt = nullptr;
};

} // namespace sastle

#endif /* __OTA_MANAGER_H__ */
