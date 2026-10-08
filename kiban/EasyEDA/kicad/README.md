# kicad/ — 回路図の KiCad 版（自動生成）

**このフォルダの回路図は自動生成物。手で編集しない。** 正本は EasyEDA Pro のプロジェクト `power-2s-xiao`。
KiCad で回路図を見る・レビューするためのスナップショット。

| フォルダ | 親シート | 子シート |
| --- | --- | --- |
| `boardA/` | `boardA.kicad_sch` | `boardA_POWER.kicad_sch`、`boardA_LED_IO.kicad_sch` |
| `boardB/` | `boardB.kicad_sch` | `boardB_CHARGER.kicad_sch`、`boardB_PROTECTION.kicad_sch` |

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

## 限界

- **フットプリントは空。** KiCad で PCB は作れない（PCB は EasyEDA で作る）
- **ERC は通らない。** 電源フラグ（`PWR_FLAG`）がなく、ピンの種類もすべて passive のため
- シンボルの見た目は KiCad の作図規約と異なる（接続の正しさを優先）

## 検証結果（2026-10-08）

| 基板 | 部品 | 2 ピン以上のネット | 結果 |
| --- | ---: | ---: | --- |
| 基板A | 44 | 23 | ✅ 一致 |
| 基板B | 67 | 43 | ✅ 一致 |
