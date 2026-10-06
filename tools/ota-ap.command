#!/bin/bash
# Mac: AP 接続後にダブルクリック。ビルド・ダウンロードは行わない。
set -euo pipefail
cd "$(dirname "$0")/.."

finish() {
    result=$?
    if [ "$result" -ne 0 ]; then
        echo "書き込みに失敗しました。AP 接続と電源を確認してください。"
    fi
    if [ -t 0 ]; then
        read -r -p "Enter で終了します。" reply || true
    fi
}
trap finish EXIT

core_dir="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}"
python="$core_dir/penv/bin/python"
espota="$core_dir/packages/framework-arduinoespressif32/tools/espota.py"
firmware=".pio/build/xiao_esp32s3/firmware.bin"
target="${1:-192.168.4.1}"

for required in "$python" "$espota" "$firmware"; do
    if [ ! -f "$required" ]; then
        echo "必要なファイルがありません: $required"
        echo "インターネット接続中に xiao_esp32s3 をビルドしてください。"
        exit 1
    fi
done

echo "対象: $target / ファーム: $firmware"
echo "Mac を対象 core の AP に接続してください。複数台の場合は対象を確認してください。"
if [ -t 0 ]; then
    read -r -p "接続したら Enter を押してください。" reply
fi

echo "接続先の状態を確認しています…"
curl --noproxy '*' -fsS --connect-timeout 3 --max-time 5 \
    "http://$target/api/status" |
    "$python" -c 'import json,sys; s=json.load(sys.stdin); print("機器: %s / SSID: %s" % (s["device"], s["ap"]["ssid"]))'

# OTA の受信前に再生を停止して CPU とフラッシュの負荷を減らす。
curl --noproxy '*' -fsS --connect-timeout 3 --max-time 5 \
    -X POST -H 'Content-Type: application/json' -d '{}' \
    "http://$target/api/stop" >/dev/null

"$python" "$espota" -i "$target" -p 3232 \
    -a isolation-sphere-ota -f "$firmware" -r

echo
echo "転送完了。再起動後、MAC 付きの新しい SSID に接続し直してください。"
if [ -t 0 ]; then
    read -r -p "新しい AP に接続したら Enter を押してください。" reply
fi
for ((attempt=0; attempt<10; attempt++)); do
    if status=$(curl --noproxy '*' -fsS --connect-timeout 2 --max-time 3 \
        "http://$target/api/status" 2>/dev/null); then
        printf '%s' "$status" | "$python" -c 'import json,sys; s=json.load(sys.stdin); print("起動確認: %s / SSID: %s / uptime: %ss" % (s["device"], s["ap"]["ssid"], s["uptime_s"]))'
        exit 0
    fi
    sleep 2
done
echo "転送は完了しましたが、起動確認はできませんでした。AP 接続を確認してください。"
