# 基板B：保護 FET を有効にする手順（BQ28Z620 の FET_EN）

作成 2026-11-14。対象は初版の基板B（`kiban/EasyEDA/kicad/boardB-reverse`）。
作り直し版（`kiban/power-AB-02/boardB-reverse`）も同じ回路なので、同じ手順が要る（起こす操作はボタン SW1 でできる）。

## 1. 症状と原因

**症状**：電池（2S LiPo）をつないでも VSYS が出ない。保護 FET（Q2、FS8205A）が開かない。

原因は 2 つ重なっている。

| # | 原因 | 根拠 |
| --- | --- | --- |
| 1 | **残量計が起動できない**。BQ28Z620 は PACK ピンが 2.05〜2.45 V を超えるまで SHUTDOWN のまま。PACK（U1 の 8 番）は R10 を通して PACK_P、つまり Q2 の出力側にあるので、電池だけでは 0 V のまま | データシート SLUSET3（VSHUTDOWN+）。PACK_P に電圧を掛けたら起きた |
| 2 | **FET_EN = 0**。出荷時のデータフラッシュ（Mfg Status init = 0x0000）では、起きても FET を駆動しない | 起こした直後の ManufacturingStatus = 0x8000（FET_EN = 0）、OperationStatus = 0x6100（XCHG・XDSG） |

SHUTDOWN 中の残量計は I2C の線を約 2 V に引き下げる。このあいだは同じバスの BNO055（0x28）も見えなくなる。

## 2. 用意するもの

- XIAO ESP32S3 を載せた core-XIAO-04（I2C のプルアップは BNO055 モジュール内蔵の 10 kΩ）
- 確認用スケッチ `tools/boardB_gauge_check`
- 抵抗 8.2 kΩ（1 kΩ〜10 kΩ ならよい）。J11–J10 を一時的につなぐのに使う
- テスター
- 基板A は**外す**。充電入力（基板B の J1）も**つながない**

## 3. 配線

| 信号 | core-XIAO-04 の J1 | 基板B の J3 |
| --- | --- | --- |
| GND | 1 番 | 2 番 または 6 番 |
| SDA（XIAO D10 = GPIO9） | 3 番 | 1 番（四角いパッド） |
| SCL（XIAO D9 = GPIO8） | 4 番 | 3 番 |

- core の J1 の 2 番（3V3_MCU）は基板B につながない。基板B の J3 の 2 番は GND なので、まっすぐ 1 番同士でつなぐと 3.3 V が GND に落ちる。
- 基板B は部品が裏面の版。部品面から見ると左右が逆になるので、1 番は四角いパッドで確かめる。
- 読み取りエラー（`Wire.cpp ... Error -1`）が出るときは、SDA・SCL に 4.7 kΩ を 3.3 V へ足す。

## 4. スケッチの書き込み

```
~/.platformio/penv/bin/pio run -d tools/boardB_gauge_check -t upload
~/.platformio/penv/bin/pio device monitor -d tools/boardB_gauge_check     # 115200
```

| コマンド | 内容 | 書き込み |
| --- | --- | --- |
| `s` | スキャンして状態を表示 | 読むだけ |
| `v` | SDA・SCL の電圧を測る（測ったあと再起動） | 読むだけ |
| `m` | ManufacturingStatus / OperationStatus の応答をそのまま表示 | 読むだけ |
| `p` | I2C のピンの組み合わせを総当たり | 読むだけ |
| `F` | FET_EN を**反転**する（MAC 0x0022）。`y` で確定 | **残量計のデータフラッシュも変わる** |
| `W` | データフラッシュの Mfg Status init に FET_EN を書く。`y` で確定 | 書き込み（今回は不要だった） |

## 5. 手順（基板 1 枚につき 1 回）

1. 基板B に LiPo をつなぐ（J4・J5 の極性に注意）。
2. 3 章のとおり I2C と GND をつなぎ、XIAO を USB につなぐ。
3. テスターで確認する（GND 基準）。
   - J11（BAT_F）：6.0〜8.4 V（2 セルの合計）
   - J10（PACK_P）：約 0 V（FET が閉じている）
