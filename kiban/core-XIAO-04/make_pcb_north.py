#!/usr/bin/env python3
"""north-pole-04（北極基板）の PCB を作り、部品を配置する（配線はしない）。KiCad 付属の Python で動かす。

【配線の手順（2026-10-11）】Freerouting の DSN の境界を半径 4.45 mm に縮め（端から 0.5 mm 以上離すため）、
クリアランス 0.15 mm、配線 0.2〜0.3 mm、GND も配線で引いた（ベタは入れない。ベタは島ができて、つながらなかった）。
プロジェクトのクリアランスは 0.15 mm。部品番号の文字は、基板の外に出るので非表示にした。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/core-XIAO-04/make_pcb_north.py [--force]

KiCad で PCB を開いていないときに実行する。既に PCB があるときは --force を付けたときだけ作り直す。

- 外形：直径 10 mm の円（北極のペンタゴン開口は約 6〜7 mm、コアの頂上から内殻までは約 9 mm。キャップの内側に収まる大きさ）
- 2 層、基板の厚さ 0.8 mm。外側（キャップ側）の表面は WS2812C（北極 LED）だけ（高さをそろえ、LED だけを見せる）。
  コア側の裏面：DRV5032FC（WS2812C の真裏 = 磁石の軸の上）、0.1 µF のコンデンサ 2 個、確認用 LED とその抵抗
- ケーブルは、5 つのスルーホール（穴 0.65 mm）に AWG30 前後の線を直接はんだ付けする。左端に 3 つ、右端に 2 つ
  並びは core-XIAO-04 の J3 と同じ（1 3V3_AON、2 HALL_WAKE、3 GND、4 LED_D6、5 3V3_MCU）。外のコネクタへは線で引き出す
- WS2812C は円の中心（極の軸の上）。DRV5032FC は、その真裏。基板を 0.8 mm にして、磁石との距離の増加を抑える
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'kiban', 'EasyEDA', 'tools', 'kicad'))
import pcb_boardB as B  # noqa: E402  シルク文字の道具
from relink import symbol_uuids  # noqa: E402

NAME = 'north-pole-04'
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
STOCK = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints'
LIBS = {'lcsc': os.path.join(HERE, 'lib', 'lcsc.pretty'), 'core-XIAO-04': os.path.join(HERE, 'core-XIAO-04.pretty')}
DIAMETER = 10.0
THICKNESS = 0.8        # 基板の厚さ（mm）。DRV5032FC を裏面（磁石から遠い面）に置くので、薄くして磁石との距離を縮める

# (x, y, 回転, 裏面か)。x 右、y 下、円の中心が原点（mm）
PLAN = {
    # 表面には WS2812C だけを置く（表面の高さをそろえ、LED だけを見せる）。部品はすべて裏面（コア側）
    'D1': (0.0, 0.0, 0, False),        # WS2812C（北極 LED）。中心（極の軸の上）。charge-connector-06 の磁石の接点と同じ考え方
    # ケーブルの線を直接はんだ付けする 5 つの穴。左端に 3 つ（1〜3 番）、右端に 2 つ（4、5 番）。原点は基板の中心。
    # 外のコネクタへは、線を引き出してつなぐので、並びは自由（足型 core-XIAO-04:SolderWire_5_3L2R）
    'J1': (0.0, 0.0, 0, False),
    'U1': (0.0, 0.0, 180, True),       # DRV5032FC（裏面、WS2812C の真裏 = 磁石の軸の上）
    'D2': (-1.9, -2.4, 0, True),       # 確認用 LED（赤、裏面）
    'R1': (1.9, -2.4, 0, True),        # 確認用 LED の抵抗（裏面）
    'C1': (-1.9, 2.4, 0, True),        # DRV5032FC の 0.1 µF（裏面）
    'C2': (1.9, 2.4, 0, True),         # WS2812C の 0.1 µF（裏面）
}
import json as _json
if os.environ.get('NORTH_PLAN'):       # 試行用：{"D1": [x, y, rot, back], ...} で上書きする
    PLAN.update({k: tuple(v) for k, v in _json.loads(os.environ['NORTH_PLAN']).items()})


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
                               'lcsc': fields.get('LCSC Part', '')}
    pins = {}
    for n in t.iter('net'):
        for x in n.iter('node'):
            pins[(x.get('ref'), x.get('pin'))] = n.get('name').lstrip('/')
    return comps, pins


def load_fp(fpid):
    lib, name = fpid.split(':')
    f = pcbnew.FootprintLoad(LIBS.get(lib, os.path.join(STOCK, f'{lib}.pretty')), name)
    if f is None:
        raise SystemExit(f'フットプリントが見つからない：{fpid}')
    f.SetFPID(pcbnew.LIB_ID(lib, name))
    return f


def build(out):
    comps, pins = read_netlist()
    uu = symbol_uuids(open(os.path.join(HERE, f'{NAME}.kicad_sch'), encoding='utf-8').read())
    missing = sorted(set(comps) - set(PLAN))
    if missing:
        raise SystemExit(f'配置の決まっていない部品：{missing}')
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(mm(THICKNESS))
    for name in sorted(set(pins.values())):
        board.Add(pcbnew.NETINFO_ITEM(board, name))
    c = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_CIRCLE)
    c.SetCenter(vec(0, 0))
    c.SetEnd(vec(DIAMETER / 2, 0))
    c.SetLayer(pcbnew.Edge_Cuts)
    c.SetWidth(mm(0.1))
    board.Add(c)
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
        board.Add(f)
        for pad in f.Pads():
            net = pins.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(board.FindNet(net))
        x, y, rot, back = PLAN[ref]
        f.SetPosition(vec(x, y))
        f.SetOrientationDegrees(rot)
        if back:
            f.Flip(f.GetPosition(), True)
    B.silk_text(board)
    pro = os.path.join(HERE, f'{NAME}.kicad_pro')
    keep = open(pro, encoding='utf-8').read()
    pcbnew.SaveBoard(out, board)
    open(pro, 'w', encoding='utf-8').write(keep)         # SaveBoard が既定値で書き直すので戻す
    print(f'{out}：部品 {len(comps)}、ネット {len(set(pins.values()))}')


if __name__ == '__main__':
    out = os.environ.get('NORTH_OUT') or os.path.join(HERE, f'{NAME}.kicad_pcb')
    if os.path.exists(out) and '--force' not in sys.argv:
        raise SystemExit(f'{out} は既にある。作り直すときは --force')
    if not os.environ.get('NORTH_OUT') and any(n.endswith('.lck') and 'north' in n and 'kicad_pcb' in n for n in os.listdir(HERE)):
        raise SystemExit('KiCad で PCB が開いている。閉じてから実行する')
    build(out)
