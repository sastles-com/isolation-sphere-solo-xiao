# XIAO ESP32S3 版 立ち上げメモ

M5AtomS3R 版 (`isolation-sphere-solo`) から分岐した。コア基板を XIAO ESP32S3 で作り直す
(出発点: `FPC-isolation-sphere/kiban/core-XIAO-03`) のに合わせ、ファームも別リポジトリにした。
XIAO には LCD・本体ボタン・M5 ライブラリが無く、代わりに北極のホール素子をボタンにする。

## 分岐時にやったこと (2026-10-06)

- AtomS3R 版を履歴ごと複製し、未コミットだった省電力機能 (AP 自動停止 / モデム省電力 / トリプルシェイク切替) を作業ツリーに取り込んだ。
- 削除: `LCDManager`、`IMUManager_m5imu.cpp` と `MadgwickAHRS.h`、`board_atoms3r.h`、M5Unified 依存、`atoms3r*` の env、
  設定の LCD 項目 (`ConfigManager`)、LCD 連動コード (`main` / `DeviceController` / `SoloWebServer` / `SerialConsole` / `CommandHandler`)。
- トリプルシェイクは AP の ON/OFF 切替だけになった (`DeviceController::togglePowerSave`)。
- `pio run -e xiao_esp32s3` が通る (Flash 58.4% / RAM 21.1%)。`pio test -e native` は 68 件成功。
  **実機は未確認** (XIAO 版としては一度も書き込んでいない)。
- `data/config.json` の `features.LCD` 項目は読まれなくなったが残している (派生元との互換)。

## 確定した方針 (ユーザー決定)

- **GPIO**: PCA9632 (I2C) を維持して `VETO` / `PWR_OFF` を出し、GPIO はホール入力 1 本だけ追加する。
  ホール入力は RTC 対応 GPIO (D0〜D5, D8〜D10)。`HALL_OUT` は常時オン 3.3V 側なので、XIAO 未通電時の逆流防止に
  直列抵抗 (10〜100kΩ) を入れる。D6/D7 (GPIO43/44) は WS2812 に使わない (起動時ブートログで誤点灯する)。
  D2 (GPIO3) はストラップピンなので、ストリップに使う場合は起動時の挙動を確認する。
- **ホールボタン**: 短押し / ダブル / 長押しをファームで判定する。動作中の電源 OFF はハードの長押し (約 1.5 秒)。
  短い操作はファームのボタン。OFF→ON は今のまま (かざした瞬間に点灯)。
- **北極 RGB LED**: WS2812。データ線は mother-ring の LINE05 の最終 `DOUT` に端子を新設し、線を北極まで延ばして
  161 個目の LED として連結する。5V 振幅に整形済みの信号を受けられ、GPIO を使わない。
- **給電端子 (南極) のキャップ**: ダミープラグ型 (プラグと同じマグネット配置・接点なし・絶縁)。
  IMU は IMUPLUS (磁気不使用) なので、キャップの磁石が方位に影響する心配はない。北極ホールへの影響は
  キャップ磁石をプラグより強くしないことで抑え、実機で確認する。
- 接続案内: LCD の QR の代わりに、個体ごとの SSID (MAC 付き) を**個体シールの QR**で渡す (`tools/make_wifi_qr.py`)。

## 次にやること

1. **ボード定義を新コア基板に合わせる** (`src/boards/board_xiao_esp32s3.h`)。
   core-XIAO-03 の J4 は GPIO01〜04 + GPIO09 の 5 ストリップ。RMT は 4ch なので 5 本目は時分割 (`docs/solo_mode.md` §9)。
   I2C (D4/D5)、ホール入力 `kHallPin`、PCA9632 のアドレスを追加する。
   **設計書 (FPC-isolation-sphere docs/08, 09) の GPIO 番号と、ファームの定義が食い違っている。実機の配線を先に確認する。**
2. **`HallButton`** (新規): 押下時間を測る純ロジック。イベントは Short / Double / Long (0.7〜1.4 秒)。
   1.5 秒以上はハードが電源を切るので扱わない。`test/test_hall_button` に native 単体テストを追加する (タイマーは注入)。
   操作の割り当ては未確定。叩き台: Short = 再生/一時停止、Double = AP の ON/OFF、Long = 省電力一括。
3. **`Pca9632` ドライバ** (新規): ch0 = `VETO`、ch1 = `PWR_OFF`。電源投入時は両方非アサート (boot-safe)。
4. **`StatusLed`** (新規): 北極 RGB LED で 起動 / AP 動作中 / 接続あり / 再生中 / 省電力 を表示する。
   ストリップ 5 の LED 数を 160→161 にし、161 個目は球体マッピング (`SphereMap`) と 800 個の前提から外す。
   `kMaxLeds`、FastLED の電流制限、`led_layouts` の扱いを確認する。pillar の配線は 6 本→8 本 (`DOUT05` と `V5V` を追加)。

## ハード側の宿題 (`FPC-isolation-sphere`)

- docs/06: 動作中のみ CLK を遅延させる長押し OFF 回路の改訂。
- mother-ring-03 → 次版: LINE05 の最終 `DOUT05` に端子を新設 (現状は各コネクタで終端)。`V5V` の取り出しも確認する。
- docs/08, 09: ホール信号を ESP32 へ渡す線、RGB LED の連結、給電端子キャップ、GPIO 表、pillar 配線 8 本化。
- core-XIAO-04 (仮): ホール入力のピンと抵抗を追加。core-XIAO-03 の製造発注状況を確認する。

## 開発上の注意

- CLI でビルドするときは、VS Code の PlatformIO 拡張と `.pio/build` が競合するので、
  `PLATFORMIO_BUILD_DIR` を別ディレクトリに向ける。
- AtomS3R 版の修正を取り込むときは、`git remote add atoms3r <URL>` してチェリーピックする。
  LCD・M5 に触れるコミットは取り込まない。
