#!/usr/bin/env python3
"""core-XIAO-04 の PCB を作り、部品を配置する（配線はしない）。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/core-XIAO-04/make_pcb.py [--force]

KiCad で PCB を開いていないときに実行する。既に PCB があるときは、--force を付けたときだけ作り直す
（KiCad で手を入れた配置や配線は消える）。

- 外形は core-XIAO-03 と同じ：40 mm 角（角は半径 3 mm）に、左右の張り出し（x = ±24.5、y = ±9.34）。
  XIAO の下の 12.2 mm 角の穴も 03 のまま。2 層
- 部品はすべて表面（北極側）。裏面はセルに向く
- XIAO は 03 と同じ位置と向き。LED のピン（1〜7 番）が右、制御と I2C（8〜11 番）が左に来る。
  mother-ring のヘッダは、右 J2（LED）、左 J1（制御・I2C）。XIAO のピンの並びと同じ順になる向き（1 番が +y 側）
- 回路図のシンボルに結び付けて（path を書き込んで）おくので、「回路図から基板を更新」しても配置は消えない
- シルクの文字は 0.5 × 0.7 × 0.1 mm、Fab 層の文字は非表示（基板A / B と同じ）
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'kiban', 'EasyEDA', 'tools', 'kicad'))
import pcb_boardB as B  # noqa: E402  シルク文字の道具を流用する
from relink import symbol_uuids  # noqa: E402

NAME = 'core-XIAO-04'
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
STOCK = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints'
LIBS = {NAME: os.path.join(HERE, f'{NAME}.pretty'), 'lcsc': os.path.join(HERE, 'lib', 'lcsc.pretty')}

# 部品の位置（基板中心が原点、x 右、y 下、mm）：(x, y, 回転)
PLAN = {
    'U1': (-0.11, 7.77, 180),       # XIAO（03 と同じ）。1〜7 番は x = 7.89、8〜14 番は x = −10.14、y = 0.15〜15.39
    # ヘッダの足型の原点は 1 番ピン。回転 180 で 1 番（y = +7.62）から −y 方向へ 7 本並ぶ
    'J2': (22.54, 7.62, 180),       # mother-ring 右（LED_D1〜D5、GND、HALL_WAKE）
    'J1': (-22.54, 7.62, 180),      # mother-ring 左（GND、3V3_MCU、I2C、PWR_KILL、LED_EN、3V3_AON）
    # LED データの 33 Ω：XIAO の 1〜6 番と同じ高さに並べる
    'R1': (12.0, 15.39, 0), 'R2': (12.0, 12.85, 0), 'R3': (12.0, 10.31, 0),
    'R4': (12.0, 7.77, 0), 'R5': (12.0, 5.23, 0), 'R6': (12.0, 2.69, 0),
    'R7': (15.0, 2.69, 0),          # LED_D6 のプルダウン
    'J3': (16.8, 10.5, 0),          # 北極（1×5、2.00 mm）。1 番が上、5 番が下
    # 3V3：J1 の 3V3_MCU → JP1 → XIAO の 3V3（10.31）。コンデンサは 3V3 と GND（12.85）の間
    'JP1': (-15.0, 7.6, 0),
    'C1': (-13.6, 11.58, 90), 'C2': (-16.0, 11.58, 90),
    'R8': (-15.0, 15.2, 0), 'D1': (-15.0, 18.0, 0),     # 電源 LED
    'TP1': (-16.5, -0.2, 0), 'TP2': (-16.5, 3.8, 0),      # 3V3_MCU、GND
    # 下側の帯：BNO055 モジュール（左、18 × 11 mm）とブザー（右）
    'U2': (-13.8, -9.7, 90),        # DIP-8：1〜4 番が y = −9.7 の列（x = −13.8〜−6.18）、5〜8 番が y = −17.32
    'LS1': (9.5, -13.3, 0),
    'C3': (17.6, -5.6, 90),
}
# BNO055 モジュールの外形（1 番ピンからの相対位置、回転 90 のとき）。DIP の足型には入っていないので、Fab と Courtyard に描く
BNO_BODY = (-5.2, -9.31, 12.8, 1.69)
CUTOUT = (-6.2, 4.6, 6.0, 16.8)


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def read_netlist():
    xml = f'/tmp/{NAME}_pcb.xml'
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml,
                    os.path.join(HERE, f'{NAME}.kicad_sch')], capture_output=True, text=True, check=True)
    t = ET.parse(xml).getroot()
    comps = {}
    for c in t.iter('comp'):
        fields = {f.get('name'): f.text or '' for f in c.iter('field')}
        comps[c.get('ref')] = {'value': c.findtext('value') or '', 'fp': c.findtext('footprint') or '',
                               'lcsc': fields.get('LCSC Part', ''),
                               'no_bom': any(p.get('name') == 'exclude_from_bom' for p in c.iter('property'))}
    pins = {}
    for n in t.iter('net'):
        for x in n.iter('node'):
            pins[(x.get('ref'), x.get('pin'))] = n.get('name').lstrip('/')
    return comps, pins


def seg(board, a, b, layer=pcbnew.Edge_Cuts, w=0.1):
    s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(vec(*a))
    s.SetEnd(vec(*b))
    s.SetLayer(layer)
    s.SetWidth(mm(w))
    board.Add(s)


def arc(board, a, mid, b):
    s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
    s.SetArcGeometry(vec(*a), vec(*mid), vec(*b))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    board.Add(s)


def outline(board):
    """03 と同じ外形：40 mm 角（角 R3）+ 左右の張り出し + XIAO の下の穴。"""
    h, r, tx, ty = 20.0, 3.0, 24.5, 9.34
    k = r * (1 - 0.5 ** 0.5)
    pts = [((-h + r, -h), (h - r, -h)), ((h, -h + r), (h, -ty)), ((h, -ty), (tx, -ty)), ((tx, -ty), (tx, ty)),
           ((tx, ty), (h, ty)), ((h, ty), (h, h - r)), ((h - r, h), (-h + r, h)), ((-h, h - r), (-h, ty)),
           ((-h, ty), (-tx, ty)), ((-tx, ty), (-tx, -ty)), ((-tx, -ty), (-h, -ty)), ((-h, -ty), (-h, -h + r))]
    for a, b in pts:
        seg(board, a, b)
    for sx, sy in ((1, -1), (1, 1), (-1, 1), (-1, -1)):          # 角の円弧
        cx, cy = sx * (h - r), sy * (h - r)
        arc(board, (cx, sy * h), (cx + sx * (r - k), cy + sy * (r - k)), (sx * h, cy))
    x0, y0, x1, y1 = CUTOUT
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        seg(board, a, b)


def load_fp(fpid):
    lib, name = fpid.split(':')
    f = pcbnew.FootprintLoad(LIBS.get(lib, os.path.join(STOCK, f'{lib}.pretty')), name)
    if f is None:
        raise SystemExit(f'フットプリントが見つからない：{fpid}')
    f.SetFPID(pcbnew.LIB_ID(lib, name))
    return f


def bno_body(board, f):
    """AE-BNO055-BO の外形を、U2 の Fab（線）と Courtyard（0.25 mm 外側）に描く。"""
    p1 = [p for p in f.Pads() if p.GetNumber() == '1'][0].GetPosition()
    x0, y0, x1, y1 = BNO_BODY
    for layer, g in ((pcbnew.F_Fab, 0.0), (pcbnew.F_CrtYd, 0.25)):
        a, b = (x0 - g, y0 - g), (x1 + g, y1 + g)
        for s0, s1 in (((a[0], a[1]), (b[0], a[1])), ((b[0], a[1]), (b[0], b[1])), ((b[0], b[1]), (a[0], b[1])),
                       ((a[0], b[1]), (a[0], a[1]))):
            s = pcbnew.PCB_SHAPE(f, pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(pcbnew.VECTOR2I(p1.x + mm(s0[0]), p1.y + mm(s0[1])))
            s.SetEnd(pcbnew.VECTOR2I(p1.x + mm(s1[0]), p1.y + mm(s1[1])))
            s.SetLayer(layer)
            s.SetWidth(mm(0.1 if layer == pcbnew.F_Fab else 0.05))
            f.Add(s)


def build(out):
    comps, pins = read_netlist()
    uu = symbol_uuids(open(os.path.join(HERE, f'{NAME}.kicad_sch'), encoding='utf-8').read())
    missing = sorted(set(comps) - set(PLAN))
    if missing:
        raise SystemExit(f'配置の決まっていない部品：{missing}')
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    for name in sorted(set(pins.values())):           # 未接続ピンのネット（unconnected-…）も作る（回路図との照合で必要）
        board.Add(pcbnew.NETINFO_ITEM(board, name))
    outline(board)
    for ref, info in sorted(comps.items()):
        f = load_fp(info['fp'])
        f.SetReference(ref)
        f.SetValue(info['value'])
        f.SetPath(pcbnew.KIID_PATH(f'/{uu[ref]}'))
        f.SetSheetname('/')
        f.SetSheetfile(f'{NAME}.kicad_sch')
        fld = pcbnew.PCB_FIELD(f, f.GetNextFieldOrdinal(), 'LCSC Part')
        fld.SetText(info['lcsc'])
        fld.SetVisible(False)
        fld.SetLayer(pcbnew.F_Fab)
        f.Add(fld)
        f.SetExcludedFromBOM(info['no_bom'])
        board.Add(f)
        for pad in f.Pads():
            net = pins.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(board.FindNet(net))
        x, y, rot = PLAN[ref]
        f.SetPosition(vec(x, y))
        f.SetOrientationDegrees(rot)
        if ref == 'U2':
            bno_body(board, f)
    B.silk_text(board)
    pro = os.path.join(HERE, f'{NAME}.kicad_pro')
    keep = open(pro, encoding='utf-8').read()         # SaveBoard は .kicad_pro を既定値で書き直すので、設計ルールを戻す
    pcbnew.SaveBoard(out, board)
    open(pro, 'w', encoding='utf-8').write(keep)
    print(f'{out}：部品 {len(comps)}、ネット {len(set(pins.values()))}')


if __name__ == '__main__':
    out = os.path.join(HERE, f'{NAME}.kicad_pcb')
    if os.path.exists(out) and '--force' not in sys.argv:
        raise SystemExit(f'{out} は既にある。作り直すときは --force（KiCad での変更は消える）')
    if any(n.endswith('.lck') and 'kicad_pcb' in n for n in os.listdir(HERE)):
        raise SystemExit('KiCad で PCB が開いている。閉じてから実行する')
    build(out)
