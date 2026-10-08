#!/usr/bin/env python3
"""【出典】FPC-isolation-sphere/kiban/resized/power-2S-02/tools/eda2kicad.py（2026-08-11）を取り込んだもの。
座標変換・シンボル生成・ジャンクションなどの部品として、tools/kicad/kicad_export.py から使う。

EasyEDA Pro の回路図ダンプ (tools/schematic-dump.json) から KiCad 10 の
.kicad_sch を生成する。バックアップ / 版管理用 (CLAUDE.md §5 の補完)。

使い方:
    # 1) EasyEDA からダンプ (要 eda-connect skill + ブリッジ)
    .claude/skills/eda-connect/scripts/eda-exec.sh tools/eda-dump-full.js > tools/schematic-dump.json
    # 2) 変換
    python3 tools/eda2kicad.py tools/schematic-dump.json kicad/power-2S-02.kicad_sch
    # 3) 検証 (ネットリストが一致するか)
    python3 tools/verify_kicad.py tools/schematic-dump.json kicad/power-2S-02.kicad_sch

設計上の要点 (いずれも legacy/power-2S.kicad_sch を実測して確定):
  * KiCad 10 形式 = (version 20260306) (generator_version "10.0")
  * 座標: EasyEDA 回路図は 0.01 inch 単位 → 1 unit = 0.254 mm ちょうど。
    ピンピッチ 10 units = 2.54 mm、配線は 5 units = 1.27 mm で KiCad の
    標準グリッドに完全に乗る (端数が出ない)。
  * Y 軸: シートは下向き正、シンボル内部は上向き正。
    実測で sheet_y = instance_y - symbol_local_y を確認済み。
    → シンボル内ピンのローカル座標は EasyEDA のオフセットと同符号でよい。
  * シンボルは「EasyEDA と同じピンオフセット」で自前生成する。
    KiCad 標準ライブラリ (抵抗のピンが ±3.81mm) を使うと EasyEDA の配線
    (±5.08mm) が届かず全部引き直しになるため。
    (lcsc, rotation, mirror) ごとに 1 個生成し、インスタンスは常に angle 0 で置く
    → KiCad と EasyEDA の回転方向の違いに影響されない。
"""
from __future__ import annotations

import json
import re
import sys
import uuid

MM_PER_UNIT = 0.254          # EasyEDA 回路図 1 unit = 0.01 inch = 0.254 mm
FONT_SCALE = 0.127           # 実測: EasyEDA fontSize 19.685 -> KiCad 2.5mm / 10 -> 1.27mm
MARGIN_MM = 20.0
PIN_LEN = 2.54
NS = uuid.UUID("6f1b2d40-0000-4000-8000-706f77657232")   # 決定論的 UUID 用


def det_uuid(*parts) -> str:
    return str(uuid.uuid5(NS, "|".join(str(p) for p in parts)))


def fnum(v: float) -> str:
    """KiCad は 0.0001 まで。末尾の 0 を落として書く。"""
    s = f"{round(v + 0.0, 4):.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def esc(s) -> str:
    return str(s if s is not None else "").replace("\\", "\\\\").replace('"', '\\"')


def sym_name(part: dict) -> str:
    """シンボル名 = 種別_LCSC_r回転[_m]。同一 (lcsc, rot, mirror) は共有する。"""
    pref = re.match(r"^[A-Za-z_]+", part["des"] or "X").group(0)
    lcsc = (part.get("lcsc") or "NOLCSC").replace(":", "_")
    tag = f"{pref}_{lcsc}_r{int(part.get('rot') or 0)}"
    if part.get("mirror"):
        tag += "_m"
    return tag


class Transform:
    """EasyEDA 座標 -> KiCad シート座標 (mm)。Y を反転して正領域に収める。"""

    def __init__(self, dump: dict):
        xs, ys = [], []
        for p in dump["parts"] + dump["netports"] + dump["netflags"]:
            xs.append(p["x"]); ys.append(p["y"])
            for q in p.get("pins") or []:
                xs.append(q["x"]); ys.append(q["y"])
        for w in dump["wires"]:
            for x, y in w["pts"]:
                xs.append(x); ys.append(y)
        for t in dump["texts"]:
            xs.append(t["x"]); ys.append(t["y"])
        for r in dump["rects"]:
            xs += [r["x"], r["x"] + r["w"]]
            ys += [r["topY"], r["topY"] - r["h"]]
        self.x0, self.y1 = min(xs), max(ys)
        self.w_mm = (max(xs) - self.x0) * MM_PER_UNIT + 2 * MARGIN_MM
        self.h_mm = (self.y1 - min(ys)) * MM_PER_UNIT + 2 * MARGIN_MM

    def x(self, v: float) -> float:
        return round((v - self.x0) * MM_PER_UNIT + MARGIN_MM, 4)

    def y(self, v: float) -> float:
        return round((self.y1 - v) * MM_PER_UNIT + MARGIN_MM, 4)


