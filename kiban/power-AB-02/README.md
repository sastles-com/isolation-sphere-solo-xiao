# power-AB-02 — 基板A / 基板B の作り直し

`kiban/EasyEDA/kicad/boardA`、`boardB-reverse`（製造済みの初版。`kiban/panel-AB` で面付け）を元に、
回路の誤りを直し、部品配置と配線をやり直す版。初版のファイルは記録として残し、書き換えない。

**状態（2026-11-13）：PCB の配置・配線まで（未接続 0）。面付けと製造用ファイルはこれから。実機での確認はしていない。**

| ファイル | 内容 |
| --- | --- |
| `boardB-reverse/boardB-reverse.kicad_pcb` | 基板B、4 層。機能ブロックごとに並べ、残量計を起こすボタン（R21・SW1）を足した版 |
| `boardB-reverse/boardB-reverse-v2-blocks.*` | 基板B、4 層。ボタンを足す前の版（回路図も同じ名前で残してある） |
| `boardB-reverse/boardB-reverse-v1.kicad_pcb` | 基板B、4 層。ブロックごとに並べる前の版（小さい部品は自動配置） |
| `boardB-reverse/boardB-reverse-2layer-trial.kicad_pcb` | 基板B、2 層の**試作**。信号はつながるが、GND の塗りが充電 IC のまわりで細切れになり、島が 3 か所つながっていない。使わない |
| `boardA/boardA.kicad_pcb` | 基板A、**2 層**（表・裏の空きを GND で塗る） |
| `boardA/boardA-4layer.kicad_pcb` | 基板A、4 層（In2 が GND 面）。`.kicad_pro` も同じ名前で写してある |

部品面のシルクに、機能ブロックの枠（点線）と名前を入れてある（スクリプトの `FRAMES`）。
基板B：GAUGE / SHUNT / CHARGER / CHG IN / CHG CFG / BATT PATH。基板A：LED BUCK / MCU BUCK / 3V3 AON / PWR SW / EXT。

## PCB の作り方

```
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
$PY tools/pcb_boardB.py                 # 配置と電源の太い配線（基板A は pcb_boardA.py。既定は 2 層、4 層は --4layer）
$PY tools/route.py prep boardB-reverse  # Specctra の DSN を出す
java -jar freerouting.jar -de route-work/boardB-reverse/boardB-reverse.dsn -do route-work/boardB-reverse/boardB-reverse.ses -mp 80 -mt 0
$PY tools/route.py apply boardB-reverse # 取り込み、足りない GND ビアを足す、面を塗る
```

- **スクリプトを実行すると PCB を作り直す。KiCad で手直ししたあとは実行しない。**
- Freerouting（v2.1.0）は、結果が毎回変わる。1〜2 本残ることがあり、そのときは `route.py link`（1 本を 1 つの層でつなぐ）か KiCad で引く。
  基板B の v1 は `CHG_G` を `link` でつないだ（ブロックごとに並べた版は、自動配線だけで全部つながった）。配線が終わってから SES を書くまで 20 分ほど止まることがある。
- 線幅・クリアランスは 0.15 mm、信号のビアは 0.5 / 0.3 mm（0.4 mm ピッチの IC から引き出すため。初版は 0.2 mm、0.6 / 0.3 mm）。

## PCB で決めたこと・残っていること

- 基板B：部品はすべて位置を決めて置く（`PLACE`）。電流検出（SRP / SRN）と U3 の GND ピンは固定の配線。
- 基板B は 4 層のままにする。2 層（`pcb_boardB.py --2layer`）は、充電 IC（1.5 MHz の昇降圧、0.4 mm ピッチ）の下に続いた GND を取れない。
- 部品の参照名（シルク）は、ライブラリの位置のままで部品から離れている。未整理。
- 基板A：部品の位置は初版のまま（`J7`、`R8`、`C19` だけ動かした）。3V3_LED は表面（F.Cu）の 2.2 mm 幅で左右の J1 / J2 へ。
- 基板A の `J11`〜`J15` は**仮の位置**（y = 12.6 に 2.54 mm ピッチで一列）。相手の基板が決まったら動かす。
- 基板A の 2 層版は、左の張り出しの GND（J1 の 2 番）が、表の 3V3_LED の配線に囲まれ、裏の GND とは**ビア 1 個**（0.6 / 0.3 mm）でしかつながっていない。
  LED の戻り電流が左側にも流れるなら、ビアを足すか 4 層版を使う。降圧の GND 面も 4 層版のほうが部品面に近い（0.2 mm と 1.6 mm）。
