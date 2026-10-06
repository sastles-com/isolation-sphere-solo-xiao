/**
 * @file NetworkManager.h
 * @brief Wi-Fi 役割 (AP / AP+STA) の管理クラス
 * @author sastle-com
 *
 * 基本は球体自身が SoftAP を立て、iPhone が直接そこへ繋いで Web UI を開く。AP は常に立てる。
 * 加えて任意で STA (AP+STA 同時) を有効にできる。STA の用途は 2 つ:
 *   - 開発時の OTA: 普段の LAN に居れば PC の Wi-Fi を切り替えずに espota できる
 *     (資格情報は NVS。config.json に書くとリポジトリに混入するため)
 *   - server モード: P2P 網 (config.json の wifi{}) に固定 IP で入り、MQTT/UDP を受ける
 * 資格情報の優先順は NVS > config.json wifi{} > なし。
 *
 * ESP32 は AP と STA で無線を共有するため、AP のチャンネルは STA 側に追従する。STA を先に
 * 始めて短く待ち、その後 AP を STA と同じチャンネルで立てる。
 */

#ifndef __NETWORK_MANAGER_H__
#define __NETWORK_MANAGER_H__

#include "common.h"
#include <Arduino.h>
#include <WiFi.h>
#include <functional>
#include "ConfigManager.h"

namespace sastle {

/// STA 接続の計画 (資格情報の出所と IP 設定)
struct StaPlan {
    enum class Origin : uint8_t { None, Nvs, Config };
    Origin origin = Origin::None;
    String ssid;
    String password;
    bool useStaticIp = false;
    IPAddress ip, gateway, subnet;

    bool valid() const { return origin != Origin::None && ssid.length() > 0; }
    const char* originName() const {
        return origin == Origin::Nvs ? "nvs" : origin == Origin::Config ? "config" : "none";
    }
};

class NetworkManager {
public:
    NetworkManager();
    virtual ~NetworkManager();

    /**
     * @brief 役割を決めて Wi-Fi を立ち上げる (STA 先行 → SoftAP)
     * @param config  solo.ap{} と wifi{} / spheres[] を参照
     * @return true SoftAP が起動した (STA の成否は問わない)
     */
    bool begin(ConfigManager& config);

    /**
     * @brief NVS > config の優先順で STA の計画を組む (静的 IP は解決済み sphere エントリから)
     */
    static StaPlan resolveStaPlan(ConfigManager& config);

    /**
     * @brief SoftAP を起動する
     * @param ssid     AP の SSID
     * @param password WPA2 パスフレーズ (8文字未満なら暗号化なしのオープンAPで起動)
     * @param ip       AP 自身の IP (= ゲートウェイ)。サブネットは /24 固定
     * @param channel  0 = 既定 (STA 接続中ならそのチャンネル)
     * @return true 起動成功
     */
    bool beginSoftAP(const String& ssid, const String& password, const IPAddress& ip, uint8_t channel = 0);

    /**
     * @brief STA 接続を開始する (非ブロッキング)。WiFi.mode は AP_STA であること。
     * @param plan     資格情報と IP 設定
     * @param hostname DHCP / mDNS 用のホスト名
     */
    bool beginSta(const StaPlan& plan, const String& hostname);

    /// STA の資格情報を NVS に保存する (空 SSID で無効化)。次回起動から反映。
    static bool saveStaCredentials(const String& ssid, const String& password);
    /// NVS に保存された STA の SSID (無ければ空文字)
    static String storedStaSsid();

    /// 接続状態の変化をログに出し、切断時はバックオフ付きで再接続する (loop から呼ぶ)
    void poll();

    /// STA 接続/切断のエッジ通知 (loop 文脈で呼ばれる)。UDP listen / MQTT 接続の起動に使う
    void onStaUp(std::function<void()> cb) { _onUp = cb; }
    void onStaDown(std::function<void()> cb) { _onDown = cb; }