def build_symbol(name: str, part: dict, show_pin_text: bool) -> tuple[str, dict]:
    """lib_symbols のエントリを生成。ローカル座標は EasyEDA オフセットと同符号。"""
    px, py = part["x"], part["y"]
    pins = []
    for q in part.get("pins") or []:
        pins.append({
            "num": q.get("num") or "1",
            "name": q.get("name") or "~",
            "lx": round((q["x"] - px) * MM_PER_UNIT, 4),
            "ly": round((q["y"] - py) * MM_PER_UNIT, 4),
        })
    # 各ピンを「水平ピン」「垂直ピン」に振り分ける (支配的な成分で決める)
    for p in pins:
        p["vert"] = abs(p["ly"]) > abs(p["lx"])
    hor = [p for p in pins if not p["vert"]]
    ver = [p for p in pins if p["vert"]]
    # 本体矩形の半径。全ピンの線長が 1.27mm 以上になるように決める
    bhx = max(1.27, min((abs(p["lx"]) for p in hor), default=1.27 + PIN_LEN) - PIN_LEN)
    if ver:
        bhy = max(1.27, min(abs(p["ly"]) for p in ver) - PIN_LEN)
    else:
        bhy = max(1.27, max((abs(p["ly"]) for p in hor), default=0) + 1.27)
    if hor:
        bhy = max(bhy, max(abs(p["ly"]) for p in hor) + 1.27)

    out = []
    a = out.append
    a(f'\t\t(symbol "gen:{name}"')
    a(f'\t\t\t(pin_numbers\n\t\t\t\t(hide {"no" if show_pin_text else "yes"})\n\t\t\t)')
    a(f'\t\t\t(pin_names\n\t\t\t\t(offset 0.508)\n\t\t\t\t(hide {"no" if show_pin_text else "yes"})\n\t\t\t)')
    a('\t\t\t(exclude_from_sim no)\n\t\t\t(in_bom yes)\n\t\t\t(on_board yes)\n\t\t\t(in_pos_files yes)')
    a('\t\t\t(duplicate_pin_numbers_are_jumpers no)')
    ref_pref = re.match(r"^[A-Za-z_]+", part["des"] or "X").group(0)
    for pname, pval, ypos, hide in (
        ("Reference", ref_pref, bhy + 1.27, False),
        ("Value", esc(part.get("mpn") or ""), -bhy - 1.27, False),
        ("Footprint", "", 0.0, True),
        ("Datasheet", "", 0.0, True),
        ("Description", esc(part.get("mpn") or ""), 0.0, True),
    ):
        a(f'\t\t\t(property "{pname}" "{pval}"')
        a(f'\t\t\t\t(at 0 {fnum(ypos)} 0)')
        if hide:
            a('\t\t\t\t(hide yes)')
        a('\t\t\t\t(show_name no)\n\t\t\t\t(do_not_autoplace no)')
        a('\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)')
        a('\t\t\t)')
    # 図形 (本体矩形)
    a(f'\t\t\t(symbol "{name}_0_1"')
    a(f'\t\t\t\t(rectangle\n\t\t\t\t\t(start {fnum(-bhx)} {fnum(-bhy)})\n\t\t\t\t\t(end {fnum(bhx)} {fnum(bhy)})')
    a('\t\t\t\t\t(stroke\n\t\t\t\t\t\t(width 0.254)\n\t\t\t\t\t\t(type solid)\n\t\t\t\t\t)')
    a('\t\t\t\t\t(fill\n\t\t\t\t\t\t(type background)\n\t\t\t\t\t)\n\t\t\t\t)')
    a('\t\t\t)')
    # ピン
    a(f'\t\t\t(symbol "{name}_1_1"')
    for p in pins:
        if p["vert"]:
            ang = 270 if p["ly"] > 0 else 90
            ln = max(1.27, abs(p["ly"]) - bhy)
        else:
            ang = 0 if p["lx"] < 0 else 180
            ln = max(1.27, abs(p["lx"]) - bhx)
        a(f'\t\t\t\t(pin passive line\n\t\t\t\t\t(at {fnum(p["lx"])} {fnum(p["ly"])} {ang})')
        a(f'\t\t\t\t\t(length {fnum(ln)})')
        a(f'\t\t\t\t\t(name "{esc(p["name"])}"\n\t\t\t\t\t\t(effects\n\t\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t\t(size 1.016 1.016)\n\t\t\t\t\t\t\t)\n\t\t\t\t\t\t)\n\t\t\t\t\t)')
        a(f'\t\t\t\t\t(number "{esc(p["num"])}"\n\t\t\t\t\t\t(effects\n\t\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t\t(size 1.016 1.016)\n\t\t\t\t\t\t\t)\n\t\t\t\t\t\t)\n\t\t\t\t\t)')
        a('\t\t\t\t)')
    a('\t\t\t)')
    a('\t\t)')
    return "\n".join(out), {"bhx": bhx, "bhy": bhy}