- 基板A の J1 / J2 のパッドは、張り出しの端から 0.42 mm（DRC の基板端 0.5 mm に 12 件かかる。初版と同じ）。
- 初版のシルクのロゴと文字は写していない。シルクの重なり（DRC の警告）も未整理。

## 初版からの変更

| 基板 | 変更 | 理由 |
| --- | --- | --- |
| B | `D2` のシンボルを `lcsc:LED_A1K2`（1 番 = アノード）に変更 | KiCad 標準の `Device:LED`（1 番 = カソード）と、C2286 のフットプリント（1 番 = アノード）が逆で、LED が逆向きに実装された |
| B | `R8` を 10 kΩ → 2.2 kΩ（C4190） | 充電表示 LED が暗い（元の EasyEDA の設計値に戻す） |
| B | 回路図の UUID を、部品の instances / プロジェクトと同じ値にそろえた | 食い違いのせいで、名前のないネット（`Net-(D2-A)` など）が kicad-cli のネットリストに出なかった |
| A | `J11`〜`J15`（`MCU_EN`、`HALL_WAKE`、`3V3_AON`、`VSYS`、`LED_EN`）を追加 | 別の mother-ring 基板へつなぐ 2.54 mm ピン |
| 共通 | `lcsc.pretty` の TPS566238P（QFN-9）の属性を `through_hole` → `smd` | BOM と部品位置ファイルから外れていた（初版は手はんだで実装） |
| 共通 | 製造用ファイルの回転補正（`AUTO TRANSLATE`）を無効 | 補正表は KiCad 標準フットプリント用。`lcsc` のフットプリントは EasyEDA（JLCPCB）の向きなので補正は要らない |

ライブラリは初版と共用（`../EasyEDA/kicad/lib/lcsc.*`）。

## これから

1. KiCad で目視確認（とくに降圧まわりと、上の「残っていること」）。
2. 面付け（panel）と製造用ファイル。

### 基板B（初版）で、電池だけでは VSYS が出なかった件（2026-11-13 に原因を確認）

保護 FET（Q2、FS8205A）が開かなかった。原因は 2 つ重なっていた。

1. **残量計が起動できない**：BQ28Z620 は PACK ピンの電圧が 2.05〜2.45 V（VSHUTDOWN+）を超えるまで SHUTDOWN のまま
   （データシート SLUSET3）。PACK（U1 の 8 番）は R10 を通して PACK_P、つまり Q2 の出力側にある。セルだけでは PACK_P が 0 V で、起きない。
   SHUTDOWN 中の残量計は I2C の線を約 2 V に引き下げ、同じバスの BNO055 も見えなくなる。
2. **FET_EN = 0**：起きても、出荷時のデータフラッシュ（Mfg Status init = 0x0000）では FET を駆動しない。

確認の手順：セルをつなぎ、J11（BAT_F）と J10（PACK_P）を 8.2 kΩ でつないで残量計を起こす → `tools/boardB_gauge_check` の `F`（MAC 0x0022）
→ CHG・DSG とも ON、PACK = BAT、VSYS ≈ 8 V。8.2 kΩ を外しても VSYS は 8 V のまま。
`F` だけで Mfg Status init が 0x0010 に変わり、LiPo を外してつなぎ直したあとも FET_EN = 1 のままだった（`W` は不要だった）。
充電入力（5 V）で充電も確認：約 1 A、BQ25792 は定電流充電（CHG_STAT = 3）、VINDPM（入力電圧の下限）が働いていた。

**作り直し版（power-AB-02 の基板B）でやったこと（2026-11-14）**：
- 残量計を起こすボタンを追加：BAT_F → R21 8.2 kΩ（C25981）→ SW1（TS-1187A-B-A-B、C318884、5.1 × 5.1 mm、高さ 1.5 mm）→ PACK_P。
  SW1 は対角の 1 番と 4 番を使う（1-2、3-4 は内部でつながる）。電池をつないだ直後に 1 回押す。充電入力を入れても起きる。
- 抵抗を常時つなぐのは不可（保護 FET の迂回路になり、過放電保護が効かない）。
- 組み立て後に一度、`F` で FET_EN を有効にし、電源を入れ直して FET_EN = 1 が残ることを確かめる。
