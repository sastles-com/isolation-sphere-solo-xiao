/**
 * @file ConfigManager.h
 * @brief JSON設定ファイル管理クラス
 * @author sastle-com
 * @date 2025-12-01
 *
 * 統合ファーム (solo + server) の設定は 1 つの config.json の和集合:
 *   - solo{}     SoftAP / Web UI / 動画ファイル (solo 固有)
 *   - wifi{}     STA (P2P 網) と MQTT/UDP の宛先 (server 固有。派生元と同じ鍵名。
 *                Python サーバが同じファイルから udp_port / static_ip を読むため綴りを変えない)
 *   - source{}   フレーム供給元の調停 (auto / local / network)
 *   - spheres[]  MAC → 自機エントリの解決 (派生元と同じ)。旧形式の単一 sphere{} も受理
 */

#ifndef __CONFIG_MANAGER_H__
#define __CONFIG_MANAGER_H__

#include "common.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include "FileManager.h"

namespace sastle {

/**
 * @struct SystemConfig
 * @brief システム基本設定
 */
struct SystemConfig {
    bool debug;          ///< デバッグモード有効化
    bool PSRAM;          ///< PSRAM使用フラグ
};

/**
 * @struct OTAConfig
 * @brief OTA (Over-The-Air) アップデート設定
 */
struct OTAConfig {
    bool enabled;        ///< OTA有効化
    String username;     ///< OTA認証ユーザー名
    String password;     ///< OTA認証パスワード
    int listen_port;     ///< OTAリッスンポート
};

/**
 * @struct PathsConfig
 * @brief ファイルシステムパス設定
 */
struct PathsConfig {
    String config;       ///< 設定ファイルパス
    String layout;       ///< LEDレイアウトファイルパス
    String logs;         ///< ログディレクトリパス
};

/**
 * @struct SoloConfig
 * @brief solo 動作設定 (SoftAP / Web UI / 動画ファイル)
 */
struct SoloConfig {
    String video_path;   ///< 再生する raw MJPEG のパス
    uint16_t http_port;  ///< Web UI のポート
    String ap_ssid;      ///< SoftAP の SSID
    String ap_password;  ///< SoftAP のパスフレーズ (8文字未満はオープンAP)
    String ap_ip;        ///< SoftAP 自身の IP
};

/**
 * @struct WiFiConfig
 * @brief STA (P2P 網) と server の宛先。派生元 core と同じ鍵名。
 *
 * mode: "auto" (既定。STA 資格情報があれば AP+STA、無ければ AP のみ) / "ap" (STA を使わない。
 *       NVS の資格情報も無視) / "ap_sta" (auto と同じ)。AP は常に立てる (iPhone の操作用)。
 */
struct WiFiConfig {
    String mode;         ///< auto | ap | ap_sta
    String SSID;         ///< STA の SSID (P2P 網。空なら config 由来の STA は無効)
    String password;     ///< STA のパスフレーズ
    bool enabled;        ///< false で wifi{} 全体を無効 (Web UI の「サーバ接続」トグル)
    String broker;       ///< MQTTブローカーアドレス (空なら MQTT を使わない)
    int mqtt_port;       ///< MQTTポート番号
    int udp_port;        ///< UDP 映像受信ポート
};

/**
 * @struct SourceConfig
 * @brief フレーム供給元の調停 (FramePump / SourceArbiter)
 */
struct SourceConfig {
    String mode;             ///< auto | local | network
    uint32_t idle_timeout_ms;///< UDP がこの時間途切れたらローカルへ戻す
    bool idle_blank;         ///< 途切れ後にローカル再生が無ければ黒にする (false = 最終フレーム保持)
    uint16_t udp_queue_len;  ///< UDP 受信キュー段数 (1 段 ≈ 1.5KB, PSRAM)
};

/**
 * @struct ImageConfig
 * @brief 画像設定
 */
struct ImageConfig {
    int width;           ///< 画像幅
    int height;          ///< 画像高さ
    String format;       ///< 画像フォーマット (例: RGB565)
    String type;         ///< 画像タイプ (例: JPEG)
};

/**
 * @struct SphereConfig
 * @brief 球体デバイス固有設定 (spheres[] から自機エントリを解決した結果)
 */
struct SphereConfig {
    String id;           ///< デバイスID (MQTT clientId / トピック / OTA ホスト名)
    String mac;          ///< 登録 MAC (spheres[].mac)
    String static_ip;    ///< P2P 網での固定 IP (空なら DHCP)
    bool LED_enabled;    ///< LED制御有効化
    String IMU_type;     ///< IMUセンサータイプ (例: BNO055)
    bool ui_enabled;     ///< UI有効化
};

/**
 * @class ConfigManager
 * @brief JSON設定ファイルの読み込み・管理クラス
 *
 * LittleFSから設定ファイル(config.json)を読み込み、
 * 構造化されたデータとしてアクセスを提供します。
 */
class ConfigManager {
public:
    ConfigManager();
    virtual ~ConfigManager();

