# XIAO ESP32S3 版 立ち上げメモ

M5AtomS3R 版 (`isolation-sphere-solo`) から分岐した。コア基板を XIAO ESP32S3 で作り直す
(出発点: `FPC-isolation-sphere/kiban/core-XIAO-03`) のに合わせ、ファームも別リポジトリにした。
XIAO には LCD・本体ボタン・M5 ライブラリが無い。電源 ON は北極の磁石（ホール素子）、ほかの操作は IMU のシェイクで行う。

## 分岐時にやったこと (2026-10-06)

- AtomS3R 版を履歴ごと複製し、未コミットだった省電力機能 (AP 自動停止 / モデム省電力 / トリプルシェイク切替) を作業ツリーに取り込んだ。
- 削除: `LCDManager`、`IMUManager_m5imu.cpp` と `MadgwickAHRS.h`、`board_atoms3r.h`、M5Unified 依存、`atoms3r*` の env、
  設定の LCD 項目 (`ConfigManager`)、LCD 連動コード (`main` / `DeviceController` / `SoloWebServer` / `SerialConsole` / `CommandHandler`)。
- トリプルシェイクは AP の ON/OFF 切替だけになった (`DeviceController::togglePowerSave`)。
- `pio run -e xiao_esp32s3` が通る (Flash 58.4% / RAM 21.1%)。`pio test -e native` は 68 件成功。
  **実機は未確認** (XIAO 版としては一度も書き込んでいない)。
- `data/config.json` の `features.LCD` 項目は読まれなくなったが残している (派生元との互換)。

## ボード向けリファクタリング (2026-10-06)

- ボード定義を `src/BoardConfig.h` 1 つにまとめた (`src/boards/` の振り分けと `-D BOARD_XIAO_ESP32S3` を廃止)。
- **5 ストリップ化**: `kLedPins[] = {1, 2, 3, 4, 44}`、`kLedsPerStrip = 160`。以前の XIAO 定義は 4 本で、
  5 本分の `led_layouts-5strip.csv` を読むと 5 本目の 160 個が捨てられていた。
- 5 本目は GPIO44 (D7) で暫定にしていた。→ core-XIAO-04 で LED は D0〜D5 に確定（下の「core-XIAO-04 のピン割り当て」）。
- FastLED の登録は `kLedPins[]` を再帰テンプレートで展開する 1 か所にまとめた (以前は 3 か所に本数ぶん複製し `#if` で出し分け)。
- ブザーを有効化 (GPIO43 = core-XIAO-03 の LS1)。`BOARD_HAS_LCD` / `BOARD_HAS_BUZZER` / `BOARD_NUM_STRIPS` は廃止。
- `data/config.json` の LCD 項目を削除。
- 注意: `spheres[]` の MAC は AtomS3R 機 (sphere001/002) のもの。XIAO 機で server モードを使うなら MAC を登録し直す。
- 注意: build_flags の `-std=c++14` は効いていない (`std::index_sequence` が使えなかった)。C++14 の機能に依存しないこと。

## core-XIAO-04 のピン割り当て (2026-10-10 確定)

回路図は [`kiban/core-XIAO-04`](../kiban/core-XIAO-04/make_sch.py)（MCU 基板 core-XIAO-04 と北極基板 north-pole-04）。

| XIAO | GPIO | 用途 | 備考 |
| --- | --- | --- | --- |
| D0〜D4 | 1, 2, 3, 4, 5 | LED ストリップ 1〜5（各 160 個） | 33 Ω を通して mother-ring の LINE01〜05 へ |
| D5 | 6 | LED ストリップ 6 = 北極 LED（1 個） | 電源は `3V3_MCU`。10 kΩ でプルダウン |
| D6 | 43 (TX) | ブザー | 起動中に High / ログが出るので LED には使わない |
| D7 | 44 (RX) | `LED_EN` | 起動中は入力のまま。基板A のプルダウンで既定 OFF |
| D8 | 7 | `PWR_KILL` | 基板A で 100 kΩ プルアップ。起動中に Low にしない (FW-1) |
| D9 / D10 | 8 / 9 | I2C SCL / SDA | XIAO の標準 (D4/D5) ではない。`Wire.begin(9, 8)`（SDA = GPIO9、SCL = GPIO8）で指定 |

- `kLedPins[] = {1, 2, 3, 4, 5}`（各 160 個）+ 北極 `{6}`（1 個）。RMT は 4ch なので時分割（`docs/solo_mode.md` §9）。
- 北極 LED は `3V3_MCU` から給電されるので、`LED_EN` と関係なく使える。FW-2 の「`LED_EN` が Low の間はデータ線 Low」は
  ストリップ 1〜5 だけに適用する。起動直後（ROM / ブートローダの数百 ms）は点かない。
- I2C：充電 IC 0x6B、残量計 BQ28Z620 0x55（要確認）、BNO055 0x28（秋月 AE-BNO055-BO を MCU 基板に直接実装）。
  プルアップは AE-BNO055-BO 内蔵の 10 kΩ だけ。
- ファーム側の要件（FW-1〜5）は [`kiban/EasyEDA/docs/interfaces.md`](../kiban/EasyEDA/docs/interfaces.md) §7。

