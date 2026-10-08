# 一次資料 / データシート確認リスト

実装の根拠には、最新のメーカー公式資料を使うこと。最終的な電気定数を、通販のモジュールページやチャットの要約に頼って決めないこと。

## LTC2954 — Analog Devices

製品ページ：
<https://www.analog.com/en/products/ltc2954.html>

データシート（Rev. B を確認）：
<https://www.analog.com/media/en/technical-documentation/data-sheets/2954fa.pdf>

確認済み（2026-10-07）：

- 選定：-1（EN ハイアクティブ、低リークのオープンドレイン）
- 電源電圧 2.7〜26.4 V、静止電流 6 µA typ / 12 µA max
- PB：内部 100 kΩ で 1.9 V へプルアップ、入力範囲 −1〜26.4 V、しきい値 0.6〜1.0 V
- ON：32 ms + C_ONT × 6.4 s/µF。式は `C_ONT[µF] = 1.56×10⁻⁴ × (t_ONT[ms] − 1)`
- 強制 OFF：64 ms + C_PDT × 6.4 s/µF
- KILL：しきい値 0.6 V、起動後のブランキング 400 / 512 / 650 ms。この間に High にならないと EN を解除する
- OFF 後は 256 ms 間 PB を無視する
- 長配線の PB には直列 5.1 kΩ と 0.1 µF を推奨

残りの確認項目：

- 選定した MCU 降圧の EN 入力との電圧整合
- LCSC での入手性

## BQ25792 — Texas Instruments（採用）

製品ページ：
<https://www.ti.com/product/BQ25792>

データシート：
<https://www.ti.com/lit/ds/symlink/bq25792.pdf>

LCSC：C2862876（BQ25792RQMR、VQFN-29）
<https://www.lcsc.com/product-detail/C2862876.html>

確認済み（2026-10-08）：

- 入力動作範囲 3.6〜24 V（絶対最大 30 V）、入力過電圧保護の初期値 26 V
- 1〜4 セル、昇降圧、NVDC、充電 最大 5 A、電池放電 6 A RMS 連続 / 10 A ピーク（1 s 以内）
- PROG 抵抗でセル数と周波数を設定。2 セルの初期値は 8.4 V・1 A
- 入力電流上限の初期値 3 A（ILIM_HIZ の抵抗で制限）
- I²C アドレス 0x6B、電池のみで動作中の静止電流 17 µA typ（ADC 無効時）
- BQ25798 とピン配置が同じ（評価ボード BQ25792EVM / BQ25798EVM を共用）

確認項目：

- 2S、12 V 入力のリファレンス回路（BQ25792EVM ユーザーガイド SLUUCB5）とインダクタ選定
- BQ28Z610 との接続構成
- 入力 1 系統で使う場合の ACDRV / SDRV の処理

ユーザーガイド：
<https://www.ti.com/document-viewer/lit/html/SLUUCB5E>

## 不採用にした充電 IC

比較は `hardware_spec.md` §3.3。

- BQ25883：<https://www.ti.com/product/BQ25883>（入力 3.9〜6.2 V。12 V 不可）
- BQ25798：<https://www.ti.com/product/BQ25798>（BQ25792 に MPPT とバックアップを加えたもの。ピン配置は同じ）

## BQ28Z620 — Texas Instruments（採用）

製品ページ：
<https://www.ti.com/product/BQ28Z620>

データシート（SLUSET3）：
<https://www.ti.com/lit/ds/symlink/bq28z620.pdf>

LCSC：C20345237（VSON-12、64 個、1 個 $6.98 / 100 個 $5.28）
<https://www.lcsc.com/product-detail/C20345237.html>

JLC の PCBA：C20345237 は Extended 部品で、Economic / Standard の両方で実装できる（JLC のページで確認、2026-10-08）。購入した部品は JLC の部品ライブラリに入り、単体では発送されない。在庫数はページに出ないため、発注時に確認する。
JLC の別の登録 C22395771 は購入不可。

確認済み（2026-10-08）：

- BQ28Z610-R1 とピン互換（VSON-12、DRZ）
- R1 からの変更点：1.2 V ロジックの I/O、保護 FET ゲート駆動 5.75 V の選択肢、1 mΩ 未満のシャントに対応、BTP 機能を削除
- SDA/SCL：推奨上限 5.5 V、絶対最大 6 V、VIH 0.78 V、VIL 0.42 V。3.3 V プルアップで使える
- I²C が約 2 秒 Low に保持されるとバスを解放する
- 設計例ではブロードキャスト（Master Mode）が有効。本設計では無効にする