GND_SYMBOL = """\t\t(symbol "gen:GND"
\t\t\t(power)
\t\t\t(pin_numbers
\t\t\t\t(hide yes)
\t\t\t)
\t\t\t(pin_names
\t\t\t\t(offset 0)
\t\t\t\t(hide yes)
\t\t\t)
\t\t\t(exclude_from_sim no)
\t\t\t(in_bom no)
\t\t\t(on_board yes)
\t\t\t(in_pos_files no)
\t\t\t(duplicate_pin_numbers_are_jumpers no)
\t\t\t(property "Reference" "#PWR"
\t\t\t\t(at 0 -3.81 0)
\t\t\t\t(hide yes)
\t\t\t\t(show_name no)
\t\t\t\t(do_not_autoplace no)
\t\t\t\t(effects
\t\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(property "Value" "GND"
\t\t\t\t(at 0 -6.35 0)
\t\t\t\t(show_name no)
\t\t\t\t(do_not_autoplace no)
\t\t\t\t(effects
\t\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(property "Footprint" ""
\t\t\t\t(at 0 0 0)
\t\t\t\t(hide yes)
\t\t\t\t(show_name no)
\t\t\t\t(do_not_autoplace no)
\t\t\t\t(effects
\t\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(symbol "GND_0_1"
\t\t\t\t(polyline
\t\t\t\t\t(pts
\t\t\t\t\t\t(xy -1.27 -1.905) (xy 1.27 -1.905)
\t\t\t\t\t)
\t\t\t\t\t(stroke
\t\t\t\t\t\t(width 0.254)
\t\t\t\t\t\t(type solid)
\t\t\t\t\t)
\t\t\t\t\t(fill
\t\t\t\t\t\t(type none)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(polyline
\t\t\t\t\t(pts
\t\t\t\t\t\t(xy -0.762 -2.667) (xy 0.762 -2.667)
\t\t\t\t\t)
\t\t\t\t\t(stroke
\t\t\t\t\t\t(width 0.254)
\t\t\t\t\t\t(type solid)
\t\t\t\t\t)
\t\t\t\t\t(fill
\t\t\t\t\t\t(type none)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(polyline
\t\t\t\t\t(pts
\t\t\t\t\t\t(xy -0.254 -3.429) (xy 0.254 -3.429)
\t\t\t\t\t)
\t\t\t\t\t(stroke
\t\t\t\t\t\t(width 0.254)
\t\t\t\t\t\t(type solid)
\t\t\t\t\t)
\t\t\t\t\t(fill
\t\t\t\t\t\t(type none)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(symbol "GND_1_1"
\t\t\t\t(pin power_in line
\t\t\t\t\t(at 0 0 270)
\t\t\t\t\t(length 1.905)
\t\t\t\t\t(name "GND"
\t\t\t\t\t\t(effects
\t\t\t\t\t\t\t(font
\t\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t\t)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t\t(number "1"
\t\t\t\t\t\t(effects
\t\t\t\t\t\t\t(font
\t\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t\t)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)"""


def instance(lib_id, ref, val, x, y, uid, props, in_bom=True) -> str:
    o = []
    a = o.append
    a('\t(symbol')
    a(f'\t\t(lib_id "{lib_id}")')
    a(f'\t\t(at {fnum(x)} {fnum(y)} 0)')
    a('\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)')
    a(f'\t\t(in_bom {"yes" if in_bom else "no"})\n\t\t(on_board yes)\n\t\t(in_pos_files {"yes" if in_bom else "no"})\n\t\t(dnp no)')
    a(f'\t\t(uuid "{uid}")')
    allp = [("Reference", ref, False), ("Value", val, False)] + props
    dy = 0.0
    for name, v, hide in allp:
        a(f'\t\t(property "{name}" "{esc(v)}"')
        a(f'\t\t\t(at {fnum(x)} {fnum(y - 6.0 - dy)} 0)')
        if hide:
            a('\t\t\t(hide yes)')
        a('\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)')
        a('\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)')
        a('\t\t)')
        dy += 0.0 if hide else 2.2
    a('\t)')
    return "\n".join(o)


