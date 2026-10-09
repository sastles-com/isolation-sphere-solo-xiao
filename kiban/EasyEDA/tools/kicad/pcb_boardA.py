#!/usr/bin/env python3
"""基板A の回路図から PCB を作り、部品を配置する（配線はしない）。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      tools/kicad/pcb_boardA.py [出力 .kicad_pcb]

配置の前提（docs/easyeda_workflow.md §4、§5.5）：
- 外形は 40 mm 角に、左右（±x）へ mother-ring 用の張り出し（x = ±25、y = ±9.25）
- 基板A の表面はセル（40 × 40 × 10 mm）に 0.5 mm で接するので、**表面には部品を置けない**。
  表面に置くのは、張り出しの mother-ring 用コネクタ（J1、J2）だけ。表面実装の部品はすべて裏面（基板B 側）に置く
- 裏面の部品は、基板B 表面の部品と合わせて 6 mm 以内（基板間隔 7 mm − すき間 1 mm）
- 基板B とのヘッダ（J3、J4）は、基板B の J2、J3 と同じ位置（y = ∓16.5）・同じピン順にする。
  基板B は上から見て J2 の 1 番が x = −6.35。基板A も上から見て同じ座標に 1 番を置く
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcb_boardB as B  # noqa: E402  配置の道具（Fp、Placer、シルク文字）を流用する

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
SCH = os.path.join(ROOT, 'kicad', 'boardA', 'boardA.kicad_sch')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'kicad', 'boardA', 'boardA.kicad_pcb')
TAB_X, TAB_Y = 25.0, 9.25

B.CX = B.CY = 0.0                         # 基板の中心を原点にする（基板B と同じ）


def outline_points():
    h = 20.0
    return [(-h, -h), (h, -h), (h, -TAB_Y), (TAB_X, -TAB_Y), (TAB_X, TAB_Y), (h, TAB_Y), (h, h), (-h, h),
            (-h, TAB_Y), (-TAB_X, TAB_Y), (-TAB_X, -TAB_Y), (-h, -TAB_Y)]


def inside_board(x0, y0, x1, y1, margin=B.EDGE):
    """40 mm 角の中か、左右の張り出しを含む帯の中に、margin 以上離れて収まるか。"""
    h = 20.0 - margin
    in_square = -h <= x0 and x1 <= h and -h <= y0 and y1 <= h
    in_band = -(TAB_X - margin) <= x0 and x1 <= TAB_X - margin and -(TAB_Y - margin) <= y0 and y1 <= TAB_Y - margin
    return in_square or in_band


B.inside_board = inside_board
B.outline_points = outline_points


def read_netlist():
    xml = '/tmp/boardA_pcb.xml'
    subprocess.run([B.KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, SCH],
                   capture_output=True, text=True, check=True)
    t = ET.parse(xml).getroot()
    comps = {c.get('ref'): {'value': c.findtext('value') or '', 'fp': (c.findtext('footprint') or '').split(':')[-1]}
             for c in t.iter('comp')}
    nets = {n.get('name').lstrip('/'): [(x.get('ref'), x.get('pin')) for x in n.iter('node')] for n in t.iter('net')}
    return comps, nets


# 主要部品の固定位置（上から見た座標。x 右、y 下、mm）。(x, y, 回転, 裏面か)
PLAN = {
    # 基板B へのヘッダは、樹脂（絶縁体）が A と B の間に来るので裏面。この配置道具では回転 0 のまま裏返すと、
    # 上から見た 1 番が基板B の J2 / J3 と同じ (−6.35, ∓16.5) になる（12 ピンの座標とネットの一致を確認済み）
    'J3': (0.0, -16.5, 0, True),       # 基板B へ（VSYS / GND）
    'J4': (0.0, 16.5, 0, True),        # 基板B へ（I2C / CHG_INT）
    'J1': (-22.6, 0.0, 90, False),       # mother-ring 左（張り出し）
    'J2': (22.6, 0.0, 90, False),        # mother-ring 右（張り出し）
    'U4': (-3.0, -7.0, 0, False),        # LED 用 3.3 V 降圧（6 A）。VSYS の入口 J3 の近く
    'L2': (4.8, -8.5, 0, False),         # LED 用のインダクタ（7.1 × 6.5 mm）。基板B の F2（x ≥ 9.8）の真上を避ける
    'U3': (-6.0, 6.0, 0, False),         # MCU 用 3.3 V 降圧
    'L1': (0.5, 6.0, 0, False),          # MCU 用のインダクタ（4 × 4 mm）
    'U1': (10.0, 6.0, 0, False),         # LTC2954（電源 ON/OFF）
    'U2': (-13.0, -1.0, 0, False),       # 常時オン 3.3 V（J1 の 6 番 3V3_AON の近く）
}

# 機能ごとのまとまり：(名前, 部品, 左上の x, y, 向き, 1 行の個数)
GROUPS = [
    ('LED 入力', ['C22', 'C23', 'C24', 'C21'], -16.0, -13.5, 0, 4),
    ('LED 出力', ['C15', 'C16', 'C17', 'C18'], 1.5, -3.6, 90, 4),
    ('LED 周り', ['C19', 'C20', 'C14', 'R5', 'R7', 'R6'], -9.0, -4.0, 0, 3),
    ('MCU 入力', ['C12', 'C13'], -15.5, 3.0, 90, 2),
    ('MCU 出力', ['C8', 'C9'], 4.0, 3.5, 90, 2),
    ('MCU 周り', ['C10', 'C11', 'R3', 'R4'], -10.0, 9.5, 0, 4),
    ('電源 ON/OFF', ['C1', 'C2', 'C3', 'C4', 'C5', 'R1', 'R2'], 6.5, 9.5, 0, 4),
    ('常時オン', ['C6', 'C7'], -16.5, 2.0, 90, 2),
    ('プルアップ', ['R8', 'R9', 'R10'], -6.0, 12.5, 0, 3),
]


def build():
    comps, nets = read_netlist()
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(4)
    netmap = {}
    for name, pins in nets.items():
        if name.startswith('unconnected-'):
            continue
        board.Add(pcbnew.NETINFO_ITEM(board, name))
        for ref, pin in pins:
            netmap[(ref, pin)] = name
    pts = outline_points()
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetStart(B.vec(*p))
        seg.SetEnd(B.vec(*q))
        seg.SetWidth(B.mm(0.1))
        board.Add(seg)

    parts = {ref: B.Fp(ref, info, board, netmap) for ref, info in comps.items()}
    pl = B.Placer()
    for ref, (x, y, rot, back) in PLAN.items():
        pl.fixed(parts[ref], x, y, rot, back)
    rest = [r for r in parts if r not in PLAN]
    for name, refs, ax, ay, rot, per_row in GROUPS:
        pl.grid(parts, [r for r in refs if r in rest], ax, ay, rot, per_row)
        for r in refs:
            if r in rest and parts[r].placed_by_grid():
                rest.remove(r)
    for ref in rest:                      # グループに入れなかった部品：つながる IC のピンの近く
        tgt = None
        for (r, pin), nm in netmap.items():
            if r == ref and nm != 'GND':
                for r2, p2 in nets[nm]:
                    if r2 in PLAN and r2 != ref:
                        tgt = parts[r2].pad_pos(p2)
                        break
            if tgt:
                break
        pl.near(parts[ref], *(tgt or (0.0, 0.0)), back_ok=False)

    # 表面実装の部品は、すべて裏面へ（上から見た位置はそのまま、部品だけ裏返す）
    for f in parts.values():
        if not f.tht:
            f.fp.Flip(f.fp.GetPosition(), True)
            f.back = True
    B.silk_text(board)
    pcbnew.SaveBoard(OUT, board)
    dump = []
    for ref, f in parts.items():
        pads = []
        for pd in f.fp.Pads():
            bb = pd.GetBoundingBox()
            pads.append([B.tomm(bb.GetLeft()), B.tomm(bb.GetTop()), B.tomm(bb.GetRight()), B.tomm(bb.GetBottom()),
                         pd.GetNumber(), pd.GetNetname(), pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH])
        dump.append({'ref': ref, 'value': f.info['value'], 'back': f.back, 'rect': f.rect(f.x, f.y, f.rot, False), 'pads': pads})
    json.dump({'outline': outline_points(), 'parts': dump}, open(OUT.replace('.kicad_pcb', '.layout.json'), 'w'), ensure_ascii=False)


if __name__ == '__main__':
    build()