    bool staEnabled() const { return _staEnabled; }
    bool staConnected() const { return _staEnabled && WiFi.status() == WL_CONNECTED; }
    IPAddress staIP() const { return WiFi.localIP(); }
    String staSsid() const { return _plan.ssid; }
    const StaPlan& staPlan() const { return _plan; }
    const char* staOriginName() const { return _plan.originName(); }

    /**
     * @brief SoftAP を停止する
     * @note 先に立てた AP の設定は覚えているので startAp() で再開できる。STA が無ければ
     *       無線ごと止まる (Wi-Fi 消費電力の主因が消える)。loopTask から呼ぶこと。
     */
    void stop();

    /// 停止中の SoftAP を、直前と同じ設定で再開する。起動済みなら何もしない。loopTask から呼ぶ
    bool startAp();

    /// SoftAP が現在立っているか (stop() 中は false)
    bool isSoftAP() const { return _started; }

    /// 無操作 (接続端末 0 台) がこの分数続いたら SoftAP を自動停止する。0 = 常時 ON
    void setApIdleTimeoutMin(uint16_t minutes);
    uint16_t apIdleTimeoutMin() const { return _apIdleTimeoutMin; }

    /// モデム省電力 (WIFI_PS_MIN_MODEM)。STA 接続中のビーコン間スリープ。既定 OFF (応答性優先)
    void setModemSleep(bool on);
    bool modemSleep() const { return _modemSleep; }

    /// AP 自身の IP アドレス
    IPAddress apIP() const { return WiFi.softAPIP(); }
    /// 接続中のクライアント台数
    uint8_t clientCount() const { return WiFi.softAPgetStationNum(); }

    void printStatus() const;

    /**
     * @brief Wi-Fi 接続用 QR コードの文字列を作る (iOS カメラ / Android 標準対応)
     * @param ssid     SSID
     * @param password パスフレーズ (8文字未満は beginSoftAP と同様にオープン扱い)
     * @return "WIFI:T:WPA;S:<ssid>;P:<pass>;;" または "WIFI:T:nopass;S:<ssid>;;"
     * @note 特殊文字 (\ ; , : ") はバックスラッシュでエスケープする。
     */
    static String wifiQrText(const String& ssid, const String& password);

private:
    void startStaAttempt();
    void applyPowerSave();      ///< _modemSleep を WiFi.setSleep() に反映する
    void pollApIdle();          ///< 無操作タイムアウトで SoftAP を止める

    bool _started;
    bool _modemSleep = false;
    // stop() 後の startAp() 用に、立てたときの SoftAP 設定を覚えておく
    String _apSsid;
    String _apPassword;
    IPAddress _apIp;
    uint8_t _apChannel = 1;
    uint16_t _apIdleTimeoutMin = 0;
    uint32_t _apIdleSinceMs = 0;   ///< 端末 0 台になった (または AP 起動した) 時刻
    bool _staEnabled = false;
    bool _staWasConnected = false;
    StaPlan _plan;
    std::function<void()> _onUp;
    std::function<void()> _onDown;

    // 再接続バックオフ。Arduino core の autoReconnect は「切断イベントごとに即 begin()」で、
    // 相手の AP が居ないと数秒ごとにスキャンが走り、同じ無線を使う SoftAP の応答が鈍る
    // (iPhone の Web UI がもたつく)。5s から倍々で最大 60s まで間隔を空ける。
    static constexpr uint32_t kBackoffMinMs = 5000;
    static constexpr uint32_t kBackoffMaxMs = 60000;
    static constexpr uint32_t kBootStaWaitMs = 2000;   ///< 起動時に STA を待つ上限 (AP チャンネル決定用)
    uint32_t _backoffMs = kBackoffMinMs;
    uint32_t _lastAttemptMs = 0;
};

}  // namespace sastle

#endif  // __NETWORK_MANAGER_H__