def segments(dump):
    """EasyEDA の getState_Line() は **独立した線分の並び** (2 点ずつ) を返す。
    ポリラインではないので (0,1) (2,3) (4,5) ... とペアで取る。
    T 字接続で統合されたワイヤは 1 オブジェクトに複数線分が入る。
    長さ 0 の線分 (GUI ドラッグの副産物) は捨てる。"""
    segs = []
    for w in dump["wires"]:
        pts = w["pts"]
        for i in range(0, len(pts) - 1, 2):
            a, b = tuple(pts[i]), tuple(pts[i + 1])
            if a != b:
                segs.append((w["net"], a, b))
    return segs


def on_seg(p, a, b) -> bool:
    (px, py), (x1, y1), (x2, y2) = p, a, b
    if x1 == x2 == px:
        return min(y1, y2) <= py <= max(y1, y2)
    if y1 == y2 == py:
        return min(x1, x2) <= px <= max(x1, x2)
    return False


def junctions(segs):
    """KiCad は T 字接続に junction が必須 (EasyEDA は自動)。
    多めに打っても表示上の点が増えるだけで害はないので、取りこぼさない側に倒す。"""
    ends = {}
    for _, a, b in segs:
        for p in (a, b):
            ends[p] = ends.get(p, 0) + 1
    out = set()
    for p, n in ends.items():
        if n >= 3:
            out.add(p)
            continue
        for _, a, b in segs:
            if p != a and p != b and on_seg(p, a, b):
                out.add(p)
                break
    return sorted(out)