    /**
     * @brief 設定ファイルをロード
     * @param path 設定ファイルパス (デフォルト: "/config.json")
     * @return true ロード成功, false ロード失敗
     */
    bool loadConfig(const char* path = "/config.json");

    /**
     * @brief 設定ファイルを保存
     * @param path 設定ファイルパス (デフォルト: "/config.json")
     * @return true 保存成功, false 保存失敗
     */
    bool saveConfig(const char* path = "/config.json");

    /**
     * @brief JSONドキュメントを取得
     * @return DynamicJsonDocument参照
     */
    DynamicJsonDocument& getDocument() { return doc; }

    SystemConfig getSystemConfig();
    OTAConfig getOTAConfig();
    PathsConfig getPathsConfig();
    SoloConfig getSoloConfig();
    WiFiConfig getWiFiConfig();
    SourceConfig getSourceConfig();
    ImageConfig getImageConfig();

    /**
     * @brief 自機の球体設定を取得 (派生元 core と同じ解決順序)
     *
     * 解決順序:
     *   1. spheres[] のうち mac が自機 MAC と一致するエントリ
     *   2. ビルドフラグ -D SPHERE_ID="sphereNNN" と id が一致するエントリ
     *   3. mac が空の未採番スロット (警告ログ付き)
     *   4. spheres[0] (警告ログ付き。衝突の可能性あり)
     *   5. 旧形式の単一キー "sphere" (後方互換)
     *   6. どちらも無い: id="sphere001" の既定値 (solo の従来既定)
     * 結果はキャッシュされ、初回呼び出し時に選択理由をログ出力する。
     */
    SphereConfig getSphereConfig();

    /// 自機の WiFi STA MAC を "AA:BB:CC:DD:EE:FF" 形式で取得 (WiFi 未初期化でも efuse から読める)
    String getSelfMac();

    /**
     * @brief server 接続 (wifi{}) の有効/無効を書き換える (Web UI のトグル用。保存は呼び手)
     * @note wifi{} が無ければ派生元と同じ P2P 網の既定値で作る。config.json は LittleFS 上に
     *       あり OTA では更新できないため、球体側で書き換えて再起動する経路が必要。
     */
    void setServerEnabled(bool enabled);
    bool isServerConfigured();   ///< wifi.enabled && SSID あり

    bool isPSRAMEnabled() { return doc["system"]["PSRAM"] | false; }
    bool isDebugEnabled() { return doc["system"]["debug"] | false; }

    // sphere 系は spheres[] から自機エントリを解決した結果を返す (getSphereConfig 経由)
    String getSphereID() { return getSphereConfig().id; }
    String getSphereIP() { return getSphereConfig().static_ip; }
    bool isLEDEnabled() { return getSphereConfig().LED_enabled; }
    String getIMUType() { return getSphereConfig().IMU_type; }

    String getWiFiSSID() { return doc["wifi"]["SSID"] | ""; }
    String getWiFiPassword() { return doc["wifi"]["password"] | ""; }
    String getMQTTBroker() { return doc["wifi"]["broker"] | ""; }
    int getMQTTPort() { return doc["wifi"]["mqtt_port"] | 1883; }
    int getUDPPort() { return doc["wifi"]["udp_port"] | 8889; }

    String getLayoutPath() { return doc["system"]["paths"]["layout"] | "/led_layouts-5strip.csv"; }

