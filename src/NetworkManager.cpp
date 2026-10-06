#include "NetworkManager.h"

#include <Preferences.h>

namespace {
// STA 資格情報の保管先 (NVS)。config.json に書かないのは、リポジトリに
// 自宅 Wi-Fi のパスワードが混入するのを避けるため。
constexpr const char* kNvsNamespace = "solo";
constexpr const char* kKeySsid = "sta_ssid";
constexpr const char* kKeyPass = "sta_pass";
}  // namespace

namespace sastle {

NetworkManager::NetworkManager() : _started(false) {}

NetworkManager::~NetworkManager() {
    stop();
}

StaPlan NetworkManager::resolveStaPlan(ConfigManager& config) {
    StaPlan plan;

    const WiFiConfig wifi = config.getWiFiConfig();
    if (wifi.mode == "ap") {
        // 明示的に STA を使わない (NVS の資格情報も無視)
        return plan;
    }

    // 1. NVS (Web UI の「LAN 接続」で保存した家庭 LAN)。DHCP。
    //    「利用者が変えた値が勝つ」= 明るさと同じ規則。空 SSID で保存すると config 側へ戻る。
    Preferences prefs;
    if (prefs.begin(kNvsNamespace, true)) {
        String ssid = prefs.getString(kKeySsid, "");
        String pass = prefs.getString(kKeyPass, "");
        prefs.end();
        if (ssid.length() > 0) {
            plan.origin = StaPlan::Origin::Nvs;
            plan.ssid = ssid;
            plan.password = pass;
            return plan;
        }
    }

    // 2. config.json の wifi{} (P2P 網)。static_ip は解決済みの自機 sphere エントリから。
    if (wifi.enabled && wifi.SSID.length() > 0) {
        plan.origin = StaPlan::Origin::Config;
        plan.ssid = wifi.SSID;
        plan.password = wifi.password;
        const String staticIp = config.getSphereIP();
        if (staticIp.length() > 0 && plan.ip.fromString(staticIp)) {
            // ゲートウェイは x.x.x.1、サブネットは /24 (派生元と同じ前提)
            plan.gateway = IPAddress(plan.ip[0], plan.ip[1], plan.ip[2], 1);
            plan.subnet = IPAddress(255, 255, 255, 0);
            plan.useStaticIp = true;
        }
    }
    return plan;
}

bool NetworkManager::begin(ConfigManager& config) {
    Serial.println("\n=== Network Manager ===");

    const SoloConfig solo = config.getSoloConfig();
    IPAddress apIp;
    if (!apIp.fromString(solo.ap_ip)) {
        apIp = IPAddress(192, 168, 4, 1);
    }

    _plan = resolveStaPlan(config);

    // STA 資格情報があれば最初から AP+STA で立ち上げる (後から mode を変えると AP が落ちる)
    WiFi.mode(_plan.valid() ? WIFI_AP_STA : WIFI_AP);
    // モデム省電力を無効化。省電力中はビーコン間でスリープし、AP としての応答が遅れて
    // Web UI の操作感が落ちる。STA 側では再送のない UDP 映像を取りこぼす。
    applyPowerSave();

    uint8_t channel = 0;
    if (_plan.valid()) {
        // STA を先に始め、短く待つ。繋がれば AP を同じチャンネルで立てられる (後から STA が
        // 繋がると AP がチャンネルを移り、接続中の iPhone が数秒切れる)。繋がらなくても続行。
        beginSta(_plan, solo.ap_ssid);
        const uint32_t t0 = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t0 < kBootStaWaitMs) {
            delay(50);
        }
        if (WiFi.status() == WL_CONNECTED) {
            channel = (uint8_t)WiFi.channel();
            Serial.printf("STA: connected during boot, AP will use channel %u\n", (unsigned)channel);
        } else {
            Serial.printf("STA: not connected within %lums (AP starts on default channel)\n",
                          (unsigned long)kBootStaWaitMs);
        }
    }

    const bool apOk = beginSoftAP(solo.ap_ssid, solo.ap_password, apIp, channel);

    if (_plan.valid()) {
        // begin() 内の待ちで既に繋がっていれば poll() がエッジを検出して onStaUp を呼ぶ
        _staWasConnected = false;
    }
    return apOk;
}