def main(src: str, dst: str) -> None:
    dump = json.load(open(src, encoding="utf-8"))
    tr = Transform(dump)

    # --- シンボル定義 (lcsc, rot, mirror) ごとに 1 個 -------------------------
    symbols, meta = {}, {}
    for p in dump["parts"]:
        n = sym_name(p)
        if n in symbols:
            continue
        pref = re.match(r"^[A-Za-z_]+", p["des"] or "X").group(0)
        show = pref in ("U", "Q", "CN") or len(p.get("pins") or []) > 2
        symbols[n], meta[n] = build_symbol(n, p, show)

    body = []
    a = body.append
    a('(kicad_sch')
    a('\t(version 20260306)')
    a('\t(generator "eda2kicad.py")')
    a('\t(generator_version "10.0")')
    a(f'\t(uuid "{det_uuid("sheet", dump["project"]["uuid"])}")')
    a(f'\t(paper "{"A2" if tr.w_mm <= 594 and tr.h_mm <= 420 else "A1"}")')
    a('\t(lib_symbols')
    for n in sorted(symbols):
        a(symbols[n])
    a(GND_SYMBOL)
    a('\t)')

    # --- 枠 (破線) ----------------------------------------------------------
    for i, r in enumerate(dump["rects"]):
        a('\t(rectangle')
        a(f'\t\t(start {fnum(tr.x(r["x"]))} {fnum(tr.y(r["topY"]))})')
        a(f'\t\t(end {fnum(tr.x(r["x"] + r["w"]))} {fnum(tr.y(r["topY"] - r["h"]))})')
        a('\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type dash)\n\t\t)')
        a('\t\t(fill\n\t\t\t(type none)\n\t\t)')
        a(f'\t\t(uuid "{det_uuid("rect", i)}")')
        a('\t)')

    # --- 配線 ---------------------------------------------------------------
    segs = segments(dump)
    for i, (net, p1, p2) in enumerate(segs):
        a('\t(wire')
        a(f'\t\t(pts\n\t\t\t(xy {fnum(tr.x(p1[0]))} {fnum(tr.y(p1[1]))}) (xy {fnum(tr.x(p2[0]))} {fnum(tr.y(p2[1]))})\n\t\t)')
        a('\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)')
        a(f'\t\t(uuid "{det_uuid("wire", i, net, p1, p2)}")')
        a('\t)')
    for i, p in enumerate(junctions(segs)):
        a('\t(junction')
        a(f'\t\t(at {fnum(tr.x(p[0]))} {fnum(tr.y(p[1]))})')
        a('\t\t(diameter 0)\n\t\t(color 0 0 0 0)')
        a(f'\t\t(uuid "{det_uuid("junc", i, p)}")')
        a('\t)')

    # --- グローバルラベル (EasyEDA の NET_PORT) -------------------------------
    for i, np_ in enumerate(dump["netports"]):
        pin = (np_.get("pins") or [{"x": np_["x"], "y": np_["y"]}])[0]
        a(f'\t(global_label "{esc(np_["net"])}"')
        a('\t\t(shape input)')
        a(f'\t\t(at {fnum(tr.x(pin["x"]))} {fnum(tr.y(pin["y"]))} 0)')
        a('\t\t(fields_autoplaced yes)')
        a('\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left)\n\t\t)')
        a(f'\t\t(uuid "{det_uuid("glabel", i, np_["net"], pin["x"], pin["y"])}")')
        a('\t)')

    # --- ローカルラベル (ブロック内ノード名を保存) ---------------------------
    # EasyEDA はネット名をワイヤ属性として持つが KiCad はラベルからしか名前を
    # 取れない。名前を落とすと Net-(Q1-G) のような自動名になり可読性が落ちるので、
    # 各内部ネットにつき 1 個ローカルラベルを置く (接続には影響しない)。
    seen_net = set()
    for i, (net, p1, p2) in enumerate(segs):
        if not net or net in seen_net:
            continue
        seen_net.add(net)
        a(f'\t(label "{esc(net)}"')
        a(f'\t\t(at {fnum(tr.x(p1[0]))} {fnum(tr.y(p1[1]))} 0)')
        a('\t\t(fields_autoplaced yes)')
        a('\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)')
        a(f'\t\t(uuid "{det_uuid("label", net)}")')
        a('\t)')

    # --- 注釈テキスト -------------------------------------------------------
    for i, t in enumerate(dump["texts"]):
        size = max(0.5, round((t.get("size") or 10) * FONT_SCALE, 3))
        a(f'\t(text "{esc(t["content"])}"')
        a('\t\t(exclude_from_sim no)')
        a(f'\t\t(at {fnum(tr.x(t["x"]))} {fnum(tr.y(t["y"]))} 0)')
        bold = "\n\t\t\t\t(bold yes)" if t.get("bold") else ""
        a(f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {fnum(size)} {fnum(size)}){bold}\n\t\t\t)\n\t\t\t(justify left)\n\t\t)')
        a(f'\t\t(uuid "{det_uuid("text", i, t["content"])}")')
        a('\t)')

    # --- 部品インスタンス ---------------------------------------------------
    for p in dump["parts"]:
        n = sym_name(p)
        props = [
            ("Footprint", "", True),
            ("Datasheet", "", True),
            ("Description", p.get("mpn") or "", True),
            ("LCSC", p.get("lcsc") or "", True),
            ("MPN", p.get("mpn") or "", True),
        ]
        a(instance(f"gen:{n}", p["des"], p.get("value") or "",
                   tr.x(p["x"]), tr.y(p["y"]), det_uuid("part", p["des"]), props))

    # --- GND 電源シンボル (EasyEDA の netflag) --------------------------------
    for i, f in enumerate(dump["netflags"], start=1):
        pin = (f.get("pins") or [{"x": f["x"], "y": f["y"]}])[0]
        a(instance("gen:GND", f"#PWR{i:03d}", f.get("net") or "GND",
                   tr.x(pin["x"]), tr.y(pin["y"]), det_uuid("gnd", i, pin["x"], pin["y"]),
                   [("Footprint", "", True), ("Datasheet", "", True)], in_bom=False))

    a('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)')
    a(')')

    text = "\n".join(body) + "\n"
    import os
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    open(dst, "w", encoding="utf-8").write(text)
    print(f"生成: {dst}")
    print(f"  用紙 {tr.w_mm:.0f} x {tr.h_mm:.0f} mm 相当  シンボル定義 {len(symbols)+1} 種")
    print(f"  部品 {len(dump['parts'])} / GND {len(dump['netflags'])} / "
          f"ラベル {len(dump['netports'])} / 配線 {len(segs)} 線分 / "
          f"ジャンクション {len(junctions(segs))} / 枠 {len(dump['rects'])} / 注釈 {len(dump['texts'])}")
    print(f"  ローカルラベル {len(seen_net)} 種 (内部ノード名の保存用)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
