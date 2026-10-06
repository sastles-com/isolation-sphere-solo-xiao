#include "ConfigManager.h"
#include <WiFi.h>

// グローバルデバッグフラグ (main.cppで定義)
extern bool g_debugEnabled;

namespace sastle {

namespace {
// wifi{} が無いときに setServerEnabled(true) が書き込む P2P 網の既定値 (派生元 core と同じ)
constexpr const char* kDefaultP2pSsid = "ESP32-P2P-Direct";
constexpr const char* kDefaultP2pPassword = "isolation-sphere-p2p";
constexpr const char* kDefaultBroker = "192.168.49.1";
constexpr int kDefaultMqttPort = 1883;
constexpr int kDefaultUdpPort = 8889;
}  // namespace

ConfigManager::ConfigManager() : doc(8192) {
}

ConfigManager::~ConfigManager() {
}

bool ConfigManager::loadConfig(const char* path) {
    Serial.printf("Loading config from: %s\n", path);

    String jsonStr;
    if (!FileManager::readFile(path, jsonStr)) {
        Serial.println("Failed to read config file");
        return false;
    }

    Serial.printf("Config file size: %d bytes\n", jsonStr.length());

    return parseJSON(jsonStr);
}

bool ConfigManager::parseJSON(const String& jsonStr) {
    DeserializationError error = deserializeJson(doc, jsonStr);

    if (error) {
        Serial.printf("JSON parse error: %s\n", error.c_str());
        return false;
    }

    Serial.println("Config parsed successfully");
    // 新しい JSON になったので自機エントリのキャッシュを捨てる (次回参照時に再解決)
    _sphereResolved = false;
    return true;
}

bool ConfigManager::saveConfig(const char* path) {
    String output;
    serializeJsonPretty(doc, output);

    if (FileManager::writeFile(path, output)) {
        Serial.printf("Config saved to: %s\n", path);
        return true;
    } else {
        Serial.println("Failed to save config");
        return false;
    }
}

SystemConfig ConfigManager::getSystemConfig() {
    SystemConfig config;
    config.debug = doc["system"]["debug"] | false;
    config.PSRAM = doc["system"]["PSRAM"] | false;

    // グローバルデバッグフラグを設定
    g_debugEnabled = config.debug;

    return config;
}

OTAConfig ConfigManager::getOTAConfig() {
    OTAConfig config;
    config.enabled = doc["system"]["ota"]["enabled"] | true;
    config.username = doc["system"]["ota"]["username"] | "admin";
    config.password = doc["system"]["ota"]["password"] | "";
    config.listen_port = doc["system"]["ota"]["listen_port"] | 3232;
    return config;
}

PathsConfig ConfigManager::getPathsConfig() {
    PathsConfig config;
    config.config = doc["system"]["paths"]["config"] | "/littlefs/config.json";
    config.layout = doc["system"]["paths"]["layout"] | "/littlefs/led_layouts-5strip.csv";
    config.logs = doc["system"]["paths"]["logs"] | "/littlefs/logs/";
    return config;
}

SoloConfig ConfigManager::getSoloConfig() {
    SoloConfig config;
    config.video_path = getSoloVideoPath();
    config.http_port = getSoloHttpPort();
    config.ap_ssid = getSoloApSsid();
    config.ap_password = getSoloApPassword();
    config.ap_ip = getSoloApIp();
    return config;
}

WiFiConfig ConfigManager::getWiFiConfig() {
    WiFiConfig config;
    config.mode = doc["wifi"]["mode"] | "auto";
    config.SSID = doc["wifi"]["SSID"] | "";
    config.password = doc["wifi"]["password"] | "";
    config.enabled = doc["wifi"]["enabled"] | true;
    config.broker = doc["wifi"]["broker"] | "";
    config.mqtt_port = doc["wifi"]["mqtt_port"] | kDefaultMqttPort;
    config.udp_port = doc["wifi"]["udp_port"] | kDefaultUdpPort;
    return config;
}

SourceConfig ConfigManager::getSourceConfig() {
    SourceConfig config;
    config.mode = doc["source"]["mode"] | "auto";
    config.idle_timeout_ms = doc["source"]["idle_timeout_ms"] | 2000;
    config.idle_blank = doc["source"]["idle_blank"] | true;
    config.udp_queue_len = doc["source"]["udp_queue_len"] | 32;
    if (config.udp_queue_len < 4) config.udp_queue_len = 4;
    if (config.udp_queue_len > 128) config.udp_queue_len = 128;
    return config;
}

bool ConfigManager::isServerConfigured() {
    WiFiConfig w = getWiFiConfig();
    return w.enabled && w.SSID.length() > 0 && w.mode != "ap";
}

void ConfigManager::setServerEnabled(bool enabled) {
    JsonObject wifi = doc["wifi"];
    if (wifi.isNull()) {
        wifi = doc.createNestedObject("wifi");
    }
    if (!wifi.containsKey("SSID") || String(wifi["SSID"] | "").length() == 0) {
        wifi["SSID"] = kDefaultP2pSsid;
        wifi["password"] = kDefaultP2pPassword;
    }
    if (!wifi.containsKey("broker")) wifi["broker"] = kDefaultBroker;
    if (!wifi.containsKey("mqtt_port")) wifi["mqtt_port"] = kDefaultMqttPort;
    if (!wifi.containsKey("udp_port")) wifi["udp_port"] = kDefaultUdpPort;
    if (!wifi.containsKey("mode")) wifi["mode"] = "auto";
    wifi["enabled"] = enabled;
}

ImageConfig ConfigManager::getImageConfig() {
    ImageConfig config;
    config.width = doc["image"]["width"] | 320;
    config.height = doc["image"]["height"] | 160;
    config.format = doc["image"]["format"] | "RGB565";
    config.type = doc["image"]["type"] | "JPEG";
    return config;
}

String ConfigManager::_normalizeMac(const String& mac) {
    // "F0:9E:9E:32:67:D0" / "f0-9e-9e-32-67-d0" / "f09e9e3267d0" を同一視する
    String out;
    out.reserve(12);
    for (size_t i = 0; i < mac.length(); ++i) {
        const char c = mac[i];
        if (c == ':' || c == '-' || c == '.' || c == ' ') continue;
        out += (char)toupper((unsigned char)c);
    }
    return out;
}

String ConfigManager::getSelfMac() {
    if (_selfMac.length() == 0) {
        // WiFi 未初期化 (WIFI_MODE_NULL) でも efuse から読めるため、
        // NetworkManager::begin() より前のこの時点で参照して問題ない。
        _selfMac = WiFi.macAddress();
    }
    return _selfMac;
}

String ConfigManager::getSoloApSsid() {
    String prefix = doc["solo"]["ap"]["ssid"] | "isolation-sphere";
    if (prefix.length() == 0) prefix = "isolation-sphere";
    const String suffix = "-" + _normalizeMac(getSelfMac());
    // SSID は最大 32 bytes。UTF-8 の文字の途中では切らない。
    const size_t maxPrefix = 32 - suffix.length();
    if (prefix.length() > maxPrefix) {
        size_t end = maxPrefix;
        while (end > 0 && ((unsigned char)prefix[end] & 0xc0) == 0x80) --end;
        prefix = prefix.substring(0, end);
    }
    return prefix + suffix;
}

void ConfigManager::_parseSphereEntry(JsonVariantConst src, SphereConfig& out) {
    out.id = src["id"] | "sphere001";
    out.mac = src["mac"] | "";
    out.static_ip = src["static_ip"] | "";
    out.LED_enabled = src["features"]["LED"] | false;
    out.IMU_type = src["features"]["IMU"] | "";
    out.ui_enabled = src["features"]["ui"] | false;
}

void ConfigManager::_resolveSphere() {
    _sphereResolved = true;  // 失敗しても再解決ループに入らないよう先に立てる

    const String selfMac = getSelfMac();
    const String selfKey = _normalizeMac(selfMac);

    JsonArrayConst spheres = doc["spheres"].as<JsonArrayConst>();
    if (!spheres.isNull() && spheres.size() > 0) {
        // 1. 自機 MAC と一致するエントリ (通常経路)
        for (JsonVariantConst entry : spheres) {
            const String key = _normalizeMac(entry["mac"] | "");
            if (key.length() > 0 && key == selfKey) {
                _parseSphereEntry(entry, _sphere);
                Serial.printf("[Config] Sphere resolved by MAC: %s (mac=%s)\n",
                              _sphere.id.c_str(), selfMac.c_str());
                return;
            }
        }

#ifdef SPHERE_ID
        // 2. ビルドフラグ -D SPHERE_ID="sphereNNN" 指定 (MAC 未採番の新基板用)
        for (JsonVariantConst entry : spheres) {
            if (String(SPHERE_ID) == String(entry["id"] | "")) {
                _parseSphereEntry(entry, _sphere);
                Serial.printf("[Config] Sphere resolved by build flag SPHERE_ID: %s (mac=%s)\n",
                              _sphere.id.c_str(), selfMac.c_str());
                return;
            }
        }
        Serial.printf("[Config] WARNING: SPHERE_ID=\"%s\" is not in spheres[]\n", SPHERE_ID);
#endif

        // 3. mac が空の「未採番スロット」があればそれを使う。
        //    既に MAC 登録済みのエントリ (稼働中の球体) と id/static_ip が衝突すると
        //    同一 IP・同一 MQTT clientId の2台になり、ブローカーが古い接続を切って
        //    双方が再接続を繰り返す。新基板を足すときは空 mac + 未使用 IP のスロットを
        //    1つ用意しておけば、起動ログの "Own MAC:" を後から記入するだけで衝突せずに立ち上がる。
        for (JsonVariantConst entry : spheres) {
            if (_normalizeMac(entry["mac"] | "").length() == 0) {
                _parseSphereEntry(entry, _sphere);
                Serial.printf("[Config] WARNING: own MAC %s not registered; using unclaimed slot '%s'\n",
                              selfMac.c_str(), _sphere.id.c_str());
                Serial.printf("[Config]          -> spheres[] の \"%s\" に \"mac\": \"%s\" を記入してください\n",
                              _sphere.id.c_str(), selfMac.c_str());
                return;
            }
        }

        // 4. 先頭エントリにフォールバック。稼働中の球体と IP/clientId が衝突する
        //    可能性があるため最後の手段。
        _parseSphereEntry(spheres[0], _sphere);
        Serial.printf("[Config] WARNING: own MAC %s not found in spheres[]; using '%s'.\n",
                      selfMac.c_str(), _sphere.id.c_str());
        Serial.printf("[Config]          -> config.json の spheres[] に \"mac\": \"%s\" を登録してください\n",
                      selfMac.c_str());
        return;
    }

    // 5. 旧形式の単一キー "sphere" (solo の従来 config.json)
    JsonVariantConst legacy = doc["sphere"];
    if (!legacy.isNull()) {
        _parseSphereEntry(legacy, _sphere);
        Serial.printf("[Config] Legacy single \"sphere\" entry used: %s (mac=%s)\n",
                      _sphere.id.c_str(), selfMac.c_str());
        return;
    }

    // 6. どちらも無い: コンパイル時既定 (id=sphere001)。config が読めない起動でもここに来る
    _parseSphereEntry(JsonVariantConst(), _sphere);
    Serial.printf("[Config] WARNING: no \"spheres\"/\"sphere\" entry in config.json; using defaults (id=%s mac=%s)\n",
                  _sphere.id.c_str(), selfMac.c_str());
}

SphereConfig ConfigManager::getSphereConfig() {
    if (!_sphereResolved) {
        _resolveSphere();
    }
    return _sphere;
}

void ConfigManager::printConfig() {
    Serial.println("\n=== Configuration ===");

    SystemConfig sys = getSystemConfig();
    Serial.printf("System:\n");
    Serial.printf("  PSRAM: %s, Debug: %s\n",
                  sys.PSRAM ? "enabled" : "disabled",
                  sys.debug ? "enabled" : "disabled");

    SoloConfig solo = getSoloConfig();
    Serial.printf("\nSolo:\n");
    Serial.printf("  Video: %s\n", solo.video_path.c_str());
    Serial.printf("  AP:    %s (ip %s, http %u)\n",
                  solo.ap_ssid.c_str(), solo.ap_ip.c_str(), (unsigned)solo.http_port);

    WiFiConfig wifi = getWiFiConfig();
    Serial.printf("\nServer (wifi{}): %s, mode=%s\n",
                  isServerConfigured() ? "configured" : "not configured", wifi.mode.c_str());
    Serial.printf("  STA SSID: %s%s\n", wifi.SSID.c_str(), wifi.enabled ? "" : " (disabled)");
    Serial.printf("  MQTT Broker: %s:%d, UDP Port: %d\n", wifi.broker.c_str(), wifi.mqtt_port, wifi.udp_port);

    SourceConfig src = getSourceConfig();
    Serial.printf("\nSource: mode=%s idle_timeout=%lums idle_blank=%s udp_queue=%u\n",
                  src.mode.c_str(), (unsigned long)src.idle_timeout_ms,
                  src.idle_blank ? "yes" : "no", (unsigned)src.udp_queue_len);

    OTAConfig ota = getOTAConfig();
    Serial.printf("\nOTA: %s\n", ota.enabled ? "enabled" : "disabled");
    Serial.printf("  Username: %s, Port: %d\n", ota.username.c_str(), ota.listen_port);

    ImageConfig img = getImageConfig();
    Serial.printf("\nImage: %dx%d %s (%s)\n",
                  img.width, img.height, img.format.c_str(), img.type.c_str());

    SphereConfig sphere = getSphereConfig();
    Serial.printf("\nSphere: %s\n", sphere.id.c_str());
    Serial.printf("  Own MAC: %s (config.json の spheres[].mac と照合)\n", getSelfMac().c_str());
    Serial.printf("  MAC: %s, static IP: %s\n", sphere.mac.c_str(), sphere.static_ip.c_str());
    Serial.printf("  LED: %s, IMU: %s\n",
                  sphere.LED_enabled ? "enabled" : "disabled",
                  sphere.IMU_type.c_str());

    PathsConfig paths = getPathsConfig();
    Serial.printf("\nPaths:\n");
    Serial.printf("  Config: %s\n", paths.config.c_str());
    Serial.printf("  Layout: %s\n", paths.layout.c_str());

    Serial.printf("\nParams (startup defaults):\n");
    Serial.printf("  Brightness: %d%%, Speed: %d%%, Hue: %d, Saturation: %d%%\n",
                  getParamBrightness(), getParamSpeed(), getParamHue(), getParamSaturation());

    Serial.println("====================\n");
}

} // namespace sastle
