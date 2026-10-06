#include "SerialConsole.h"

#include <WiFi.h>

namespace sastle {

void SerialConsole::poll() {
    while (Serial.available() > 0) {
        const char c = (char)Serial.read();
        if (c == '\r') {
            continue;
        }
        if (c != '\n') {
            if (_len < sizeof(_line) - 1) {
                _line[_len++] = c;
            }
            continue;
        }
        _line[_len] = '\0';
        _len = 0;

        char* cmd = _line;
        while (*cmd == ' ') cmd++;
        if (*cmd == '\0') {
            continue;
        }
        execute(cmd);
    }
}

void SerialConsole::execute(char* cmd) {
    if (!_ctl) return;
    SoloPlayer* player = _ctl->player();
    NetworkManager* net = _ctl->net();

    if (strcmp(cmd, "help") == 0) {
        Serial.println("[CONSOLE] commands: status | play | pause | stop | led sphere|test|off | bri N | ap on|off | ap idle N(分,0=常時) | msleep on|off | power(AP 切替) | server on|off | reboot");
    } else if (strcmp(cmd, "status") == 0) {
        Serial.printf("[CONSOLE] ap=%s ip=%s clients=%u heap=%u psram=%u\n",
                      _apSsid.c_str(), net ? net->apIP().toString().c_str() : "-",
                      (unsigned)(net ? net->clientCount() : 0),
                      (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getFreePsram());
        Serial.printf("[CONSOLE] power: ap=%s idle=%umin msleep=%s\n",
                      _ctl->apRunning() ? "on" : "off", (unsigned)_ctl->apIdleMinutes(),
                      _ctl->modemSleep() ? "on" : "off");
        if (net) {
            Serial.printf("[CONSOLE] sta=%s [%s] %s ip=%s server=%s\n",
                          net->staEnabled() ? net->staSsid().c_str() : "-", net->staOriginName(),
                          net->staConnected() ? "connected" : "disconnected",
                          net->staConnected() ? WiFi.localIP().toString().c_str() : "-",
                          _ctl->serverConfigured() ? "configured" : "off");
        }
        if (player) {
            SoloPlayer::Stats s = player->stats();
            Serial.printf("[CONSOLE] state=%s video=%s frames=%u fps=%.1f miss=%u error=%s led=%s bri=%u%%\n",
                          player->stateName(), player->videoPath().c_str(),
                          (unsigned)player->videoFrames(), s.fps, (unsigned)s.deadlineMisses,
                          player->lastError() ? player->lastError() : "-",
                          _ctl->ledModeName(), (unsigned)_ctl->brightnessPct());
        }
    } else if (strcmp(cmd, "play") == 0 || strcmp(cmd, "pause") == 0 || strcmp(cmd, "stop") == 0) {
        DeviceController::PlayResult r = (cmd[1] == 'l') ? _ctl->play()
                                       : (cmd[1] == 'a') ? _ctl->pause()
                                                         : _ctl->stop();
        Serial.printf("[CONSOLE] %s: %s (state=%s)\n", cmd, DeviceController::playResultMessage(r),
                      player ? player->stateName() : "-");
    } else if (strncmp(cmd, "led ", 4) == 0) {
        DeviceController::LedMode m;
        if (DeviceController::parseLedMode(cmd + 4, m)) {
            _ctl->setLedMode(m);
            Serial.printf("[CONSOLE] led output = %s\n", _ctl->ledModeName());
        } else {
            Serial.println("[CONSOLE] led: sphere | test | off | pixels");
        }
    } else if (strncmp(cmd, "bri ", 4) == 0) {
        int v = atoi(cmd + 4);
        if (v < 0) v = 0;
        if (v > 100) v = 100;
        _ctl->setBrightnessPct((uint8_t)v);
        Serial.printf("[CONSOLE] brightness = %d%%\n", v);
    } else if (strcmp(cmd, "server on") == 0 || strcmp(cmd, "server off") == 0) {
        const bool on = (cmd[7] == 'n');
        const bool ok = _ctl->setServerEnabled(on);
        Serial.printf("[CONSOLE] server connection %s -> %s (reboot to apply)\n",
                      on ? "on" : "off", ok ? "saved" : "SAVE FAILED");
    } else if (strcmp(cmd, "ap on") == 0 || strcmp(cmd, "ap off") == 0) {
        const bool on = (cmd[4] == 'n');
        _ctl->requestAp(on);
        Serial.printf("[CONSOLE] softap -> %s\n", on ? "start" : "stop");
    } else if (strncmp(cmd, "ap idle ", 8) == 0) {
        int m = atoi(cmd + 8);
        if (m < 0) m = 0;
        if (m > 1440) m = 1440;
        _ctl->setApIdleMinutes((uint16_t)m);
        Serial.printf("[CONSOLE] ap auto-stop = %d min (0 = always on)\n", m);
    } else if (strcmp(cmd, "msleep on") == 0 || strcmp(cmd, "msleep off") == 0) {
        const bool on = (cmd[7] == 'n');
        _ctl->setModemSleep(on);
        Serial.printf("[CONSOLE] modem sleep = %s\n", on ? "on" : "off");
    } else if (strcmp(cmd, "power") == 0) {
        _ctl->togglePowerSave();
    } else if (strcmp(cmd, "reboot") == 0) {
        Serial.println("[CONSOLE] rebooting...");
        _ctl->stop();
        _ctl->scheduleReboot(200);
    } else {
        Serial.printf("[CONSOLE] unknown command: %s (try 'help')\n", cmd);
    }
}

}  // namespace sastle