4. **J11 と J10 を 8.2 kΩ でつなぐ**（直結しない）。数秒待つ。
5. `s` でスキャンし、次を確かめる。
   - `found 0x55` がある（残量計が起きた）
   - `DAStatus1` の PACK が 2.1 V 以上
   - `ManufacturingStatus` の **FET_EN = 0**（「読めない」と出たら `m` で読み直す。`57 00 00 80 …` なら 0x8000 = FET_EN 0）
   - SafetyStatus・PFStatus が 0
6. **FET_EN = 0 のときだけ** `F` を送り、`y` で確定する。FET_EN が既に 1 のときに送ると 0 に戻る。
7. 結果を確かめる。
   - ManufacturingStatus：FET_EN = 1（0x8010 など）
   - OperationStatus：`DSG(放電FET ON) CHG(充電FET ON)`
   - PACK ≈ BAT（約 8 V）
   - DF Mfg Status init：0x0010（データフラッシュに保存された）
8. 8.2 kΩ を外す。テスターで VSYS が約 8 V のままか確かめる。
9. `s` で Current() を見る。基板A など何もつないでいなければ 0〜数 mA のはず。
10. 保存の確認：LiPo を外して数秒待ち、つなぎ直す → 4 の要領でもう一度起こす → `s` で FET_EN = 1、CHG・DSG とも ON。

## 6. 以後の使い方

- FET_EN は残量計の**データフラッシュ（不揮発）**に残る。電池を外しても消えない。
- FET の開閉そのものは残らない。電池を外すと残量計は止まり、FET は閉じる。
- 電池をつないだら、**起こす操作を 1 回**する：
  - J11–J10 に 8.2 kΩ を一瞬当てる、または
  - 充電入力を一度入れる（PACK_P が約 5 V まで上がって起きることを確認済み）、または
  - 作り直し版ではボタン SW1 を押す
- 起きれば、残量計が FET_EN = 1 を読んで、異常がなければ自分で FET を開ける。過充電・過放電・過電流・短絡・温度異常では自分で閉じる。
- 電池を使い切って残量計が止まった場合も、充電器を挿せば起きて充電が始まる。
- 抵抗を J11–J10 に**つなぎっぱなしにしない**。保護 FET の迂回路になり、過放電保護が効かなくなる。

## 7. つまずいた点

| 症状 | 原因と対処 |
| --- | --- |
| 基板B をつなぐと 0x28（BNO055）も含めて何も見えない。SDA・SCL が約 2 V | 残量計が SHUTDOWN。4 の手順で起こす |
| スキャンが 100 秒以上かかって 0 個 | 同上（バスが Low に張り付いてタイムアウトしている） |
| 充電入力を入れたら XIAO が USB から消えた | 充電入力の 5 V を XIAO / Mac の USB から取ると、充電 IC の入力電流で USB ポートが止まる。別の電源を使う |
| 充電中に `REG1B` の VINDPM が立つ | 5 V 電源が電流を出し切れず、充電 IC が入力を絞っている。約 8 V × 1 A ≒ 8 W なので、5 V 側は 2 A 近く要る |
| ManufacturingStatus が「読めない」 | 時々失敗する。`m` で読み直す |
| SafetyAlert に 0x00200000 が出た | 保護の予告（SafetyStatus は 0 のまま）。中身は TRM で未確認 |

## 8. 実施記録

| 基板 | 日付 | `F` 前 | `F` 後 | 電池を外したあと | 備考 |
| --- | --- | --- | --- | --- | --- |
| 1 枚目 | 2026-11-13 | FET_EN 0、PACK 7909 mV | FET_EN 1、CHG・DSG ON、VSYS 8 V | FET_EN 1 のまま | 充電 約 1 A を確認。残量 79 % |
| 2 枚目 | 2026-11-14 | FET_EN 0、PACK 2091 mV | FET_EN 1、CHG・DSG ON、PACK 8143 mV | 未確認 | 放電電流 約 140 mA（1 枚目は 0〜4 mA）。PACK_P に試験用の LED をつけていた。PACK が 2091 mV と低いのも、この LED のせいと考えられる（[power_AB_bringup_notes.md](power_AB_bringup_notes.md) の 3 章） |

残量（%）は残量計の学習（GAUGE_EN）が無効のままの値で、満充電容量も初期値。目安として見る。