## 確定した方針 (ユーザー決定)

- **電源 ON / OFF**: 北極の DRV5032FC → 基板A の LTC2954-1。磁石を約 2.15 秒保持で ON、約 7.8 秒（最小 5.5 秒）でハード強制 OFF
  （状態を保存しない非常用）。通常 OFF は **IMU のシェイク**で判定し、ブザーや北極 LED で予告して取り消せるようにしてから
  `PWR_KILL` を Low にする。トリプルシェイク（AP の ON/OFF）とははっきり違う動作にする（2026-10-10。TMAG5273 は廃止）。
- **北極基板への配線は 5 本**: `3V3_AON`、`HALL_WAKE`、GND、`LED_D6`、`3V3_MCU`。I2C は北極へ行かない。
  北極には DRV5032 の動作確認用の赤 LED（磁石を検出している間だけ点く）もある。
- ~~PCA9632 で `VETO` / `PWR_OFF`、ホール入力 1 本、ホールボタン（短押し / ダブル / 長押し）、北極 LED を LINE05 の 161 個目に連結~~
  → 電源系を `kiban/EasyEDA` の案に替えたことと core-XIAO-04 の設計で、すべて廃止（2026-10-10）。
- **給電端子 (南極) のキャップ**: ダミープラグ型 (プラグと同じマグネット配置・接点なし・絶縁)。
  IMU は IMUPLUS (磁気不使用) なので、キャップの磁石が方位に影響する心配はない。北極ホールへの影響は
  キャップ磁石をプラグより強くしないことで抑え、実機で確認する。
- 接続案内: LCD の QR の代わりに、個体ごとの SSID (MAC 付き) を**個体シールの QR**で渡す (`tools/make_wifi_qr.py`)。

## 次にやること

1. **ボード定義の残り** (`src/BoardConfig.h`)。上の表のピン（LED 6 本、`LED_EN`、`PWR_KILL`、I2C、ブザー）に合わせる。
2. **電源制御** (新規): FW-1〜3 の手順（`PWR_KILL` は起動中に触らない、`LED_EN` を上げてから 5 ms 以上待って送る、
   シャットダウンはデータ線 Low → `LED_EN` Low → 保存 → `PWR_KILL` Low）。
3. **OFF ジェスチャ** (新規): BNO055 のシェイクで判定する純ロジック。トリプルシェイク（AP の ON/OFF）と区別し、
   予告と取り消しの時間を入れる。`test/` に native 単体テストを追加する (タイマーと IMU の値は注入)。
4. **`StatusLed`** (新規): 北極 LED（ストリップ 6、1 個）で 起動 / AP 動作中 / 接続あり / 再生中 / 省電力 / OFF 予告 を表示する。
   球体マッピング (`SphereMap`) と 800 個の前提には入れない。

## ハード側の宿題 (`FPC-isolation-sphere`)

### このリポジトリでの基板設計 (2026-10-06)

- 制御プログラムに加えて、基板・3Dプリント部品も本リポジトリで扱う。
- mother-ring のポゴピン→ピンヘッダ変更は保留。
- 電池は **2S を維持**。
- 2026-10-07、電源系は [`kiban/EasyEDA`](../kiban/EasyEDA/README.md) の案を採用。
  40 mm 角の2枚構成（基板A：電源制御、基板B：充電・BMS）、LED は WS2812C-2020-V6 を 3.3 V で駆動。
  [`kiban/power-2s`](../kiban/power-2s/README.md)（IP2326 + MP1584、5V LED）は参考資料扱い。
- 北極ホールは DRV5032FC + LTC2954-1。約2.15秒の保持でON、約7.8秒（最小5.5秒）の保持でハード強制OFF。
  通常OFFは IMU のシェイクを XIAO が判定して `PWR_KILL` を Low にする（2026-10-10、TMAG5273 は廃止）。
  ファーム側の要件は [`kiban/EasyEDA/docs/interfaces.md`](../kiban/EasyEDA/docs/interfaces.md) §7。
- 基板A / B は KiCad で回路図・PCB（配線途中）まで作成済み。core-XIAO-04 と北極基板は回路図まで（2026-10-10）。

- mother-ring 次版: core との接続を 1×7 ×2 に改版（core-XIAO-04 の J1 / J2 と同じ並び）。LED の 33 Ω は core 側へ移したので外すか 0 Ω。
  電源は基板A の `3V3_LED` に合わせる。LINE05 の `DOUT05` 端子は不要になった（北極 LED は 6 本目のストリップ）。
- core-XIAO-04 / north-pole-04 の PCB。北極基板の外形（pillar の先の寸法）を決める。
- 給電端子キャップ。core-XIAO-03 の製造発注状況を確認する。

## 開発上の注意

- CLI でビルドするときは、VS Code の PlatformIO 拡張と `.pio/build` が競合するので、
  `PLATFORMIO_BUILD_DIR` を別ディレクトリに向ける。
- AtomS3R 版の修正を取り込むときは、`git remote add atoms3r <URL>` してチェリーピックする。
  LCD・M5 に触れるコミットは取り込まない。
