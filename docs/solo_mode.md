> **XIAO ESP32S3 版の注記**: 本書は M5AtomS3R 版から引き継いだ。LCD・QR 表示・本体ボタン・M5 IMU に関する
> 記述と実機検証の記録 (§6 QR、§9 の AtomS3R 実測) は AtomS3R 版の経緯であり、本リポジトリでは該当機能を
> 削除している。XIAO 版の方針と計画は `docs/xiao_bringup.md`。

# solo 設計ノート

`isolation-sphere-solo` の設計判断、仕様、運用手順、実機チェック項目をまとめる。
使い方の概要は [../README.md](../README.md)、実装依頼時の仕様は [handoff.md](handoff.md) を参照。

---

## 1. 派生元の調査結果 (実装前に実コードで確認した事実)

本リポジトリは [sastles-com/sastle-isolation-sphere](https://github.com/sastles-com/sastle-isolation-sphere)
の `core/` (ESP32-S3 ファームウェア) を solo 専用に切り出したもの。切り出しの判断根拠として、
派生元のコードから確認した事実を残す (ハンドオフ資料は最新コードを読めていない前提で書かれていた)。

| 項目 | 事実 |
| --- | --- |
| ビルド | PlatformIO + Arduino framework、`board = m5stack-atoms3` (flash 8MB, PSRAM OPI) |
| パーティション | nvs / otadata / phy / ota_0 1.5MB / ota_1 1.5MB / spiffs(LittleFS) 3MB。末尾 約1.94MB が未使用 |
| **ファームサイズ** | **派生元をそのままビルドすると 1,723,509 bytes (1.5MB スロットの 109.6%) で収まらない**。release + `CORE_DEBUG_LEVEL=1` でも 1,594,145 bytes (101.4%)。この超過は solo 化前から存在していた |
| フレーム供給 | server → UDP チャンク (16B ヘッダ, ≤1400B) → 再構成 → TJpg_Decoder → RGB565 → トリプルバッファ |
| デコーダ | `bodmer/TJpg_Decoder` (Baseline JPEG のみ)、出力 RGB565、`setSwapBytes(false)`。デコードは Core0 |
| 描画 | FastLED RMT 並列出力、レンダタスクが Core1 prio2 で連続駆動 (~50-60Hz)。毎パス最新 IMU で再マッピングし、**フレーム到着に依存しない** |
| IMU | 100Hz 更新。`loop()` タスクで取得し、レンダタスクが読む |
| 制御 | MQTT (PubSubClient) を `loop()` で駆動、`CommandHandler` が params/playback/led/system を処理 |
| 設定 | LittleFS `/config.json` を ArduinoJson で読み書き。NVS/Preferences は未使用。**デバイスレベルの「モード」概念は無かった** (LED 出力モード sphere/pixels/off/test のみ) |
| LCD | M5AtomS3R 128×128、M5GFX (LovyanGFX)。LovyanGFX は `qrcode()` を内蔵 |
| デバイス内 HTTP / DNS | **無し**。`esp_http_server` と `DNSServer` は ESP-IDF / arduino-esp32 に同梱 |
| ローカル再生 | **無し**。`data/images/*.jpg` は LittleFS に載っていたがファームは読んでいなかった (1.2MB の無駄) |
| 既存ビルドエラー | `LEDManager.cpp` の `memset(CRGB[],…)` が FastLED 3.10 で曖昧呼び出しになり失敗。XIAO env は `kLedMaxPowerMa` 未定義で失敗 (いずれも本リポジトリで修正済み) |

**切り出しが成立する根拠**: 描画エンジンはフレームの供給元を知らない (トリプルバッファから読むだけ) ため、
「UDP 受信タスク」を「ローカルファイル読み出しタスク」に差し替えるだけで単独再生が成立する。
球面 UV マッピングと IMU 再投影は元々デバイス側で完結していた。

## 2. 採用した設計判断

- **供給元の差し替え**: `ImageManager::submitJpegFrame()` を入口とし、`SoloPlayer` タスクが LittleFS から
  読んだ JPEG を流す。描画・IMU・LED・球面マッピングは派生元のまま無変更。
- **動画形式 = raw MJPEG** (Baseline JPEG の連結、コンテナ無し)。AVI/multipart は受理しない。
  既存デコーダ (TJpg_Decoder) と同じ JPEG をそのまま使えるのが理由。
- **フレーム境界はマーカー追跡で判定** ([../src/JpegScan.h](../src/JpegScan.h))。`0xFFD9` の線形探索だと
  EXIF サムネイル (APP1) 内の EOI を誤検出するため、セグメント長を辿って SOI..EOI を確定させる。
  Arduino 非依存のヘッダオンリー実装にして PC 上で単体テストする。
- **10fps はファームウェア固定** (`kSoloFps`)。ファイル内の fps メタデータは参照しない。
- **締切管理は単調クロック** (`esp_timer_get_time`)。「デコード後に 100ms 待つ」方式ではなく締切を
  管理し、遅れた締切は捨てて次に揃える (処理時間によるドリフトと遅延の蓄積を避ける)。
- **1 フレーム上限 64KiB** (`kSoloMaxFrameBytes`)。ファイル内のサイズ値を無検証でメモリ確保に使わず、
  固定サイズの PSRAM バッファを使う。
- **UI はファームウェア埋め込み** (PROGMEM, 約 6KB)。LittleFS が壊れていても管理 UI を出して
  再アップロードできる。CDN・外部フォントには依存しない。
- **HTTP は ESP-IDF 同梱 `esp_http_server`、DNS は arduino-esp32 同梱 `DNSServer`** — 追加ライブラリ依存なし。
- **接続導線は QR + キャプティブポータル** (§6)。NFC は iOS が NFC 経由の Wi-Fi 参加に対応しないため不採用。
- **パーティション: OTA 2MB×2 + LittleFS 3.94MB** (§5)。OTA は削らず拡張し、派生元から存在した
  「ファームが OTA スロットに収まらない」問題も解消する。
- **アップロードは 一時ファイル → 全件検証 → rename**。容量が足りない場合のみ既存動画を先に削除し
  (UI に明記)、失敗時は「動画なし」で再アップロードできる状態にする。
- **server モード関連は削除** (MQTT 制御, UDP 映像受信, 時刻同期, リモートログ)。切り替えではなく
  削除にしたのは、単独動作に特化した独立リポジトリとして見通しを良くするため。server 構成が必要な
  場合は派生元リポジトリを使う。

### 削除したもの (派生元との差分)

| 削除 | 行数 | 理由 |
| --- | --- | --- |
| `MQTTManager.{h,cpp}`, `MqttTopics.h` | 421 | 外部ブローカーに依存しない。制御は HTTP API |
| `CommandHandler.{h,cpp}` | 602 | MQTT JSON コマンドの受け口。明るさ適用は `main.cpp` と Web API へ移動 |
| `TimeSync.{h,cpp}` | 154 | 複数球体の時刻同期ビーコン (server 前提) |
| `FrameReassembler.h` | 127 | UDP チャンク再構成 |
| `RemoteLog.{h,cpp}` | 161 | MQTT への tee ロガー → `Log.{h,cpp}` (Serial のみ, 14行) に置換 |
| `NetworkManager` の STA/UDP | — | SoftAP 専用に縮小 |
| `ImageManager` の UDP 経路 | — | `submitJpegFrame()` のみを入口に |
| `GestureManager` の MQTT 通知 | — | 検出結果は Serial ログへ |
| `server/` (Python + React), server 向けドキュメント・スクリプト | — | 本リポジトリの対象外 |
| `data/images/` (未参照の JPEG 200枚) | 1.2MB | ファームが読んでいなかった。LittleFS を動画に使う |

結果: ファーム 1,822,841 → **1,734,465 bytes** (約 88KB 減)、RAM 80,588 → **68,484 bytes** (約 12KB 減)、
LittleFS の同梱物 1.35MB → **39KB**。

## 3. アーキテクチャ

| 境界 | 実装 |
| --- | --- |
| ネットワーク | SoftAP (既定 `isolation-sphere` / 192.168.4.1、常時) + 任意の STA (NVS の LAN > config の P2P 網) + キャプティブ DNS |
| 映像入力 | `FramePump` (Core0、1 タスク) が UDP 配信 (`UdpReceiver` → `FrameReassembler`) とローカル `SoloPlayer::tick()` を調停 (`SourceArbiter`) し、`ImageManager::submitJpegFrame()` を呼ぶ唯一の場所。ローカル動画は open 時に **全体を PSRAM に読み込み**、再生中はフラッシュを読まない (§9 カクつき対策) |
| 制御入力 | `SoloWebServer` (esp_http_server) / `CommandHandler` (MQTT) / `SerialConsole` → いずれも `DeviceController` |
| 表示 | `LEDManager` レンダタスク (Core1) + IMU 再マッピング (`SphereMap.h`) |
| ログ | `sastle::Log` = `RemoteLog`: Serial + (server モードでは) MQTT `sphere/<id>/log` (PSRAM 退避 12KB) |
| 更新 | USB (`upload` / `uploadfs`) と OTA (espota: AP 192.168.4.1 / STA の IP) |

§10 に server モード (統合ファーム) の詳細。

### タスク配置

| タスク | Core | prio | stack | 役割 |
| --- | --- | --- | --- | --- |
| `LED_Render` | 1 | 2 | 8192 | IMU 再マッピング + RMT 出力 (~50-60Hz) |
| `imu` | 1 | 3 | 4096 | BNO055 100Hz 読み出し (Log を呼ばない。診断は loop が吐く) |
| `frame_pump` | 0 | 1 | 8192 | UDP キュー待ち (次のローカル締切まで) → 再構成 → デコード / 締切でローカル 1 フレーム。デコードは必ずここ |
| `async_udp` | 0 | — | — | AsyncUDP コールバック: データグラムを PSRAM キューへ (server モードのみ) |
| `httpd` | 0 | 2 | 8192 | Web UI / API / アップロード受信 (FS 書き込み) |
| `loopTask` | 1 | 1 | 8192 | OTA、STA 再接続、MQTT loop、ログ flush、DNS、設定保存/再起動、ジェスチャー、LCD、周期ログ・publish |
| WiFi/lwIP | 0 | 高 | — | SDK |

アップロード中 (FS 書き込み中) は再生を止める。フラッシュ書き込みはキャッシュ無効化で両コアに
影響するため、描画のちらつきが出る可能性がある (再生停止中なので実害は小さい)。

### 状態遷移 (SoloPlayer)

```
起動 ──有効な動画あり──▶ playing ──pause──▶ paused (表示は現在のフレームのまま)
  │                       │  ▲  ▲            │
  │                     stop │  └────play─────┘ (続きから)
  │                       ▼  │
  │                    stopped (LED 消灯。play で続きから)
  └─動画なし──▶ no_video (消灯)
  └─破損/解像度違い─▶ error (消灯)
アップロード開始 ─▶ uploading ─成功─▶ playing (先頭から)
                            └─失敗─▶ 旧動画があれば playing / 無ければ no_video
```

## 4. 動画形式と事前変換

受理条件 (アップロード時と起動時の両方で全フレーム検査):

- raw MJPEG: `FFD8 … FFD9` の Baseline JPEG (SOF0) を区切りなしで連結
- 全フレーム 320×160 (`config.json` の `image.width/height`)。他解像度は `resolution mismatch`
- progressive (SOF2) は `not a baseline JPEG` で拒否
- 1 フレーム ≤ 65536 bytes
- 途中で切れたファイル・末尾のゴミ・不正なマーカー構造は拒否 (部分ファイルは再生しない)

```bash
# 中央トリミングで 2:1 に合わせる (既定)。-q は 2(高画質)〜31(低画質)
tools/make_solo_video.sh input.mp4 video.mjpg -q 6
# 黒帯で収める / 先頭 30 秒だけ
tools/make_solo_video.sh input.mov video.mjpg --fit pad -t 30
```

MP4/MOV/HEVC を ESP32 上で変換する機能は無い (ESP32 では H.264 をデコードできない)。

### ブラウザ変換 (`docs/convert.html` → ファームに埋め込み `/convert`)

iPhone のカメラ動画を PC を介さずに変換するための単体ページ。**変換はすべて閲覧端末のブラウザ内**で
行われ、球体側の負荷はゼロ (ページを配信するだけ)。

```
Safari                                         ESP32
 <video> で H.264 デコード (HWデコーダ)          ← 負荷ゼロ
 canvas.drawImage() で 320×160 へ伸縮
 canvas.toBlob('image/jpeg') を Blob で連結
 POST /api/video ───────────────────────────▶  既存のアップロード経路 (変更不要)
```

`canvas` の JPEG 出力は Baseline (SOF0) なので `JpegScan` がそのまま受理する。APPn (JFIF/EXIF) は
マーカー長で読み飛ばされるため無害。**ファイルに fps 情報は入らない** (`SoloPlayer` は `kSoloFps=10`
固定で再生する) ので、「10fps にする」= 元動画のタイムラインを 100ms 刻みでサンプリングすることを指す。
30fps の全フレームを出力すると 3 倍のスローモーションになる。

| 項目 | 実装 |
| --- | --- |
| アスペクト比 | **2:1 への押し潰し固定** (元フレーム全体を 320×160 へ伸縮)。正距円筒として全周に貼るため、クロップやレターボックスより情報の欠落が無い方を採った |
| フレーム取り出し | `requestVideoFrameCallback` で `mediaTime` を見ながら 100ms スロットを埋める (2 倍速再生で実時間の半分)。取りこぼしたスロットは直前のフレームで埋めてフレーム数 = 再生時間を保つ。非対応ブラウザは 1 フレームずつシークする方式にフォールバック |
| サイズ見積り | 中央の 1 フレームを実際に符号化して 1f あたりのバイト数を測り、フレーム数を掛ける。`/api/status` が読めれば `fs.max_upload` と比較して変換前に警告する |
| 制限チェック | 1 フレーム 64KiB 超 / 総サイズが上限超のときは画質・長さの調整を促す |
| 出力 | `video.mjpg` を保存 / 共有。同一オリジン (球体が配信している場合) では `/api/video` へ直接アップロード |

**球体が `/convert` として配信する** (2026-09-22 実装)。AP 接続中の iPhone はインターネットに
出られないため外部サイトの変換ページを開けず、「iPhone の動画をそのまま入れたい」という要件は
同一オリジンでしか満たせない。正本は `docs/convert.html` (単体でもブラウザで開ける) で、
`python3 tools/embed_convert.py` が `src/ConvertPage.h` (PROGMEM) を生成する。**docs/convert.html を
編集したら必ず再生成すること**。埋め込みによるフラッシュ増は約 14KB (62.9% → 63.6%)。

**本体 UI にはファイル選択欄を置かない。** 動画の入れ替えは `/convert` への入口ボタン 1 つだけにし、
ファイルを選ぶのはそのページでの 1 回に統一した (本体 UI で選んでから変換ページへ遷移すると、
File オブジェクトは遷移で失われて選び直しになるため)。`/convert` は選ばれたファイルの先頭 3 バイトと
拡張子を見て、**すでに raw MJPEG なら変換を飛ばして直接アップロード**する。その際はブラウザ側で
全フレームを走査し、ファーム側の受理条件 (Baseline / 320×160 / 1 フレーム 64KiB 以下 / 末尾にゴミ無し)
を先に検査して、`corrupt JPEG structure` で弾かれる前に理由を表示する。
アップロードが成功したら結果を 1.2 秒表示して `/` へ戻る (球体は既に先頭から再生している)。
失敗時は理由を読めるようページに留まる。

容量の目安 (10fps)。LittleFS 3.94MB のうち同梱物は 39KB なので、動画に約 3.9MB 使える。

| 平均フレーム | 1 秒あたり | 再生できる長さ |
| --- | --- | --- |
| 5 KiB | 50 KiB | 約 78 秒 |
| 10 KiB | 100 KiB | 約 39 秒 |
| 20 KiB | 200 KiB | 約 19 秒 |

## 5. パーティションと容量

```
nvs       0x9000    0x4000
otadata   0xd000    0x2000
phy_init  0xf000    0x1000
ota_0     0x10000   0x200000   (2MB)
ota_1     0x210000  0x200000   (2MB)
spiffs    0x410000  0x3F0000   (3.94MB, LittleFS)
```

- OTA スロットを 2MB にした理由: §1 のとおり、派生元の時点で 1.72MB あり 1.5MB に収まらなかった。
  本リポジトリのビルドは 1,734,465 bytes = 2MB の 82.7% で、約 360KB の余裕がある。
- 8MB flash の未使用領域 (約 1.94MB) を OTA 増分 1MB と LittleFS 増分 0.94MB に配分した。
- アップロード上限 (`/api/status` の `fs.max_upload`) = 空き + 既存動画サイズ − 64KiB (LittleFS 余裕)。
- 一時ファイルと既存動画を同時に置けないサイズのときだけ、既存動画を先に削除して受信する
  (`replaced_before_upload: true`)。失敗すると `no_video` になり再アップロードできる。

### 書き込み手順

パーティション表は USB でしか更新できない (OTA では書き換わらない)。初回は必ず USB で書き込む。

```bash
pio run -e atoms3r -t upload      # ファーム + パーティション表 (USB)
pio run -e atoms3r -t uploadfs    # data/ を LittleFS へ (config.json, レイアウト CSV)
```

以後のファーム更新は `pio run -e atoms3r_ota -t upload` (先に PC を SoftAP へ接続)。

電源断: 一時ファイルへ書いてから rename するので、途中で切れても `/video.mjpg` は旧状態のまま。
`/video.tmp` が残った場合は次回アップロード時に削除される。マウント失敗時に勝手にフォーマットはしない。

## 6. 接続導線: QR とキャプティブポータル (NFC を採らなかった理由)

1. 端末が 1 台も繋がっていない間、本体 LCD に Wi-Fi 接続 QR
   (`WIFI:T:WPA;S:isolation-sphere;P:sphere-solo;;`) と SSID / URL を表示する
   (`LCDManager::drawWifiQr`、`sphere.features.LCD.debug = true` のとき)。
2. iPhone のカメラで読むと「ネットワーク “isolation-sphere” に接続」が出る → タップで接続。
3. 接続直後に iOS が `captive.apple.com/hotspot-detect.html` を取得しようとする。デバイスの DNS が
   全ホスト名を 192.168.4.1 に解決し、HTTP は `/api/` 以外の未知パスを `http://192.168.4.1/?cna=1`
   へ 302 で返すため、iOS は期待する "Success" を受け取れず **「ログイン」画面 (Captive Network
   Assistant) に Web UI を表示する**。Android (`/generate_204`) / Windows (`/connecttest.txt`) も同様。
4. 端末が接続されると LCD は映像 / STANDBY 表示に戻る。切断すると QR に戻る。

**既定ではキャプティブポータルを開かせない** (`solo.captive_portal = false`)。iOS の「ログイン」画面
(Captive Network Assistant) は簡易ブラウザで **`<input type=file>` のダイアログが出ず、動画を
アップロードできない** (実機で確認)。そのため OS の検出プローブには期待どおりの応答を返し、
利用者には最初から Safari で開いてもらう:

| プローブ | 応答 |
| --- | --- |
| iOS/macOS `/hotspot-detect.html`, `/library/test/success.html` | `<HTML>…<BODY>Success</BODY></HTML>` |
| Android `/generate_204`, `/gen_204` | 204 No Content |
| Windows `/connecttest.txt` / `/ncsi.txt` | `Microsoft Connect Test` / `Microsoft NCSI` |
| Firefox/NM `/success.txt` | `success` |
| 上記以外の未知パス | `http://192.168.4.1/?cna=1` へ 302 (利用者が何か入力した場合の救済) |

導線は **QR 2 枚**:

1. LCD の **Wi-Fi QR** (端末が未接続のとき表示) → カメラで読むと AP 参加を提案
2. 参加後、LCD が **UI の URL QR** (`http://192.168.4.1/`) に切り替わる → カメラで読むと **Safari** が開く
   (`SoloWebServer::uiServed()` が false の間だけ表示。UI を一度開いたら映像 / STANDBY へ戻る)

`tools/make_wifi_qr.py` はこの 2 枚を `docs/wifi_qr.png` / `docs/ui_qr.png` として出力するので、
LCD 非搭載機や印刷運用でも同じ導線が取れる。

`solo.captive_portal = true` にすると従来どおり接続と同時に UI が自動で開く (アップロードは
Safari で開き直す必要あり)。既定値はコード側 (`getSoloCaptivePortal()`) も false なので、
config.json を更新していない機体でも抑止側で動く。

### QR 画像の生成 (`tools/make_wifi_qr.py`)

印刷して本体に貼る / LCD 非搭載機 (XIAO ESP32S3) 向けに、`data/config.json` の `solo.ap` から
QR 画像を生成する。文字列の組み立て (エスケープ規則・パスワード 8 文字未満は `nopass`) は
`NetworkManager::wifiQrText()` と同一。

```bash
pip install segno            # cairosvg があればラベルの PNG も出る
python3 tools/make_wifi_qr.py
```

| 出力 | 内容 |
| --- | --- |
| `docs/wifi_qr.png` | 接続用 QR。`WIFI:T:WPA;S:isolation-sphere;P:sphere-solo;;` (33×33 モジュール, version 4) |
| `docs/ui_qr.png` | 接続後に開く `http://192.168.4.1/` の URL QR |
| `docs/wifi_qr_label.svg` / `.png` | QR + SSID / パスワード / URL を並べた印刷用ラベル |

生成した 3 つの画像は zxing-cpp でデコードして内容を確認済み。シリアルログにも
`[SOLO] Wi-Fi QR: WIFI:T:WPA;S:...;P:...;;` が出るので、任意の QR 生成ツールに入れてもよい。

### NFC について

- iPhone は **NFC タグから Wi-Fi に参加できない** (Android の Wi-Fi NDEF は iOS 非対応)。NFC でできるのは
  URL レコードを読んで Safari を開くことだけで、AP に繋がっていなければ `http://192.168.4.1/` は開けない。
- したがって NFC 単独では「接続 → UI」の導線が成立せず、QR (接続) + キャプティブポータル (UI 起動) を採用した。
- 接続後のショートカットとして、`http://192.168.4.1/` を書いた**受動 NFC タグ**を球体に貼るのは有効
  (ファーム変更不要、iPhone XS 以降は画面点灯中に近づけるだけで Safari が開く)。任意のオプション。

### OTA の経路: AP 経由と LAN (STA) 経由

AP 経由 (`atoms3r_ota` → 192.168.4.1) は、書き込む PC の Wi-Fi を球体の AP に繋ぎ替える必要があり、
その間 PC はインターネットから切れる。開発中はこれが煩雑なので **AP+STA 同時接続**を用意した。

- Web UI の「LAN 接続 (開発用 / 任意)」に普段の Wi-Fi の SSID / パスワードを入れて保存 → 再起動
- 球体は **AP を維持したまま** STA でも接続する (`WIFI_AP_STA`)。iPhone は従来どおり AP に繋がる
- PC は普段の LAN のまま `tools/ota.sh` (中身は `pio run -e atoms3r_lan_ota -t upload --upload-port <IP>`)
  で書き込める。mDNS 名は `<sphere id>.local` (既定 `sphere001.local`) だが PC 側で時々解決に失敗する
  (`getent` は通るのに espota が `Host Not Found`、実機 2026-09-23) ので、スクリプトが先に IP を解決して
  直指定する。解決できないときは `SPHERE_IP=<IP> tools/ota.sh` (IP は Web UI の「LAN (STA)」欄 /
  `/api/status` の `sta.ip`)。server モードでは P2P 網の固定 IP (例 192.168.49.101) を指定する

LAN の資格情報は **NVS に保存**する (`Preferences`, namespace `solo`)。config.json に書かないのは、
自宅 Wi-Fi のパスワードがリポジトリに混入するのを避けるため。SSID を空で保存すると無効化。
P2P 網 (配信 server) の SSID/パスワードは派生元と同じく config.json `wifi{}` に置く (固定値)。
優先順は **NVS > config.json** (利用者が変えた値が勝つ。明るさと同じ規則)。
`/api/status` に `sta:{enabled,connected,ssid,ip,origin}` (`origin` = `nvs|config|none`) が出る。
STA は起動時に先行して最大 2 秒待ち、AP を STA と同じチャンネルで立てる。相手 AP が居ないときは
5s→60s のバックオフで再接続する (autoReconnect の連続スキャンで SoftAP の応答が鈍るのを防ぐ)。

注意: ESP32 は AP と STA で無線を共有するため、**AP のチャンネルは STA 側に追従する**。
STA が 5GHz 専用 AP にしか繋がらない環境では使えない (ESP32-S3 は 2.4GHz のみ)。

## 7. HTTP API

| Method | Path | Body | 説明 |
| --- | --- | --- | --- |
| GET | `/` | — | Web UI (`?cna=1` でキャプティブ画面向けバナー。`uiServed` を立てる) |
| GET | `/convert` | — | 動画変換ページ (ブラウザ内で 320×160/10fps の raw MJPEG に変換し、そのまま `/api/video` へ) |
| GET | `/api/status` | — | 状態・動画情報・統計・容量・`ap` / `sta` / `server{configured,enabled,ssid,broker,mqtt}` / `source{mode,active,net_fps,udp_rx,reasm_drop,...}` / `led` / `imu` |
| POST | `/api/play` / `/api/pause` / `/api/stop` | — | ローカル再生 / 一時停止 (表示維持) / 停止 (消灯) (uploading 中・動画なしは 409)。配信中は表示は配信が握り、停止は配信終了後に効く |
| POST | `/api/led` | `{mode, pattern, width, axis}` | `mode`: sphere / test / off / pixels、`pattern`: strip / chase、`width` 1-60、`axis` bool |
| GET/POST | `/api/imu` | `{smooth_frames, i2c_khz, aux, word_read, reset, dump, reset_timing}` | IMU 診断と実行時スイッチ (`?dump=1` で生サンプル) |
| POST | `/api/source` | `{"mode":"auto|local|network"}` | 映像ソースの調停モード (再起動不要、保存しない) |
| POST | `/api/server` | `{"enabled":bool}` | config.json `wifi.enabled` を書き換えて保存し 0.8 秒後に再起動 (`"reboot":false` で保存のみ)。`wifi{}` が無ければ P2P 網の既定値で作る |
| POST | `/api/wifi` | `{ssid, password}` | STA (LAN) の資格情報を NVS に保存。空 SSID で無効化 (config の P2P 網に戻る)。反映は再起動後 |
| POST | `/api/brightness` | `{"value":0-100}` | 明るさ % (γ=2.2 で LED 値に変換。NVS に保存) |
| POST | `/api/video` | 動画本体 (`application/octet-stream`) | アップロード。成功 200 / 検証失敗 400 / 容量不足 507 / 競合 409 |
| POST | `/api/video/delete` | — | 動画削除 → `no_video` |
| POST | `/api/power` | `{ap, ap_idle_min, modem_sleep}` | 省電力 (指定したキーだけ反映)。`ap` bool (`false` は応答後に AP を止める。この接続も切れる)、`ap_idle_min` 0-1440 (NVS 保存、0=常時 ON)、`modem_sleep` bool (NVS 保存)。状態は `/api/status` の `power{ap_running,ap_idle_min,modem_sleep}` |
| POST | `/api/reboot` | — | 再起動 |
| * | `/api/` 以外の未知パス | — | `302 → http://<AP IP>/?cna=1` (キャプティブポータル検出用) |

```bash
curl -s http://192.168.4.1/api/status | jq .
curl -s -X POST --data-binary @video.mjpg -H 'Content-Type: application/octet-stream' http://192.168.4.1/api/video
curl -s -X POST -d '{"value":30}' http://192.168.4.1/api/brightness
```

## 8. 設定 (`data/config.json` と NVS)

役割分担: **config.json = 出荷時の既定値**、**NVS = 利用者が UI で変えた値**。起動時は NVS が
あればそちらを使い、無ければ config.json を読む。

| 項目 | 保存先 | 書き込み契機 |
| --- | --- | --- |
| 明るさ / XYZ 軸表示 / IMU 平滑 | NVS (`solo`/`bri`,`axis`,`smooth`) | Web UI・MQTT どちらから変えても、最後の変更から 3 秒後に 1 回 ([Settings.cpp](../src/Settings.cpp))。再起動要求時は即座に確定 |
| STA (LAN) の SSID / パスワード | NVS (`solo`/`sta_ssid`,`sta_pass`) | `/api/wifi` |
| server 接続の ON/OFF (`wifi.enabled`) | `config.json` (球体上) | `/api/server` / コンソール `server on|off` → `saveConfig()` → 再起動 |
| 解像度・AP・P2P 網・broker・調停・spheres[]・オープニング等 | `config.json` | `uploadfs` |

スライダーは操作中に値が連続で飛んでくるため、変更のたびに書くとフラッシュを無駄に消耗する。
`Settings::setBrightness()` は RAM を更新して保留にするだけで、`Settings::tick()` が最後の変更から
3 秒経ってから 1 回だけ書く。値が変わっていなければ書かない。



| キー | 既定 | 説明 |
| --- | --- | --- |
| `solo.video_path` | `/video.mjpg` | 再生する動画 |
| `solo.http_port` | `80` | Web UI のポート |
| `solo.ap.ssid` / `password` / `ip` | `isolation-sphere` / `sphere-solo` / `192.168.4.1` | SoftAP。パスフレーズが 8 文字未満ならオープン AP で起動し警告を出す (QR も `T:nopass`) |
| `wifi.mode` | `auto` | `auto` (STA 資格情報があれば AP+STA) / `ap` (STA を使わない。NVS も無視) / `ap_sta` |
| `wifi.enabled` | `true` | server 接続 (P2P 網 STA + MQTT + UDP) の ON/OFF。Web UI の「サーバ接続」が書き換える |
| `wifi.SSID` / `password` | `ESP32-P2P-Direct` / … | 配信 server の P2P 網 (派生元と同じ鍵名・値。Python server も同じファイルを読む) |
| `wifi.broker` / `mqtt_port` / `udp_port` | `192.168.49.1` / `1883` / `8889` | MQTT ブローカーと UDP 映像ポート。`broker` 空なら MQTT を使わない |
| `source.mode` | `auto` | 映像ソースの調停 (§10)。`local` / `network` で固定も可 |
| `source.idle_timeout_ms` | `2000` | 配信がこの時間途切れたらローカルへ戻す |
| `source.idle_blank` | `true` | 途切れ後にローカル再生が無ければ黒 (`false` = 最終フレーム保持) |
| `source.udp_queue_len` | `32` | UDP 受信キュー段数 (1 段 ≈ 1.5KB、PSRAM) |
| `telemetry.imu_hz` | `10` | MQTT `sphere/<id>/imu` の publish レート (0 で無効。接続中のみ) |
| `spheres[]` | sphere001/002 | MAC → 自機エントリ (id / static_ip / features)。旧形式の単一 `sphere{}` も受理。MAC 不一致なら空 mac の枠 → 先頭 (警告ログ) |
| `image.width` / `height` | `320` / `160` | 受理する解像度 |
| `params.brightness` | `50` | 起動時の明るさ [%] (γ=2.2 で LED 値へ。50% → 55/255) |
| `system.opening_action` | `enabled: true, 1200ms` | 起動時の LED オープニング |
| `system.debug` | `true` | `DEBUG_*` マクロのログ出力 |
| `sphere.features.LCD.debug` | `true` | LCD 表示 (QR / 映像 / STANDBY)。`false` で LCD 無効 |
| `sphere.features.IMU` | `BNO055` | IMU 種別 (ビルド env の `IMU_SENSOR_*` も参照) |

## 9. 検証状況

### ソース / ビルドで確認したこと

| コマンド | 結果 |
| --- | --- |
| `pio test -e native` | **42 ケース PASS** (IMU 4 スイート 22 ケースを派生元から移植)。JPEG 境界パーサー 13 ケース (完全フレーム、全プレフィックスで NeedMore、連結分割、APP1 内 EOI 非誤検出、非 SOI、progressive 判定、マーカー間ゴミ、SOS 前 EOI、SOI 入れ子、フィルバイト、長さ 0 セグメント、TEM/RSTn、null) + `MjpegAssembler` 7 ケース (復帰後のフレームが無傷: read 幅 1/3/64/700/2048/一括、先読みの温存、切れた末尾の破棄とループ、非ループ時の Eof/Truncated、TooLarge、空/ゴミ) |
| `pio run -e atoms3r` | **SUCCESS**。Flash 1,734,465 / 2,097,152 bytes (82.7%)、RAM 68,484 / 327,680 bytes (20.9%) |
| `pio run -e xiao_esp32s3` | **SUCCESS**。Flash 1,466,289 bytes (69.9%)、RAM 64,920 bytes (19.8%)。LCD 無しのため QR 表示は無効 |

### 実機で確認したこと (2026-09-22, AtomS3R, USB 給電)

書き込みは USB (`uploadfs` → `upload` の順。先に FS を 0x410000 へ置き、表とアプリを書いてから初回起動させる)。

| 項目 | 結果 |
| --- | --- |
| 起動 → 自動再生 → ループ | OK。`state=playing loops=2`、`tools/make_test_pattern.py` の 100 フレーム動画 |
| 100ms 締切 | **fps=10.0 miss=0**。`read=4-6ms` (LittleFS→PSRAM 2048B 追記読み) + `decode=62ms` (TJpgDec 320×160 4:2:0) = `tick=67-70ms`、余裕 約30ms |
| デコード | **decode_err=0** (下記の不具合修正後)。修正前は 100 フレーム中 87 が `JDR_FMT1` |
| LittleFS / config / SoftAP / OTA 受け口 / Web (port 80) | すべて起動。QR 文字列 `WIFI:T:WPA;S:isolation-sphere;P:sphere-solo;;` を出力 |
| メモリ | `heap_free≈205KB`、PSRAM 8MB 認識、`solo_play` スタック残 3.7KB / 6KB |
| IMU | `Scan done: 0 device(s)` — **AtomS3R を本体から外して試験したため** (BNO055 は本体側)。IMU 無しで続行できることの確認になった |
| LED 出力 | **`out=55-58ms` (render_fps 16.6)**。設計値 6-8ms に対し約 8 倍遅い。未解決 (下記) |

#### 実機で見つかった不具合: 先読みバイトによるフレーム上書き (修正済み)

症状: 再生は始まるが 100 フレーム中 87 が `drawJpg → JDR_FMT1` で落ち、失敗するフレームは毎ループ同一。
LED 出力を止めても、内部 RAM にコピーしても、PC で同じ `tjpgd.c` を走らせても再現せず、
LittleFS の読み出し自体 (PSRAM/内部 RAM、512-9496B の各チャンク幅) は全 233 チャンク一致。
デコーダに渡したバイト列の CRC32 をフレームごとに出して PC と照合したところ不一致で、frame0 の
壊れた 180..744 バイト目が **frame1 の同オフセットのバイト列と完全一致** (744 = 先読み量) した。

原因: `MjpegReader::next()` がフレーム確定時に先読み分をバッファ先頭へ `memmove` してから return
していた。呼び出し側 (`SoloPlayer`) がデコードする時点で、返したフレームの先頭が次フレームで
上書きされている。先頭 180 バイトが無事に見えたのは SOI/APP0/DQT が隣接フレームと同一だったため。
先読み量が小さいフレームだけ生き残る = 決定的なパターン。

修正: 先読みの寄せを **次回 `next()` 呼び出しの冒頭**に遅延 (`_consumed`)。バッファ管理を Arduino
非依存の [`src/MjpegAssembler.h`](../src/MjpegAssembler.h) に切り出し、`MjpegReader::next()` と
`validate()` の両方がこれを使う。`test/test_mjpeg_assembler` が「復帰後のフレームが無傷」を
read 幅ごとに検証する (PC でこの呼び出し順を再現すると修正前は 87/100 が実機と同一パターンで失敗、
修正後は 0/100)。

#### 実機で見つかった不具合: IMU 姿勢のジャンプ → 派生元 feat/ui-v2 の IMU スタックを移植

症状: 球体を回すと姿勢が数十度飛んで往復する。静止中は起きない。派生元 core (server あり) でも
同じ症状があり、**`feat/ui-v2` ブランチで 2026-09-09 に解決済み**だった (solo は `main` から切り出した
ため未反映)。経緯は派生元 `docs/HANDOFF_2026-09-09_imu_jump.md`。

solo 側でも 100Hz 生ダンプ (`/api/imu`) で独立に同じ原因に到達した:

```
t=149531  w=14807 x=-6576 y=-2437 z=    3   ← 正常
t=149553  w=14808 x=-6577 y= -126 z=   -1   ← y の上位バイトが 0xFF、z が 0xFFFF
t=149604  w=14810 x=-6574 y= -123 z=   -1   ← 4 サンプル (約 75ms) 連続で化けたまま
t=149627  w=14809 x=-6572 y=-2437 z=    4   ← 戻る → 見た目は ±16° の往復
t=158010  w=14775 x=   -1 y=   -1 z=   -1   ← 2 バイト目以降が全部 0xFF (|q|^2=0.813)
```

- BNO055 の多バイト I2C 読みで**上位バイトだけが 0xFF になる** (下位は真値)。`requestFrom` は要求
  バイト数を返すのでトランスポートは成功扱い (`fails=0`)。中身で弾かないと通る
- 潰れた成分の真値が |v|=0.2〜0.38 だと |q|^2 が 0.85〜0.98 で緩いノルム窓を通過し、いったん受理
  されると連続性ガードが**以後の真値を棄却し続ける** → 真値 ⇄ 化け値の往復 = 高周波ジャンプ
- 連続性ガードの gyro を deg/s のまま rad/s として使っていた (約 57 倍ゆるく、回転中は無効)
- 副次: 8B バースト読み (~5ms) が 10ms の融合更新境界をまたぐ (回転中の約 45%)

対策 = 派生元の実装をそのまま移植 (`src/imu/*`, `IMUManager{,_bno055,_m5imu}.cpp`, `PeriodicTimer.h`):

| 部品 | 内容 |
| --- | --- |
| `Bno055QuatReader` | quat を **2B×4 の分割読み**。MSB が 0xFF/0x00 のワードは前回受理値から 800 LSB 以内でなければ部分読みとして読み直し (最大 3 回)。x,y,z の後に **w を再読みして一致を要求** (融合境界跨ぎの検出 = `straddle`) |
| `Bno055Codec` | LE デコード / MSB 欠落判定 / 全ゼロ・末尾埋め検出 |
| `AttitudeValidator` | ノルム窓 0.85〜1.15 + 連続性ガード (gyro は rad/s) + 強制受理 |
| `QuatSmoother` | 符号合わせ付き移動平均 (`imu.smooth_frames`、既定 10。`/api/imu {smooth_frames}` で変更、NVS に保存) |
| `ImuDiag` | 累計カウンタ (`fail/disc/zero/partial/straddle`)、IMU タスク → loop の診断スナップショット、`imu_dump` リング |
| `I2cLock` | I2C は IMU タスクだけが触る |
| 専用タスク `IMU_Poll` | core1 優先度 3 で 100Hz 固定。棄却率 50% 超が 4 秒続けば BNO055 を自動再初期化 (15 秒クールダウン)。`Wire.setTimeOut(20)` |

solo 固有の追加:
- `IMUManager_bno055::begin()` に `Wire.setClock(_i2cHz)` を追加。`main.cpp` の `scanI2cBus()` が先に
  `Wire.begin` しており、**`Wire.begin` は 2 回目以降は周波数を再設定しない**ため、IMUManager の
  100kHz 指定が無視されて 400kHz のまま動いていた (実機で `Wire.getClock()` を出して確定)。
  走査自体も 100kHz にした
- `/api/imu` GET: カウンタ / cal / mode / quat / i2c / smooth。`?dump=1` で imu_dump の生サンプルを返す。
  POST: `{smooth_frames, reset, i2c_khz (50-400), aux, word_read, dump (<=2000)}`
- UI の IMU カードに partial/straddle、平滑スライダー、再初期化ボタン
- `[RATE]` ログを派生元書式に (zero/partial/straddle/i2c/word/smooth/seq)。診断スナップショットは
  loop 側で吐く (IMU タスクは Log を呼ばない)
- native テストを移植: `test_bno_codec` / `test_attitude_validator` / `test_quat_smoother` / `test_imu_diag`
  (`test/mocks/Arduino.h`、`-std=c++14`)。**合計 42 ケース PASS**

移植前に solo 側で見つけた別の原因: IMU を `loopTask` から読んでいたため、LCD の QR 再描画 (`c.qrcode`
約 70ms、500ms 周期) と 2 秒周期のログで**読み出し周期が中央値 22ms・最大 240ms** に乱れていた
(100Hz 設計)。読めない間は描画が古い姿勢のまま止まり、次に読めた瞬間に追いつく = これもジャンプに見える。
IMU 専用タスクで解消。QR は文字列が変わったときだけ生成するようにした。

派生元の未解決事項 (引き継ぎ): `_recoverI2cBus()` は無効化中 (有効にした起動で BNO055 未検出)、
`readVector6` (accel/gyro/euler) に MSB 欠落判定が無い (euler が化けるのを観測、GestureManager が使う)、
`atoms3r_m5imu` env はリンクしない (QUARANTINED)。

実機確認 (2026-09-23, 本体に組み込み LiPo、OTA 後):

| 条件 | 読み出し | fail | disc | partial | straddle | 受理姿勢の飛び (15° 超) |
| --- | --- | --- | --- | --- | --- | --- |
| 静止 25 秒, I2C 100kHz | 39.8/s | 0 | 0 | **16.6/s** | 1.0/s | 0 回 (最大 1.8°) |
| 静止 20 秒, I2C 400kHz (実行時切替) | 47.6/s | 0 | 0 | 0.1/s | 0.8/s | 0 回 |
| 静止 20 秒, I2C 100kHz に戻す | 41.3/s | 0 | 0 | 0 | 0.3/s | 0 回 |

- **化けは静止中でも 17% の頻度で起きており、全件を検出して読み直し、姿勢には出ていない**
  (disc 0 / 飛び 0)。移植前は同条件で受理姿勢の飛びが 90 秒に 16 回出ていた
- 読み出しレートは **約 40〜48/s** で設計 100Hz に届かない。I2C クロックを 400kHz にしても +15% なので
  クロックではなくトランザクション数 (2B 分割読み: quat 4 + w 再読み 1 + 補助 1 ベクタ = 約 8 回/周期、
  Wire の 1 トランザクション約 2ms) が律速。派生元が 90〜100/s だったのは、走査の 400kHz が
  `Wire.begin` で上書きされず実質 400kHz だったため。描画 (約 49fps) に対しては毎フレーム更新に近く、
  体感上は問題にならない見込み。平滑 10 フレームは 45Hz では約 220ms の遅れになるので、
  遅れが気になれば `/api/imu {smooth_frames: 5}` 程度に下げる
- 100kHz と 400kHz で化け率 (partial) は 16.6/s → 0.1/s と大きく違った。ただし静止 20 秒の単発比較で、
  100kHz に戻した直後は 0/s だったので、時間変動 (電源・温度) の可能性がある。既定は 100kHz のまま、
  `/api/imu {i2c_khz}` で切り替えて様子を見る
- 回転中の生ダンプ (100kHz、856 サンプル): 受理 766 / 読み失敗 81 / 棄却 9。**読み失敗 81 件のうち 80 件は
  |q|²=1.000 の正常値**で、受理間の 15° 超の飛び 12 件のうち 11 件は「間に 1〜17 回の読み失敗を挟んだ」
  もの (角速度換算 116〜376°/s = 手の回転そのもの)。つまり残っていたジャンプは化けの素通りではなく、
  **正常値の誤棄却 → 姿勢保持 → 追いつき**。原因は (1) w 再読みの bit 一致要求 (回転中は 416/856 サンプル
  で再読みが走る)、(2) MSB 欠落判定の 800 LSB が、読み失敗で prevAccepted が古くなると本物の小さい値を
  弾く。→ solo 側で改良: w 再読みは差分 600 LSB 以内なら同一サンプル扱い (`wordsDisagree`)、MSB 欠落の
  許容幅は前回受理からの経過時間で 400°/s 相当に伸ばす (`partialToleranceLsb`、上限 4000)。
  native テストを追加 (test_bno_codec)
- 400kHz にすると化けの出方が変わり、**下位ワードが 0x00 で埋まる** (`c4 32 00 00 00 00 00 00`) 形で
  静止中でも 14% のサイクルが読み失敗する (100kHz では読み直しで全件回復、失敗 0)。既定は 100kHz。
  派生元が実質 400kHz で 90〜100/s 出ていたのは、この失敗を「読み失敗 → 前回値保持」で吸収していたため
- 利用者評価 (平滑 3): 「時々ジャンプが発生するが、かなり改善している」
- 許容幅改良版の回転ダンプ (ダンプ B: 1928 サンプル、うち 1351 区間が回転中): **読み失敗 0 / 誤棄却 0 /
  straddle 再読み 2** (改良前 81 / 80 / 496)。正常値を捨てて止まる問題は解消。
  残った受理間 15° 超は 15 件で性質が変わった: 間に欠落なし・dt≈24ms・角速度換算 700〜1165°/s
  (手の回転は中央値 190°/s)。前後の生値を見ると**飛びの「直前」の受理値が全て化け**
  (x=-76〜-404 = 0xFFxx、n²=0.979〜0.994) で、真値 (x≈-2500) に戻る瞬間が飛びとして見えていた。
  MSB 欠落の差分判定を経過時間で伸ばしたことで、読み出しが遅れた周期 (40〜100ms) に |v|≈0.15 の
  成分の化け (Δ≈2300 LSB) が通るようになっていた
- 対策 (再修正): (1) 組み立てた 8 バイトの**ノルム² を読み出し試行内で検査** (1±0.02 を外れたら
  同じ周期で読み直す、`quatNormImplausible`)。健全な出力は 0.999〜1.000 に張り付くのでワード差分とは
  独立に化けを捕まえられる。(2) 差分判定の許容幅の上限を 4000 → 2000 LSB。(3) `AttitudeValidator` の
  ノルム窓を 0.85〜1.15 → 0.97〜1.03 (派生元の「0.92〜0.98 を常用」は化け値込みの観測だった)。
  しきい値はダンプ B の実測から決めた: **健全値の最大ずれ |n²-1|=0.0072、化けの最小ずれ 0.019** なので
  読み直し判定は 0.015
- 再確認 (静止 20 秒): 読み出し 39.8/s、**fail 0 / disc 0 / partial 0 / straddle 0**、姿勢の飛び 0。
  読み直しが 0 になったのは、ノルム検査が同じ周期内で化けを捕まえて再読みし、成功しているため
  (partial は「弾いた回数」なので、弾く前に読めていれば増えない)
- 利用者評価 (平滑 3、ノルム検査あり): 「かなり向上した。ジャンプもたまにあるが、気にならない程度に
  収まり始めている」

#### 読み出しレート 40/s の原因: IMU タスクが起動していなかった

I2C クロックを 100/200/300/400kHz で A/B しても 40 → 46/s しか変わらず (fail/partial は全て 0)、
クロックは律速ではなかった。`/api/imu` に `task_running` と周期の内訳 (`cycle_us` / `upd_us` /
`quat_us`) を出して確認したところ **`task_running=false`**: `ota.begin()` を SoftAP 直後へ前倒しした
とき、`startTask()` の呼び出しをその直前 (= IMU 初期化より前) に置いてしまい、`isInitialized()` が
false で一度も起動していなかった。40/s は loop ポーリングのフォールバックが LCD 再描画などに
削られた値。`startTask()` を setup 末尾へ移して解消:

```
task_running=True   受理 100.5/s  読み 100.5/s   fail 0 / disc 0 / partial 0 / straddle 0
1 周期 10.00 ms = _updateOnce 6.03 ms (quat 4 ワード + w 再読み 4.60 ms、aux 1.44 ms) + 待ち 3.96 ms
```

I2C 100kHz のまま設計値 100Hz に到達。1 周期に 4ms の余裕があるので 100kHz を既定に維持する
(400kHz は 0x00 埋めの化けが増える)。平滑 3 フレームの遅れは 30ms。

**利用者評価 (100Hz 到達後): 「平滑 1 でもジャンプはない」** — 移動平均なしで姿勢追従が滑らかになった。
平滑は化け対策ではなく好みの範囲で使うもの (config.json の既定 10 は派生元の値。solo では
1〜3 で十分)。IMU ジャンプの件はここで解決とする。

#### 未解決: LED 出力 55-58ms

FastLED 3.10.5 の RMT4 ドライバ (IDF 4.4)。ESP32-S3 の RMT TX チャンネルは 4 本
(`SOC_RMT_TX_CANDIDATES_PER_GROUP=4`) で、AtomS3R の 5 ストリップ目は「時分割」で後回しになる。
完了検出はポーリング + 1ms スライス (`ChannelManager::waitForPollNeededSignal`)。それでも 58ms の
説明には足りない。**試して外れたもの**: FastLED の実行時ログ無効化 (`FASTLED_LOG_VERBOSITY=0`、
`out=53-56ms` で変化なし。フラッシュ削減のため設定は残した)。残る切り分け候補は
(a) `-D BOARD_NUM_STRIPS=4` で 4 ストリップ構成にして `out=` を計測 (時分割の影響を確定)、
(b) `FASTLED_RMT_MEM_BLOCKS` 増加、(c) S3 の I2S/LCD_CAM 並列ドライバへの切替。映像 10fps の表示自体は間に合っており、
影響は IMU 姿勢追従の滑らかさ (設計 50-60Hz → 実測 16.6Hz)。

#### 本体に組み込んで LiPo 起動: 起動音 → 全 LED 白点灯 → 電源断 (対処中)

上表の実機確認はすべて **AtomS3R を本体から外して USB 単体**で行ったもの (LED 800 個と BNO055 は
本体側)。本体に戻して LiPo で起動すると、起動音の直後に全 LED が白点灯し電源が落ちた。
起動順序は `earlyBlank()` (全ストリップに黒を送信) → Serial → 起動音 → 2 秒待ち、なので、
**黒を送ったはずの `earlyBlank()` が LED に白として受け取られている** (データ線のタイミング逸脱で
0 ビットが 1 に読まれる) と見ている。

同じ 3.10.5 ビルドで、本体に組み込んだまま USB 給電で起動したときは**全 LED が暗い赤**で点灯した
(電源電圧の違いで LED 側の閾値が変わったと見れば、白と同じ「黒データが別の値に読まれる」症状)。

以前動いていた core ビルドとの差は FastLED の版。指定は同じ `^3.7.8` だが現在は **3.10.5** に解決され、
ESP32 の RMT ドライバが ChannelManager 実装 (S3 の TX 4 チャンネルに 5 ストリップを時分割) に
置き換わっている。core の現行ソースが 3.10 ではビルドできない (`memset` 曖昧呼び出し) ことから、
以前の書き込みは 3.10 より前の版。ベンチの LED 出力 55ms (設計値 6-8ms) も同じ差の症状と考えられる。

対処: `platformio.ini` で **FastLED を 3.7.8 に固定** (元プロジェクトが `^3.7.8` を宣言した時点の版 =
球体が動いていた実績のある版)。この版でのビルドは Flash **1,307,717 bytes** (3.10.5 では 1,721,757、
3.9.20 では 1,329,397) と約 414KB 小さく、**旧 1.5MB スロットにも収まる**。今日の表変更の前提
「ファームが 1.5MB に入らない」は 3.10 系の RMT 実装が原因だった。
3.7.8 に下げたところ、ベンチで起動直後に **`Guru Meditation Error: Core 1 panic'ed (Cache disabled but
cached memory region accessed)`** のリブートループになった。バックトレース:
`ESP32RMTController::interruptHandler → doneOnChannel → startNext → rmt_set_tx_thr_intr_en` (Core1 の
RMT 割り込みがフラッシュ上の IDF 関数を呼ぶ) と、同時刻の Core0 `SoloPlayer::begin → validate →
File::read → esp_flash_read` (キャッシュ無効化)。以前の core は映像を UDP で受けていてフラッシュを
読み続けなかったため踏まなかった。**solo が LittleFS を 10fps で読む構成では必ず起きる**。
対策として `-D FASTLED_ESP32_FLASH_LOCK=1` (show() の間 `spi_flash_op_lock()`) を両 env に追加。
3.10.5 では起きなかった (新実装は ISR を IRAM に置き、二重バッファで WiFi 干渉耐性を持つ) ので、
「白点灯」と「フラッシュ競合」は版のトレードオフになっている。

ベンチ計測 (3.7.8 + `FASTLED_ESP32_FLASH_LOCK=1`, LED 未接続):

| 項目 | 3.10.5 | 3.7.8 + FLASH_LOCK |
| --- | --- | --- |
| LED 出力 `out=` | 53-58ms | **15.2ms** |
| `render_fps` | 16.6 | **48.8-49.0** (設計値 50-60Hz にほぼ到達) |
| LittleFS 読み出し `read=` | 4-6ms | 10-20ms (show() 中はフラッシュロックで待たされる) |
| `tick=` (read + decode) | 67-70ms | 68-82ms (100ms 締切に対し余裕 約18ms) |
| 再生 / デコード | fps=10.0 miss=0 err=0 | fps=10.0 miss=0 err=0 |
| パニック | なし | なし (FLASH_LOCK 無しではリブートループ) |

`read=` の増加はロック待ちによるもので、締切内に収まっている。余裕が欲しくなったら
`kReadChunk` を大きくして read 回数を減らすか、デコードを先に走らせる順序に変える。
**本体に組み込んで LiPo 起動: 全白は出なくなった** (2026-09-22 夜、ユーザー確認)。
FastLED 3.10.5 の RMT 実装が原因だったと確定。

追加の実機フィードバックと対応:
- 停止しても最後のフレームが LED に残る → `ImageManager::publishBlack()` を追加し、`stop()` /
  動画クローズ (削除→no_video) / エラー時に全画素 0 のフレームを公開して消灯する。
  描画タスクは公開済みフレームを再マッピングし続ける設計なので、黒フレームを流すのが最小の変更。
- Web UI からファイルをアップロードできない → `<input type=file>` の `accept=".mjpg,…"` を撤去。
  iOS は accept に未知の拡張子があると「ファイル」アプリで該当ファイルがグレーアウトして選べない。
  形式検証はサーバ側 (validate) が行うので accept は不要。

FastLED を使わない選択肢: NeoPixelBus の S3 LCD_CAM 並列 (`NeoEsp32LcdX8Ws2812xMethod`, 8 本まで
真の並列) が本命。LEDManager の出力部差し替えと、色計算・電流制限の自前化が必要。
姿勢追従を設計値 50-60Hz で回す必要が出たときに検討する。

#### 起動経路の変更 (組み立て後の復旧手段を確保)

起動直後の `delay(2000)` (シリアルモニタ接続待ち) は、USB ホストが繋がっているとき
(`Serial.isConnected()`, HWCDC) だけ 300ms 待つように変更。電池駆動では待たない。

LittleFS マウント失敗・`config.json` 読み込み失敗で `while(1)` 停止していた箇所を撤去し、
ConfigManager のコンパイル時既定値で続行する。`ota.begin()` を SoftAP 直後に前倒しし、以降の初期化
(IMU / LED / 再生 / Web) が止まっても無線の書き戻しが生き残るようにした
(USB 端子に触れない筐体で、閉じた後に文鎮化する経路を潰す)。

### 実機で確認したこと (2026-09-23, 統合ファーム Phase 0〜5 + カクつき対策, LAN 経由 OTA)

利用者の実動画 (3.0MB / 565 フレーム / 平均 5KB/f) で「カクつく・時々止まる」が出た。`/api/status` に
描画・デコード統計を足して切り分けた結果と対策:

| 指標 | 旧 solo ファーム | 統合 (対策前) | 統合 (対策後) |
| --- | --- | --- | --- |
| 再生 fps / 締切落ち (静穏) | 7.2 / 9.6% | 7〜10 / 13% | **10.0 / 0%** |
| 締切落ち (0.5s 間隔で /api/status を叩く) | — | 37% | **0%** |
| LED 出力 1 回 (`render.out_us`) | 55ms (§9 既知) | 11ms | 10.5ms |
| 描画 fps | ~17 | 25〜47 | 50 |
| デコード 1 枚 (`img.decode_us`) | 55ms | 44〜411ms | 52〜64ms |

- **原因 1: `/api/status` がフラッシュを読んでいた**。`LittleFS.usedBytes()` は全ブロック走査、
  `LittleFS.open()` も読む。`spi_flash_read` は 1 回ごとに両コアのキャッシュを止めるので、httpd
  (Core0, 当時 prio 2 > 再生 prio 1) がデコードを引き延ばし、Core1 の描画も止めていた。Web UI は
  2 秒ごとに叩くため「UI を開いているとカクつく」。ポーリング間隔と締切落ちに用量反応があった
  (静穏 13% → 0.5s 間隔 37%) ので因果は確定。対策: 使用量は起動時・アップロード/削除の前後だけ
  再計算してキャッシュ、動画サイズは player の値を使う
- **原因 2: 再生自体のフラッシュ読み** (`read_us` 最大 19ms = LED 出力中のフラッシュ操作ロック待ち)。
  対策: open 時に動画全体を PSRAM に読み込む (`MjpegReader::openMemory`、3MB で 1.3 秒 = 2.2MB/s)。
  再生中はフラッシュに一切触らない。PSRAM 確保に失敗したときだけ従来のフラッシュ直読みに退避
- 併せて frame_pump を prio 2、httpd を prio 1 にして、状態表示やアップロード受信がデコードを奪わないようにした
- `FASTLED_RMT_MEM_BLOCKS=1` で LED 出力は 55ms → 10.5ms (派生元の実測どおり)。§9 冒頭の「55-58ms
  で原因不明」は解消。描画 50fps、IMU 追従も 50Hz に上がった
- 残りの余裕: デコード 52〜64ms は本来の値 (TJpg_Decoder `JD_FASTDECODE=1`)。100ms 締切に対し
  35〜45ms の余裕。さらに縮めるなら `JD_FASTDECODE=2` (ライブラリを `lib/` に同梱して設定変更、
  内部 RAM +6KB) か、数フレーム先にデコードしておくリングが次の手

### 実機で未確認のこと (次にやる実機チェック)

1. ~~起動と自動再生~~ → 確認済み (上表)
2. ~~締切~~ → 確認済み (上表)。ただし球体本来の電源での再確認が未了 (USB 給電で計測)
3. ~~姿勢追従~~ → 確認済み。本体に組み込んだ状態で 100Hz、平滑 1 でジャンプなし (上記)
4. **QR と自動起動**: LCD の QR を iPhone のカメラで読めるか (照度・サイズ)。接続後に「ログイン」画面が
   自動で開くか。接続すると LCD が映像 / STANDBY に戻るか
5. **iPhone Safari**: UI 表示 → アップロード進捗 → 完了後に先頭から再生 → 切断後も再生継続
6. **異常系**: 途中切れ / 解像度違い / progressive / 過大フレーム / 容量不足 / 送信中断 →
   `/video.mjpg` が壊れず、UI が理由を表示して再アップロードできる
7. **電源断**: アップロード中に電源を切る → 再起動後、旧動画が再生される (または `no_video`)。
   `/video.tmp` が残っていても次回アップロードで消える
8. **メモリ**: `/api/status` の `heap_free` / `psram_free` と各タスクのスタック余裕
   (`uxTaskGetStackHighWaterMark`) を記録する
9. **OTA**: パーティション変更後、USB で 1 回書いた機体に対して `atoms3r_ota` で更新できること
10. **ブラウザ変換** (`docs/convert.html`): iPhone Safari で `requestVideoFrameCallback` が動くか
    (非対応ならシーク方式に落ちる)。変換所要時間・1f あたりのバイト数・生成した `.mjpg` が
    アップロード検証を通るか。`<input type=file>` から camera roll の動画を選べるか
11. **統合ファーム (§10)**: 2026-09-23 の Phase 0〜5 はビルドと native テストのみで、**実機は未確認**。
    §10 の検証手順を順に実施する (solo 退行 → UDP 配信 → MQTT → OTA)

12. **省電力 (未確認)**: 2026-10-05 にビルドと native テストのみ。実機で、AP 自動停止後の再開 (シェイク /
    シリアル / MQTT) と OTA (`192.168.4.1`) が使えること、トリプルシェイクの感度 (誤検出・取りこぼし)、
    AP 停止/稼働別の消費電流を実測する

### 既知の制約

- 音声・シーク・複数動画・プレイリスト・サムネイルは無い (要件どおり)
- ~~LED 出力が 1 フレーム 55-58ms かかる~~ → `FASTLED_RMT_MEM_BLOCKS=1` で 10.5ms に解消 (2026-09-23 実測)。描画 50fps
- 動画は open 時に全体を PSRAM に読み込む (最大 3.9MB)。アップロード直後・起動直後に数秒の読み込み時間がある
- 本体に組み込んだ状態では **USB 給電で映像を再生できない** (LED 800 個の電流に足りず、起動直後の
  オープニングや再生開始で電圧が落ち USB が切れる)。書き込みは USB で可、動作確認は LiPo で行う
- ESP32 上で動画を変換する機能は無い。PC なら `tools/make_solo_video.sh`、iPhone 単体なら
  `docs/convert.html` (ブラウザ内変換、実機未確認)
- 明るさは NVS に保存され再起動後も復元される (§8)。config.json の値は「まだ一度も変えていないとき」の既定値
- QR 表示は LCD 搭載機 (AtomS3R) かつ `LCD.debug = true` のときのみ
- iOS の「ログイン」画面 (CNA) ではファイル選択ダイアログが出ない → 既定でキャプティブポータルを抑止し、LCD の URL QR から Safari で開く導線にした (§6)
- `TJpg_Decoder` はグローバル単一インスタンスのため、デコードを複数タスクから同時に呼べない
  → 配信・ローカルとも `FramePump` の 1 タスクが順番にデコードする (§10)
- LED 出力モード `Manual` は `mode: off / pixels` (Web UI `/api/led`、MQTT `led`) から使う。
  `pixels` の一括更新は MQTT 2KB の制約で ~50 LED/メッセージ (全球は UDP 映像経路で)

## 10. server モード (統合ファーム: server あり / なし を 1 バイナリで)

2026-09-23 に派生元 `feat/ui-v2` の server 系モジュール (MQTT / UDP 映像) を本リポジトリへ移植し、
solo と server を **同じファーム**で動かすようにした。計画: `~/.claude/plans/server-expressive-parnas.md`。
**実機確認は未了** (ビルドと native テスト 67 件のみ)。

### 方針

- 本リポジトリが superset。派生元 `core/` は凍結し、Python server はそのまま使う (プロトコル凍結:
  UDP 16B ヘッダ magic `0x4A504547` / 1400B チャンク / ≤46 チャンク、MQTT `sphere/<id>/...`、
  retained `state` ≤768B)
- デコードは `FramePump` の 1 タスクだけ。配信 (UDP) とローカル (MJPEG) を同じタスクが順番に処理する
- 調停は `auto`: 配信の完成フレームが `idle_timeout_ms` 以内に届いていれば配信を表示、途切れたら
  ローカルへ (Playing なら続きから、そうでなければ黒)。`local` は配信を読み捨て、`network` はローカルを止める
- 制御面 (Web UI / MQTT / コンソール) は `DeviceController` 1 つを呼ぶ。明るさは両方 γ=2.2、
  変更はどこから来ても NVS に保存
- AP は常時 (iPhone)。STA は NVS の LAN > config の P2P 網 (固定 IP は `spheres[].static_ip`)
- server モードの ON/OFF は config.json `wifi.enabled`。**Web UI の「サーバ接続」/ コンソール
  `server on|off` が球体上の config.json を書き換えて再起動**する (OTA では LittleFS を更新できない)。
  `wifi{}` が無い旧 config には P2P 網の既定値を書き込む

### 起動順と挙動

1. `Log.begin()` (PSRAM 退避) → FS → config (spheres[] を MAC で解決、警告あり) → Settings (NVS)
2. `NetworkManager::begin`: STA 先行 (≤2s) → SoftAP を同じチャンネルで
3. OTA (hostname = sphere id) → IMU → ImageManager → **FramePump 起動 → UDP listen** (server 設定時)
4. LED → `DeviceController::begin` (明るさ/軸を適用) → SoloPlayer (ファイルを開く、タスクは持たない)
   → Web UI → **MQTT** (最後。server は status/state を見た瞬間に配信を始めるため受け側を先に作る)
   → IMU タスク
5. loop: OTA → STA poll (バックオフ再接続) → `mqtt.loop` (STA 接続後に接続。切断時 5s 毎) →
   `Log.loop` (退避ログを 3 行/周) → DNS → 設定保存/再起動 → コンソール → LCD → ジェスチャー →
   周期ログ → imu (10Hz) / state (5s retained) publish

配信中の操作: `stop` / `pause` はローカル再生の状態だけ変える (黒要求は配信が表示を握っている間は
保留され、配信終了 + idle_timeout 後に効く)。Playing のままなら配信終了後に続きから再開。

MQTT: 受信 `sphere/<id>/command/#`、`sphere/all/command/#`、`sphere/all/clock` (TimeSync)。送信
`status` (online, retained)、`state` (5s, retained)、`imu` (10Hz)、`log` (RemoteLog)、`gesture` / `ui_mode`。
`led.source` (local/network/none) を `state.led` に追加した (server は未知キーを無視する)。

### メモリ (ビルド実測、atoms3r)

| | Phase 0 (solo のみ) | Phase 5 (統合) |
| --- | --- | --- |
| Flash (2MB スロット) | 1,366,793 B (65.2%) | 1,487,237 B (70.9%) |
| 静的 RAM | 62,712 B | 72,296 B (+9.6KB: UDP 作業領域 3KB、MQTT 退避 2KB、CommandHandler 2KB、Telemetry state 0.8KB ほか) |
| ヒープ (見積) | 空き ~205KB | −8KB (frame_pump) +6KB (solo_play 廃止) −~12KB (async_udp / PubSubClient 2KB / TCP) → ~190KB。UDP キュー 48KB と Log 退避 12KB は PSRAM |
| PSRAM | ~7.6MB 空き | −64KB 再構成 −48KB キュー −12KB 退避 |

### 実機検証手順 (未実施)

1. **solo 退行なし** (`wifi.enabled=false` または旧 config): ~~起動、再生 fps=10 miss=0、OTA (LAN)~~ →
   確認済み (2026-09-23、§9 の表)。残り: QR、停止で黒、一時停止、アップロード (PSRAM 再読み込み)、
   明るさ (見た目が暗くなる: γ2.2)、OTA (AP 経由)、`[QDIAG]` の ortho/norm が 0 付近
2. **UDP 配信のみ** (server 不要): NVS の LAN に接続した状態で PC から
   `python3 tools/stream_to_sphere.py --target <STA IP> --fps 15` → 1 フレーム以内に `source.active=network`、
   `net_fps≈15`、`reasm_drop` が増えない。Ctrl-C → 約 2 秒後にローカルへ復帰 (Playing なら続き、
   Stopped なら黒)。`/api/source {"mode":"local"}` で配信を無視、`network` でローカル停止
3. **server あり**: `/api/server {"enabled":true}` → 再起動後 STA が P2P 網に固定 IP で入る
   (`sta.origin=config`。NVS に LAN があるとそちらが勝つので `/api/wifi` を空 SSID で保存)。
   `[MQTT] connected` → server 側で online / ready → 配信開始。Web UI (AP 経由) の BRT / playback /
   led (test/off/pixels/axis) / system restart が効く。`sphere/<id>/log` に起動ログ。`[TIMESYNC] synced`
4. **OTA 両経路** (配信中): `atoms3r_ota` (AP) と `tools/ota.sh` (STA IP)。`[OTA] Start` で pump/UDP/MQTT が
   止まり、再起動後に同じモードへ戻る
5. **ソーク**: 30 分配信 + 回転。`[MEM]` heap_min、`[BOOT] Reset reason` に TASK_WDT/PANIC が無い。
   `FASTLED_RMT_MEM_BLOCKS=1` で AP+STA+UDP 下にちらつきが出れば 2 に戻す

### 残課題

- 実機確認 (上記)。特に AP チャンネル追従で iPhone が一瞬切れる挙動と、P2P 網不在時のバックオフ
- `/api/wifi` と P2P 網の共存 (NVS の LAN が常に勝つ。切り替えは Web UI で空 SSID 保存)
- 派生元 `core/` への逆流 (IMU 修正・協調停止・FLASH_LOCK) と README のポインタ
- `[RATE]/[PERF]` など solo の周期ログは `main.cpp` に残したまま (派生元の `Telemetry` に統合していない)
- `atoms3r_m5imu` env はリンク未確認 (従来どおり)