データシートとテクニカルリファレンスマニュアルの両方を読むこと。

確認項目：

- 2S セル電圧検出の接続
- 保護 FET の構成とシャント / ケルビン配線
- バランスの設定
- パック設定 / 学習 / 校正の要件（bqStudio）
- I²C アドレス（0x55 を想定）
- 充電器 / システムのパワーパスとの相互作用

### 比較した品種

- BQ28Z610（無印）：<https://www.ti.com/product/BQ28Z610>。LCSC C157573。I²C タイムアウトの不具合があり、新規設計には推奨されない
- BQ28Z610-R1：<https://www.ti.com/product/BQ28Z610-R1>。無印の不具合をシリコンで修正。LCSC に無い

## JST XH（電池コネクタ）

- 2.5 mm ピッチ、3 A（AWG22）、適合電線 AWG30〜22
- 縦向きの B2B-XH-A は実装高さ 9.8 mm。基板間隔 7.0 mm に収まらないため使わない
- データシート：<https://www.digikey.be/en/resources/datasheets/jst/xh-connector>

## DRV5032 — Texas Instruments

製品ページ：
<https://www.ti.com/product/DRV5032>

確認済み（データシート SLVSDC7H）：

- 選定：**DRV5032FCDBZR**（SOT-23）
- 全極性、オープンドレイン、20 Hz、平均 1.3 µA、B_OP 最大 4.8 mT
- 磁界が B_OP を超えると出力 Low、B_RP を下回るとハイインピーダンス
- VCC 1.65〜5.5 V
- 代替：DRV5032AJ（全極性、オープンドレイン、最大 9.5 mT）

残りの確認項目：

- 使用する磁石と、北極外殻からセンサまでの距離での磁束密度

## TMAG5273 — Texas Instruments

製品ページ：
<https://www.ti.com/product/TMAG5273>

確認項目：

- 測定範囲のバリアント
- I²C アドレス / オプション
- 割り込みを使うかどうか
- 北極の磁石に必要な測定範囲
- 機械設計における X/Y/Z 軸の向き

## LED 降圧の候補 — TPS56637

製品ページ：
<https://www.ti.com/product/TPS56637>

候補であり、確定部品ではない。

確認項目：

- 2S の入力範囲
- 3.3 V / 約 4 A 連続時の効率と熱
- インダクタとコンデンサの選定
- EN のロジック
- レイアウト要件
- 入手性 / EasyEDA・JLC での実装適性

## MCU 降圧の候補 — TPS62162

製品ページ：
<https://www.ti.com/product/TPS62162>

1 A 品の候補。MCU レールに 1 A を超える余裕が必要になる可能性があるため、**確定していない**。

## mother-ring コネクタ

ユーザー指定の秋月電子の候補：

- <https://akizukidenshi.com/catalog/g/g100167/>
- <https://akizukidenshi.com/catalog/g/g103784/>

PCB リリース前に確認すること：

- オス / メスの正確な組み合わせ
- 接点 1 個あたりの電流定格
- 嵌合深さ
- ピン長
- PCB の穴径
- 機械的な向きと 1 番ピンの規則
- LED 給電接点 1 個あたり約 2 A を連続で流したときの温度上昇

## LED

使用品：Worldsemi WS2812C-2020-V6（確定、LCSC C55109522）

製品ページ：
<https://www.lcsc.com/product-detail/C55109522.html>

データシート（V1.0、2026-05-21、中国語）：
<https://www.lcsc.com/datasheet/C55109522.pdf>

確認済み（2026-10-08）：

- 電源電圧 +3.3〜+5.3 V。3.3 V 動作は保証範囲内（下限ちょうど）
- VIH は 0.55 × VDD 以上、VIL は 0.7 V 以下、VI は −0.3 V〜VDD + 0.7 V
- 各色 5 mA、静止電流 1 µA 以下
- VDD に 100 nF のデカップリングを推奨

注意：旧品 WS2812C-2020（V1）は電源電圧 +3.7〜+5.3 V で、3.3 V では使えない。調達時に V6 であることを確認すること。
参考（V1 相当、秋月電子）：<https://akizukidenshi.com/goodsaffix/ws2812c-2020.pdf>

残りの確認項目：

- mother-ring 末端での電圧降下（LED 降圧の出力電圧の決定に使う）
- 電源 OFF 時のデータピンからの逆給電の挙動（実機）