bool NetworkManager::beginSoftAP(const String& ssid, const String& password, const IPAddress& ip,
                                 uint8_t channel) {
    if (ssid.length() == 0) {
        Serial.println("ERROR: SoftAP SSID is empty");
        return false;
    }

    if (WiFi.getMode() == WIFI_MODE_NULL) {
        // begin(config) を経由しない呼び出し (互換) のため
        WiFi.mode(storedStaSsid().length() > 0 ? WIFI_AP_STA : WIFI_AP);
        applyPowerSave();
    }

    const IPAddress subnet(255, 255, 255, 0);
    if (!WiFi.softAPConfig(ip, ip, subnet)) {
        Serial.println("ERROR: softAPConfig failed");
        return false;
    }

    // WPA2 は 8 文字以上のパスフレーズが必須。短い場合は起動に失敗するので
    // オープン AP にフォールバックし、その旨を明示する。
    const bool open = password.length() < 8;
    if (open && password.length() > 0) {
        Serial.println("WARN: AP password shorter than 8 chars -> starting as OPEN network");
    }
    if (channel < 1 || channel > 13) {
        channel = 1;
    }
    if (!WiFi.softAP(ssid.c_str(), open ? nullptr : password.c_str(), channel)) {
        Serial.println("ERROR: softAP start failed");
        return false;
    }

    _started = true;
    _apSsid = ssid;
    _apPassword = password;
    _apIp = ip;
    _apChannel = channel;
    _apIdleSinceMs = millis();
    Serial.printf("SoftAP started: SSID=%s (%s) ch=%u\n", ssid.c_str(), open ? "open" : "WPA2",
                  (unsigned)channel);
    Serial.printf("  AP IP:  %s\n", WiFi.softAPIP().toString().c_str());
    Serial.printf("  AP MAC: %s\n", WiFi.softAPmacAddress().c_str());
    return true;
}

bool NetworkManager::saveStaCredentials(const String& ssid, const String& password) {
    Preferences prefs;
    if (!prefs.begin(kNvsNamespace, false)) {
        return false;
    }
    bool ok;
    if (ssid.length() == 0) {
        prefs.remove(kKeySsid);
        prefs.remove(kKeyPass);
        ok = true;
    } else {
        ok = prefs.putString(kKeySsid, ssid) > 0;
        prefs.putString(kKeyPass, password);  // 空パスワード (オープン AP) も許容
    }
    prefs.end();
    return ok;
}

String NetworkManager::storedStaSsid() {
    Preferences prefs;
    if (!prefs.begin(kNvsNamespace, true)) {
        return String();
    }
    String ssid = prefs.getString(kKeySsid, "");
    prefs.end();
    return ssid;
}

bool NetworkManager::beginSta(const StaPlan& plan, const String& hostname) {
    if (!plan.valid()) {
        Serial.println("STA: not configured (POST /api/wifi で LAN、または config.json wifi{} で P2P 網)");
        return false;
    }
    _plan = plan;
    _staEnabled = true;
    if (hostname.length() > 0) {
        WiFi.setHostname(hostname.c_str());
    }
    // 再接続は poll() のバックオフで行う (autoReconnect は AP の応答を鈍らせる。ヘッダ参照)
    WiFi.setAutoReconnect(false);
    if (plan.useStaticIp) {
        if (!WiFi.config(plan.ip, plan.gateway, plan.subnet)) {
            Serial.println("STA: WARN static IP config failed (falling back to DHCP)");
        }
    }
    startStaAttempt();
    Serial.printf("STA: connecting to \"%s\" [%s%s] (non-blocking; AP stays up)\n",
                  plan.ssid.c_str(), plan.originName(),
                  plan.useStaticIp ? (", ip " + plan.ip.toString()).c_str() : "");
    return true;
}

void NetworkManager::startStaAttempt() {
    _lastAttemptMs = millis();
    WiFi.begin(_plan.ssid.c_str(), _plan.password.length() ? _plan.password.c_str() : nullptr);
}