    /// true = 接続時に OS の「ログイン」画面 (Captive Network Assistant) を開かせる。
    /// 既定 false: iOS の CNA はファイル選択ダイアログが出ないため動画をアップロードできない。
    /// false のときは OS の検出プローブに期待どおりの応答を返し、CNA を開かせない。
    bool getSoloCaptivePortal() { return doc["solo"]["captive_portal"] | false; }
    /// IMU 姿勢の移動平均フレーム数 (1 = 平滑なし、上限 IMUManager::kSmoothMax)。
    /// /api/imu {"smooth_frames": N} / MQTT led {"imu_smooth": N} で実行時にも変更できる。
    uint8_t getImuSmoothFrames() { return doc["imu"]["smooth_frames"] | 1; }
    // 起動オープニングパターン (LEDManager::playOpening)。スキップは enabled=false。
    bool getOpeningActionEnabled() { return doc["system"]["opening_action"]["enabled"] | true; }
    uint16_t getOpeningActionDurationMs() { return doc["system"]["opening_action"]["duration_ms"] | 1200; }

    int getImageWidth() { return doc["image"]["width"] | 320; }
    int getImageHeight() { return doc["image"]["height"] | 160; }
    String getImageFormat() { return doc["image"]["format"] | "RGB565"; }
    String getImageType() { return doc["image"]["type"] | "JPEG"; }

    // params ブロック = 表示パラメータの起動時デフォルト。明るさは Web UI / MQTT で実行時に
    // 上書きされ、NVS (Settings) に保存される。fallback は server 側 (config_service.DEFAULT_PARAMS)
    // と同じ値に揃えておく。
    uint8_t getParamBrightness() { return doc["params"]["brightness"] | 50; }
    uint8_t getParamSpeed() { return doc["params"]["speed"] | 50; }
    uint16_t getParamHue() { return doc["params"]["hue"] | 120; }
    uint8_t getParamSaturation() { return doc["params"]["saturation"] | 100; }

    // LEDカラーのマルチサンプリング (中心+半径R円周上N点を画像空間で平均)。
    // 実機でちらつき低減↔ボケ/負荷のトレードオフを調整するための可変パラメータ。
    bool getLedMultisampleEnabled() { return doc["led"]["multisample"]["enabled"] | true; }
    float getLedMultisampleRadius() { return doc["led"]["multisample"]["radius_px"] | 2.0f; }
    uint8_t getLedMultisamplePoints() { return doc["led"]["multisample"]["points"] | 6; }

    // solo 設定 (未設定時は右側のデフォルト)
    String getSoloVideoPath() { return doc["solo"]["video_path"] | "/video.mjpg"; }
    uint16_t getSoloHttpPort() { return doc["solo"]["http_port"] | 80; }
    String getSoloApSsid();  ///< 設定の接頭辞 + 基板固有 MAC (最大 32 bytes)
    String getSoloApPassword() { return doc["solo"]["ap"]["password"] | "sphere-solo"; }
    String getSoloApIp() { return doc["solo"]["ap"]["ip"] | "192.168.4.1"; }

    // テレメトリ: MQTT への IMU publish レート (0 で無効)。接続中のみ送る。
    uint8_t getTelemetryImuHz() { return doc["telemetry"]["imu_hz"] | 10; }

    // デバッグ出力
    void printConfig();

private:
    DynamicJsonDocument doc{8192};  // 8KB buffer for config
    bool parseJSON(const String& jsonStr);

    SphereConfig _sphere;            ///< 解決済みの自機エントリ (キャッシュ)
    bool _sphereResolved = false;    ///< _sphere が解決済みか
    String _selfMac;                 ///< 自機 MAC (キャッシュ)

    /// spheres[] から自機エントリを解決して _sphere に格納する
    void _resolveSphere();
    /// JSON の1エントリを SphereConfig へパースする
    static void _parseSphereEntry(JsonVariantConst src, SphereConfig& out);
    /// MAC 比較用の正規化 (区切り文字除去 + 大文字化)
    static String _normalizeMac(const String& mac);
};

} // namespace sastle

#endif // __CONFIG_MANAGER_H__
