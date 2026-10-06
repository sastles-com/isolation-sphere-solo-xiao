/**
 * @file SoloWebServer.h
 * @brief soloモード用のデバイス内 HTTP サーバー (最小Web UI + 制御API + 動画アップロード)
 *
 * ESP-IDF 同梱の esp_http_server を使う (追加ライブラリ依存なし)。UI の HTML/JS は
 * ファームウェアに埋め込み、CDN や外部フォントには依存しない。LittleFS が壊れて
 * いても管理 UI を出せるようにするため、UI を LittleFS には置かない。
 *
 * API (すべて JSON 応答):
 *   GET  /                    Web UI
 *   GET  /api/status          状態・統計・容量
 *   POST /api/play            再生
 *   POST /api/stop            停止
 *   POST /api/brightness      {"value":0-100}
 *   POST /api/video           動画本体 (application/octet-stream, raw MJPEG)
 *   POST /api/video/delete    保存済み動画の削除
 *   POST /api/reboot          再起動
 */

#ifndef __SOLO_WEB_SERVER_H__
#define __SOLO_WEB_SERVER_H__

#include <Arduino.h>
#include <DNSServer.h>
#include <WiFi.h>
#include <esp_http_server.h>

#include "ConfigManager.h"
#include "DeviceController.h"
#include "LEDManager.h"
#include "IMUManager.h"
#include "NetworkManager.h"
#include "SoloPlayer.h"
#include "UdpReceiver.h"

namespace sastle {

class SoloWebServer {
public:
    SoloWebServer();
    ~SoloWebServer();

    /**
     * @brief HTTP サーバーを起動する
     * @param ctl     操作の窓口 (再生/明るさ/LED/IMU/再起動は全てここへ委譲する)
     * @param config  設定 (captive_portal / sphere id)
     * @param player  再生統計の読み出し
     * @param led     LED 統計の読み出し
     * @param port    リッスンポート
     */
    bool begin(DeviceController& ctl, ConfigManager& config, SoloPlayer& player, LEDManager& led,
               NetworkManager& net, IMUManager& imu, uint16_t port, UdpReceiver* udp = nullptr);
    void end();
    bool isRunning() const { return _server != nullptr; }

    /**
     * @brief loop() から呼ぶ。キャプティブ DNS の応答 (再起動・設定保存は DeviceController::tick)。
     */
    void loop();

private:
    // esp_http_server ハンドラ (user_ctx = this)
    static esp_err_t onRoot(httpd_req_t* req);
    static esp_err_t onConvert(httpd_req_t* req);
    static esp_err_t onStatus(httpd_req_t* req);
    static esp_err_t onPlay(httpd_req_t* req);
    static esp_err_t onStop(httpd_req_t* req);
    static esp_err_t onPause(httpd_req_t* req);
    static esp_err_t onWifi(httpd_req_t* req);
    static esp_err_t onLed(httpd_req_t* req);
    static esp_err_t onImuGet(httpd_req_t* req);
    static esp_err_t onImuPost(httpd_req_t* req);
    static esp_err_t onServer(httpd_req_t* req);
    static esp_err_t onPower(httpd_req_t* req);
    static esp_err_t onSource(httpd_req_t* req);

    static esp_err_t onBrightness(httpd_req_t* req);
    static esp_err_t onUpload(httpd_req_t* req);
    static esp_err_t onDelete(httpd_req_t* req);
    static esp_err_t onReboot(httpd_req_t* req);
    static esp_err_t onNotFound(httpd_req_t* req, httpd_err_code_t err);

    esp_err_t doUpload(httpd_req_t* req);
    esp_err_t sendJson(httpd_req_t* req, const char* status, const char* json);
    esp_err_t sendError(httpd_req_t* req, const char* status, const char* message);
    bool readBody(httpd_req_t* req, char* out, size_t cap, size_t& len);
    /// 空き容量からアップロード上限を出す (キャッシュ済みの使用量と player の動画サイズから。フラッシュは読まない)
    size_t maxUploadBytes(size_t& freeOut, size_t& existingOut) const;
    /// LittleFS の使用量を再計算してキャッシュする (起動時・アップロード/削除の前後のみ。全ブロック走査 = フラッシュ読み)
    void refreshFsUsage();

    httpd_handle_t _server;
    // キャプティブポータル: 全ドメインを AP 自身の IP に解決し、未知パスは "/" へ 302。
    // iPhone は AP 接続直後に captive.apple.com を叩くので、そのまま UI が自動で開く。
    DNSServer _dns;
    bool _dnsStarted = false;
    DeviceController* _ctl;
    ConfigManager* _config;
    SoloPlayer* _player;
    LEDManager* _led;
    NetworkManager* _net;
    IMUManager* _imu;
    UdpReceiver* _udp = nullptr;   ///< 統計表示用 (nullptr 可)

    // LittleFS の使用量キャッシュ。usedBytes() は全ブロックを走査してフラッシュを読み、その間
    // 両コアのキャッシュが止まる。/api/status (Web UI が 2 秒ごと) から呼ぶと再生がカクつく
    // (実機 2026-09-23: 0.5s 間隔のポーリングで締切落ち 37%) ので、状態表示はこの値を使う。
    size_t _fsTotal = 0;
    size_t _fsUsed = 0;
    uint8_t* _rxBuf;              ///< 受信作業バッファ (ヒープ)
    char _jsonBuf[2048];          ///< 応答組み立て (ハンドラは httpd タスクで直列実行)
    uint32_t _uploads;
    uint32_t _uploadFailures;
};

}  // namespace sastle

#endif  // __SOLO_WEB_SERVER_H__