void NetworkManager::poll() {
    pollApIdle();
    if (!_staEnabled) {
        return;
    }
    const uint32_t now = millis();
    const bool connected = (WiFi.status() == WL_CONNECTED);
    if (connected != _staWasConnected) {
        _staWasConnected = connected;
        if (connected) {
            _backoffMs = kBackoffMinMs;
            // WiFi.begin() が省電力設定を既定 (MIN_MODEM) に戻すため、接続後に設定値を入れ直す。
            // 既定は省電力 OFF: 省電力中はビーコン間でスリープし、再送のない UDP 映像を取りこぼす
            // (派生元の知見)。
            applyPowerSave();
            Serial.printf("STA: connected to \"%s\" [%s] IP=%s ch=%d RSSI=%d "
                          "(OTA: pio run -e xiao_esp32s3_lan_ota -t upload --upload-port <IP>)\n",
                          _plan.ssid.c_str(), _plan.originName(), WiFi.localIP().toString().c_str(),
                          WiFi.channel(), WiFi.RSSI());
            if (_onUp) _onUp();
        } else {
            Serial.printf("STA: disconnected from \"%s\" (retry in %lus)\n", _plan.ssid.c_str(),
                          (unsigned long)(_backoffMs / 1000));
            if (_onDown) _onDown();
        }
        return;
    }
    if (!connected && now - _lastAttemptMs >= _backoffMs) {
        // 相手が居ない間は間隔を広げる (5s → 10s → ... → 60s)
        _backoffMs = _backoffMs * 2 > kBackoffMaxMs ? kBackoffMaxMs : _backoffMs * 2;
        WiFi.disconnect(false, false);
        startStaAttempt();
    }
}

void NetworkManager::stop() {
    if (_started) {
        WiFi.softAPdisconnect(true);
        _started = false;
        Serial.println("SoftAP stopped");
    }
}

bool NetworkManager::startAp() {
    if (_started) {
        return true;
    }
    if (_apSsid.length() == 0) {
        Serial.println("SoftAP restart: no previous AP settings");
        return false;
    }
    // beginSoftAP は引数を覚え直すので、メンバのコピーを渡す
    const String ssid = _apSsid, pass = _apPassword;
    const IPAddress ip = _apIp;
    return beginSoftAP(ssid, pass, ip, _apChannel);
}

void NetworkManager::setApIdleTimeoutMin(uint16_t minutes) {
    _apIdleTimeoutMin = minutes;
    _apIdleSinceMs = millis();   // 設定を変えた時点から数え直す
}

void NetworkManager::setModemSleep(bool on) {
    _modemSleep = on;
    applyPowerSave();
}

void NetworkManager::applyPowerSave() {
    // 無線が止まっている間 (mode NULL) は呼ばない。次の mode 設定後に再度適用される
    if (WiFi.getMode() == WIFI_MODE_NULL) {
        return;
    }
    WiFi.setSleep(_modemSleep ? WIFI_PS_MIN_MODEM : WIFI_PS_NONE);
}

void NetworkManager::pollApIdle() {
    if (!_started || _apIdleTimeoutMin == 0) {
        return;
    }
    const uint32_t now = millis();
    if (WiFi.softAPgetStationNum() > 0) {
        _apIdleSinceMs = now;   // 端末が居る間は数えない
        return;
    }
    if (now - _apIdleSinceMs >= (uint32_t)_apIdleTimeoutMin * 60000UL) {
        Serial.printf("SoftAP: no client for %u min -> auto stop (press the button to restart)\n",
                      (unsigned)_apIdleTimeoutMin);
        stop();
    }
}

void NetworkManager::printStatus() const {
    Serial.println("\n=== Network Status ===");
    Serial.printf("SoftAP:  %s\n", _started ? "running" : "stopped");
    if (_started) {
        Serial.printf("SSID:    %s\n", WiFi.softAPSSID().c_str());
        Serial.printf("IP:      %s\n", WiFi.softAPIP().toString().c_str());
        Serial.printf("Clients: %u\n", (unsigned)WiFi.softAPgetStationNum());
    }
    Serial.printf("STA:     %s", _staEnabled ? _plan.ssid.c_str() : "disabled");
    if (_staEnabled) {
        Serial.printf(" [%s] %s IP=%s", _plan.originName(),
                      staConnected() ? "connected" : "disconnected",
                      WiFi.localIP().toString().c_str());
    }
    Serial.println();
}

String NetworkManager::wifiQrText(const String& ssid, const String& password) {
    auto escape = [](const String& in) {
        String out;
        out.reserve(in.length() + 4);
        for (size_t i = 0; i < in.length(); i++) {
            const char c = in[i];
            if (c == '\\' || c == ';' || c == ',' || c == ':' || c == '"') {
                out += '\\';
            }
            out += c;
        }
        return out;
    };
    String qr = "WIFI:";
    if (password.length() < 8) {
        qr += "T:nopass;S:" + escape(ssid) + ";;";
    } else {
        qr += "T:WPA;S:" + escape(ssid) + ";P:" + escape(password) + ";;";
    }
    return qr;
}

}  // namespace sastle
