# isolation-sphere solo (XIAO ESP32S3 版)

> M5AtomS3R 版 ([isolation-sphere-solo](https://github.com/sastles-com/isolation-sphere-solo)) から分岐した、
> **XIAO ESP32S3 向けのリポジトリ**。LCD・本体ボタン・M5 ライブラリを持たない。本体の操作は iPhone の
> Web UI と IMU のトリプルシェイクで行い、今後は北極のホール素子をボタンにする (計画)。
> 共通部品の修正は AtomS3R 版から手動で取り込む。

球体 LED ディスプレイのファームウェア。**server なし (solo) と server あり (配信) の両方を 1 つの
バイナリで動かす**。

- **solo**: ESP32-S3 が SoftAP を立て、LittleFS に保存した 1 本の動画 (320×160 / 10fps) を電源投入だけで
  自動ループ再生する。動画の差し替えと再生操作は、個体シールの QR から iPhone を接続して
  Web UI (`http://192.168.4.1/`) で行う。MQTT ブローカー・配信 server・ルーター・インターネットは不要。
- **server モード** (`config.json` の `wifi{}` を有効にする、または Web UI の「サーバ接続 ON」): 同じ
  ファームが配信 server の P2P 網にも STA で入り、UDP で届く JPEG を優先して表示し、MQTT で操作を
  受ける。配信が 2 秒途切れると本体の動画に戻る。AP と Web UI はどちらのモードでも使える。

IMU による姿勢補正は描画側で動作し、球体を回しても映像の向きが保たれる。

> 派生元: [sastles-com/sastle-isolation-sphere](https://github.com/sastles-com/sastle-isolation-sphere)
> (server + core 構成)。本リポジトリは core の後継 (superset)。IMU スタック・OTA パーティション・
> 起動耐性は本リポジトリの方が新しく、MQTT / UDP のプロトコルは派生元の Python server と互換
> (server 側の変更は不要)。

---

## クイックスタート

```bash
# 1. ファームウェアと LittleFS を書き込む (初回は USB 必須: パーティション表を更新する)
pio run -e xiao_esp32s3 -t upload
pio run -e xiao_esp32s3 -t uploadfs

# 2. 動画を変換する (ffmpeg / ffprobe が必要)
tools/make_solo_video.sh input.mp4 video.mjpg -q 6

# 3. 電源投入 -> 個体シールの QR (tools/make_wifi_qr.py) を iPhone のカメラで読む -> AP に接続
#    -> 自動で開く画面、または Safari で http://192.168.4.1/ を開く
#    -> video.mjpg をアップロード
```

以降は電源を入れるだけで自動再生する (iPhone も PC も不要)。

## 動作の流れ

```
                  ┌──────────────── ESP32-S3 (XIAO) ────────────────────┐
                  │                                                      │
 iPhone ──Wi-Fi──▶│ SoftAP  ─▶ httpd (Web UI / アップロード)  [Core 0]    │
   │              │              │                                       │
   │ シールの QR   │              ▼                                       │
   └──個体シール───│         LittleFS  /video.mjpg                        │
                  │              │                                       │
 server ──STA────▶│ UDP (JPEG チャンク) ─▶ キュー   MQTT (操作/telemetry)  │
 (任意)           │              │                                       │
                  │    FramePump (1 タスク: 配信優先 / 100ms 締切) [Core 0] │
                  │      UDP 再構成 or ファイル読み ─▶ JPEG デコード ─▶ RGB565│
                  │              │                                       │
                  │      トリプルバッファ (display/ready/decode)           │
                  │              │                                       │
                  │    LEDManager (IMU 姿勢で毎パス再マッピング) [Core 1]   │
                  │              ▼                                       │
                  │        WS2812 ×800 (5ストリップ, RMT 並列出力)         │
                  └──────────────────────────────────────────────────────┘
```

- 再生は 10fps 固定。描画は ~50-60Hz で連続駆動し、IMU (100Hz) の最新姿勢で毎パス再マッピングする
  ため、動画のフレームレートと追従性は独立している。
- 締切は単調クロック (`esp_timer`) で管理し、遅れた締切は捨てる (遅延を溜め込まない)。

## リポジトリ構成

```
platformio.ini            ビルド設定 (xiao_esp32s3 / *_ota / native)
partitions.csv            フラッシュ配分 (OTA 2MB×2 + LittleFS 3.94MB)
src/                      ファームウェア
  main.cpp                起動順・タスク構成・loop (OTA / ネットワーク / MQTT / ログ)
  FramePump.{h,cpp}       フレーム供給の単一タスク (UDP 再構成 or ローカル再生 → デコード)
  SourceArbiter.h         配信 / ローカルの調停ポリシー (純粋、PC でテスト)
  SoloPlayer.{h,cpp}      ローカル MJPEG 再生の状態管理と 1 フレーム供給
  UdpReceiver.{h,cpp}     AsyncUDP → PSRAM キュー / FrameReassembler.h (16B ヘッダのチャンク再構成)
  DeviceController.{h,cpp} 操作の共通窓口 (HTTP / MQTT / コンソールが呼ぶ。γ2.2 明るさ、NVS 保存)
  SoloWebServer.{h,cpp}   Web UI・制御 API・アップロード・キャプティブポータル
  MQTTManager.{h,cpp}     MQTT (PubSubClient)。CommandHandler / Telemetry / TimeSync / RemoteLog
  MjpegReader.{h,cpp}     raw MJPEG の逐次読み出しと全件検証
  JpegScan.h              JPEG マーカー追跡によるフレーム境界判定 (PC でテスト可)
  ImageManager.{h,cpp}    JPEG デコード + トリプルバッファ
  LEDManager.{h,cpp}      球面 UV マッピング (SphereMap.h) / IMU 再投影 / FastLED 出力
  IMUManager.{h,cpp}      BNO055 (imu/*.h: 化け値検出・平滑・診断) 100Hz
  NetworkManager.{h,cpp}  SoftAP + STA (NVS の LAN > config の P2P 網)、Wi-Fi QR 文字列
  ...                     ConfigManager, Settings (NVS), FileManager, GestureManager, SoundManager, OtaManager
data/                     LittleFS に書き込む内容 (config.json, LED レイアウト CSV)
test/                     PC 上の単体テスト (JPEG 境界 / MJPEG 組み立て / IMU / 球面写像 / 調停 / 再構成)
tools/                    動画変換 / QR 生成 / OTA (ota.sh) / UDP 配信テスト (stream_to_sphere.py)
docs/solo_mode.md         設計と運用の詳細 (仕様・API・実機チェック手順)
docs/handoff.md           実装依頼時の仕様書
```

## 対応ボード

| env | ボード | 構成 |
| --- | --- | --- |
| `xiao_esp32s3` (既定) | Seeed XIAO ESP32S3 | 5ストリップ×160 LED (GPIO 1/2/3/4/44)、ブザー (GPIO43)、外部 BNO055、LCD なし。接続案内の QR は個体シール。ピンは `src/BoardConfig.h` に集約 |

## 動画の要件

- raw MJPEG: Baseline JPEG (SOF0) を区切りなしで連結したもの
- 320×160、10fps、音声なし、1 フレーム 64KiB 以下
- progressive JPEG・解像度違い・途中で切れたファイルは受理しない

`tools/make_solo_video.sh` が ffmpeg で変換し、ffprobe で解像度・フレーム数・最大フレームサイズを検査する。

容量: LittleFS 3.94MB のうち動画に使えるのは約 3.8MB。平均 10KiB/フレームなら約 38 秒。

## 操作

| 手段 | できること |
| --- | --- |
| Web UI (`http://192.168.4.1/`) | 状態確認、再生/一時停止/停止、明るさ、動画の変換とアップロード/削除、表示パターン、IMU 平滑、映像ソース、サーバ接続 ON/OFF、LAN 接続、再起動 |
| HTTP API | `GET /api/status`、`POST /api/play|pause|stop`、`/api/brightness`、`/api/led`、`/api/imu`、`/api/source`、`/api/server`、`/api/power`、`/api/wifi`、`/api/video`、`/api/video/delete`、`/api/reboot` |
| MQTT (server モード) | `sphere/all|<id>/command/{params,playback,led,system}` を受信、`sphere/<id>/{status,state,imu,log,gesture}` を送信 (派生元と同じ) |
| シリアルコンソール (115200) | `help` / `status` / `play` / `pause` / `stop` / `led sphere|test|off` / `bri N` / `server on|off` / `ap on|off` / `ap idle N` / `msleep on|off` / `power` (AP 切替) / `reboot` |

設定は `data/config.json` (`solo.ap.*`、`wifi{}` = server の P2P 網と broker、`source{}` = 調停、
`spheres[]` = MAC → 自機 ID / 固定 IP)。書き込みは `pio run -t uploadfs` (USB)。**サーバ接続の ON/OFF
だけは Web UI / コンソールから球体上の config.json を書き換えて再起動できる** (OTA では LittleFS を
更新できないため)。明るさ・軸表示・IMU 平滑・LAN の資格情報は NVS に保存される。

`solo.ap.ssid` は SSID の接頭辞です。実際の SSID は基板の MAC を付けた
`isolation-sphere-F09E9E3267D0` のような名前になり、複数台でも区別できます。
最大 32 bytes に収まるよう接頭辞を短縮し、Web 画面にも同じ名前を使います。
更新後は新しい SSID に接続し直してください。server モードの機器 ID・固定 IP は
`spheres[]` の MAC 登録で割り当てるため、追加基板には重複しない ID と IP を登録してください。

## 省電力 (AP / モデム)

球体の消費電力は WS2812 800 個が支配的ですが、デモ中は AP が不要なので止められるようにしてあります。
**電源投入時は常に AP 起動** で始まります。

| 機能 | 内容 |
| --- | --- |
| AP 自動停止 | 接続端末が 0 台のまま設定時間 (既定 10 分。しない/5/10/30/60) が経つと AP を止める。LAN (STA) が無ければ無線ごと止まる。設定は NVS に保存 |
| AP の ON/OFF | Web UI の「今すぐ停止」、`ap on|off`、MQTT `system` の `ap` |
| モデム省電力 | STA 接続中のビーコン間スリープ (WIFI_PS_MIN_MODEM)。既定 OFF。**AP だけの構成ではほぼ効かない** (AP は眠れない)。ON だと応答が鈍り UDP 映像を取りこぼしうる |
| トリプルシェイク | AP の ON/OFF を切り替える。従来の UI モード (回転アクション) は未実装だったため置き換え |

AP が止まっても再生は続きます。復帰は、シェイク / シリアル / MQTT / 電源の入れ直しのいずれかです。

## 開発

```bash
pio run -e xiao_esp32s3      # ビルド
pio test -e native            # 単体テスト 67 件 (実機不要)
pio device monitor            # シリアルログ (115200)
pio run -e xiao_esp32s3_ota -t upload   # OTA 書き込み (先に PC を AP へ接続)
tools/ota.sh                  # LAN / P2P 網経由の OTA (STA の IP を解決して直指定)
python3 tools/stream_to_sphere.py --target <STA の IP> --fps 15   # UDP 配信テスト (Pillow が必要)
```

詳細・設計判断・実機チェック手順は [docs/solo_mode.md](docs/solo_mode.md) を参照。

Mac で AP 経由の OTA を行う場合は、インターネット接続中に `xiao_esp32s3` をビルドし、
`tools/ota-ap.command` をダブルクリックしてください。ターミナルの案内に従って対象 core の
AP に接続し、Enter を押すとビルド済みファームを転送します。転送中のインターネット接続は不要です。
再起動後は新しい SSID に接続して Enter を押すと起動状態を確認できます。
