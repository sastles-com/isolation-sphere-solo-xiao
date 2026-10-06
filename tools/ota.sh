#!/usr/bin/env bash
# LAN (STA) 経由の OTA。mDNS (<sphere id>.local、既定 sphere001.local) の解決は PC 側で時々失敗する
# (getent は通るのに espota の gethostbyname が "Host Not Found" を返す) ため、
# 先に IP を解決してから --upload-port で直指定する。
#
#   tools/ota.sh                 # ファーム
#   tools/ota.sh uploadfs        # LittleFS (data/)
#   SPHERE_IP=192.168.10.128 tools/ota.sh   # 解決を飛ばして IP 直指定
set -euo pipefail
TARGET=${1:-upload}
HOST=${SPHERE_HOST:-sphere001.local}
cd "$(dirname "$0")/.."
IP=${SPHERE_IP:-}
if [ -z "$IP" ]; then
    IP=$(getent hosts "$HOST" | awk '{print $1; exit}' || true)
fi
if [ -z "$IP" ]; then
    echo "!! $HOST を解決できません。SPHERE_IP=<IP> を指定してください (Web UI の「LAN (STA)」欄に出ます)" >&2
    exit 1
fi
echo "== 球体: $IP  target=$TARGET"
# 再生中はデコードとフラッシュ読みで OTA の受信が間に合わないことがあるので先に止める
# (ファーム側の onStart でも止めるが、古いファームには無い)
curl -s -m 5 -X POST -H 'Content-Type: application/json' -d '{}' "http://$IP/api/stop" >/dev/null || true
pio run -e xiao_esp32s3_lan_ota -t "$TARGET" --upload-port "$IP"
echo "== 再起動待ち"
for i in $(seq 1 20); do sleep 3; curl -s -m 3 "http://$IP/api/status" >/dev/null 2>&1 && break; done
curl -s -m 5 "http://$IP/api/status" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("== state=%s uptime=%ss sta=%s" % (d["state"], d["uptime_s"], d["sta"]["ip"]))' || echo "!! 起動確認できず"
