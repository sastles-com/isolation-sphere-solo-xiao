# kicad/ — 回路図の KiCad 版（自動生成）

**このフォルダの回路図は自動生成物。手で編集しない。** 正本は EasyEDA Pro のプロジェクト `power-2s-xiao`。
KiCad で回路図を見る・レビューするためのスナップショット。

| フォルダ | 親シート | 子シート |
| --- | --- | --- |
| `boardA/` | `boardA.kicad_sch`（1 枚、`kicad_flat.py` で生成） | なし |
| `boardB/` | `boardB.kicad_sch`（1 枚に統合） | なし |

KiCad で `boardA/boardA.kicad_pro`（または `.kicad_sch`）を開き、親シートの四角をダブルクリックして各ページへ入る。

## 作り直し方

EasyEDA で回路図を変えたら、ブリッジを起動して EasyEDA を接続した状態で：

```sh
python3 tools/kicad/kicad_export.py          # 両方の基板
```

1. 各ページを開いて保存し、全要素を取り出す（`dump_<PAGE>.json`）
2. KiCad 10 形式の階層回路図に変換する
3. **kicad-cli で KiCad 本体にネットリストを書き出させ、EasyEDA のネットリストとピン集合で比べる**。`✅ ネットリスト一致` が出ることを毎回確認する

作業中は EasyEDA のタブを切り替えない（別のページを取り出してしまう）。

## 変換の仕組み

| 項目 | 内容 |
| --- | --- |
| 接続 | EasyEDA の「ネット名を付けた線」を、つながった線の島ごとに KiCad のラベルへ置き換える |
| ラベルの種類 | 2 ページ以上に出てくるネット（`VSYS`、`GND`、`I2C_SDA` など）はグローバルラベル、それ以外はローカルラベル |
| シンボル | EasyEDA と同じピン位置を持つ矩形のシンボルを生成する（抵抗もジグザグにならない） |
| 文字・枠 | 注釈の文字と破線の枠をそのまま移す。ネット名を表すための文字は、ラベルと重複するので移さない |
| 座標 | EasyEDA 回路図 1 単位 = 0.254 mm。KiCad の標準グリッドに一致する |
| 部品の情報 | `LCSC`、`MPN` フィールドに保持する |

道具は `tools/kicad/`。座標変換・シンボル生成は、FPC-isolation-sphere の power-2S-02 で作った変換ツール（`eda2kicad_core.py`）を取り込んだもの。

## LCSC のシンボル・フットプリント（`kicad/lib/`）

`easyeda2kicad` で、LCSC 番号からシンボル・フットプリント・3D モデルを取得して使う。

```sh
pipx install --backend pip easyeda2kicad      # 初回だけ
python3 tools/kicad/lcsc_lib.py                # 未取得の部品を取得して整える
python3 tools/kicad/kicad_export.py            # 取得したシンボルで作り直す
```

- `kicad/lib/lcsc.kicad_sym`、`lcsc.pretty/` は Git に入れる。`lcsc.3dshapes/`（1 部品 2〜3 MB）は入れない。必要なら `lcsc_lib.py` で取得し直す
- 各プロジェクトの `sym-lib-table` / `fp-lib-table` に `lcsc` ライブラリを登録済み
- 取得したシンボルは、EasyEDA の回路図とピン位置が一致する向き（0/90/180/270°）を自動で探して使う。合わない部品と未取得の部品は、従来の矩形シンボルにする
- **EasyEDA の API は、続けて 30 部品ほど取得すると 403 を返す**（一時的なブロック）。時間を置いて `lcsc_lib.py` を再実行すると、未取得の部品だけを取得する

## 限界

- 未取得の部品は矩形シンボルで、フットプリントは空
- **ERC は通らない。** 電源フラグ（`PWR_FLAG`）がないため
- 取得したフットプリント（特に QFN の熱パッドとピン番号）は、データシートと照合していない

## 検証結果（2026-10-08）

| 基板 | 部品 | 2 ピン以上のネット | 結果 |
| --- | ---: | ---: | --- |
| 基板A | 44 | 23 | ✅ 一致 |
| 基板B | 67 | 43 | ✅ 一致 |

## 基板B は KiCad 側で統合した（2026-10-09）

基板B の回路図は、CHARGER と PROTECTION を手で 1 枚（`boardB/boardB.kicad_sch`）に統合し、**KiCad 側が元データ**になった。
EasyEDA からの自動生成（`kicad_export.py boardB`）は、統合前の 2 枚構成を作り直して上書きするので、**もう実行しない**。
フットプリントと LCSC 品番の割り当ては `python3 tools/kicad/assign_footprints.py`（L2 は `lcsc_lib.py` で C87572 を取得してから）。

## 基板A も 1 枚にした（2026-10-09）

基板A は、EasyEDA のダンプとネットリストから、基板B と同じ書き方で 1 枚の回路図に作り直した。

```
python3 tools/kicad/kicad_flat.py      # → kicad/boardA/boardA.kicad_sch、refmap.json
```

- ルール：階層なし 1 枚（A3）、機能ごとの点線の枠と日本語の見出し、接続は短い線 + グローバルラベル、GND は部品ごとに GND 記号、
  標準の抵抗・コンデンサ・インダクタ記号、通し番号の部品名（旧名は `refmap.json` と、部品の `EasyEDA` プロパティ）
- 生成の直後に kicad-cli のネットリストを、EasyEDA のネットリスト（`outputs/schematic/boardA_nets.txt`）と照合する
- 基板A の元データは EasyEDA のまま。回路を変えたら、EasyEDA を直し、ダンプとネットリストを更新して、`kicad_flat.py` を実行する。
  KiCad 側で手直しすると、次の生成で上書きされる（基板B と違い、基板A は KiCad を元データにはしていない）
