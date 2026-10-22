#!/usr/bin/env python3
"""mother-ring-04 の PCB を、旧 mother-ring の PCB から作る。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/mother-ring-04/make_pcb.py <出力先.kicad_pcb>

旧の外周（外形、窓、長穴、取り付け穴、ポゴ接点 J1〜J5、33 Ω の R1〜R5、ロゴ、DIN の配線、面）は、そのまま残す。
変えるのは次だけ。
  1. 中央（半径 31 mm より内側）の部品、配線、ビア、シルクの文字を取り除く（J6〜J16、C10〜C12、FB1）
  2. 現行の基板との接続を置く：J6 / J7 = 基板A の J1 / J2（1×6、裏面、x = ±21.59）、
     J8 / J9 = core-XIAO-04 の J1 / J2（1×7、表面、y = ±21.59）。core は基板A に対して 90° 回す
  3. ネット名：+5V → 3V3_LED、GPIO01〜05 → LED_D1〜D5（旧 GPIO の配線は消す。引き直しは route.py）
配線（中央の信号）は含まない。2 層のまま。
"""
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
NAME = 'mother-ring-04'
OLD = os.path.join(REPO, 'kiban', 'mother-ring-bk', 'mother-ring.kicad_pcb')   # ポゴ接点が 7 パッド（貫通 THR、DIN は表、DOUT は裏）の版
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
STOCK = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints'
R_CENTRAL = 31.0
WINDOW = 15.0                # 中央の窓（旧は 19 = 38 mm 角）。30 mm 角に変更（2026-10-12 の指示）
BOARD_A_HOLES = [(sx * 18.0, sy * 18.0) for sx in (-1, 1) for sy in (-1, 1)]     # 基板A の四隅のネジ穴（Ø2.8）
J17 = (2.75, -36.05)         # 旧の J17（最後の DOUT05 の取り出し口）の位置。まわりの配線も消す
REMOVE_REFS = {f'J{i}' for i in range(6, 18)} | {'C10', 'C11', 'C12', 'FB1'} | {f'R{i}' for i in range(1, 6)}
REMOVE_TEXTS = {'BATTERY', 'POWER', 'ESP32', 'LED'}
RENAME = {'+5V': '3V3_LED', **{f'GPIO0{i}': f'LED_D{i}' for i in range(1, 6)}, **{f'DIN0{i}': f'LED_D{i}' for i in range(1, 6)}}
DROP_NETS = set(RENAME.values()) - {'3V3_LED'}          # LED_D1〜D5 の配線は引き直す
# ソケット：(足型、1 番ピンの位置、2 番ピンの位置、裏面か)
SOCKETS = {
    'J6': ('Connector_PinSocket_2.54mm:PinSocket_1x06_P2.54mm_Vertical', (-21.59, 6.35), (-21.59, 3.81), True),
    'J7': ('Connector_PinSocket_2.54mm:PinSocket_1x06_P2.54mm_Vertical', (21.59, 6.35), (21.59, 3.81), True),
    'J8': ('Connector_PinSocket_2.54mm:PinSocket_1x07_P2.54mm_Vertical', (-7.62, -21.59), (-5.08, -21.59), False),
    'J9': ('Connector_PinSocket_2.54mm:PinSocket_1x07_P2.54mm_Vertical', (-7.62, 21.59), (-5.08, 21.59), False),
}


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def block_end(s, i):
    d, k = 0, i
    while True:
        c = s[k]
        if c == '"':
            k += 1
            while s[k] != '"':
                k += 2 if s[k] == '\\' else 1
        elif c == '(':
            d += 1
        elif c == ')':
            d -= 1
            if d == 0:
                return k + 1
        k += 1


def strip_old(txt):
    """文字列の加工：中央の部品・配線・文字を消し、ネット名を換える。"""
    cut = []
    for m in re.finditer(r'\n\t\((footprint|segment|via|arc|gr_text)[\s"]', txt):
        a = m.start() + 2
        b = block_end(txt, a)
        blk = txt[a:b]
        kind = m.group(1)
        drop = False
        if kind == 'footprint':
            ref = re.search(r'\(property "Reference" "([^"]+)"', blk).group(1)
            drop = ref in REMOVE_REFS
        elif kind == 'gr_text':
            t = re.match(r'\(gr_text "([^"]*)"', blk)
            drop = bool(t) and t.group(1) in REMOVE_TEXTS
        else:
            pts = [(float(x), float(y)) for x, y in re.findall(r'\((?:start|end|at|mid) ([-\d.]+) ([-\d.]+)', blk)]
            net = re.search(r'\(net "([^"]*)"', blk)
            net = RENAME.get(net.group(1), net.group(1)) if net else ''
            drop = any(math.hypot(x, y) < R_CENTRAL or math.hypot(x - J17[0], y - J17[1]) < 5.0 for x, y in pts) \
                or net in DROP_NETS
        if drop:
            cut.append((a, b))
    for a, b in sorted(cut, reverse=True):
        txt = txt[:txt.rindex('\n', 0, a)] + txt[b:]
    for old, new in RENAME.items():
        txt = txt.replace(f'(net "{old}")', f'(net "{new}")')
    print(f'除去 {len(cut)} 件')
    return txt


def read_pins(sch):
    xml = f'/tmp/{NAME}_pcb.xml'
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, sch],
                   capture_output=True, text=True, check=True)
    t = ET.parse(xml).getroot()
    pins = {}
    for n in t.iter('net'):
        for x in n.iter('node'):
            pins[(x.get('ref'), x.get('pin'))] = n.get('name').lstrip('/')
    return pins


def load_fp(fpid):
    lib, name = fpid.split(':')
    f = pcbnew.FootprintLoad(os.path.join(STOCK, f'{lib}.pretty'), name)
    if f is None:
        raise SystemExit(f'フットプリントが見つからない：{fpid}')
    f.SetFPID(pcbnew.LIB_ID(lib, name))
    return f


def solve_rotation(fpid, pin1, pin2, back):
    want = (pin2[0] - pin1[0], pin2[1] - pin1[1])
    for rot in (0, 90, 180, 270):
        f = load_fp(fpid)
        f.SetPosition(vec(*pin1))
        f.SetOrientationDegrees(rot)
        p = {pd.GetNumber(): pd.GetPosition() for pd in f.Pads()}
        d = (pcbnew.ToMM(p['2'].x - p['1'].x), pcbnew.ToMM(p['2'].y - p['1'].y))
        if back:
            d = (-d[0], d[1])
        if abs(d[0] - want[0]) < 0.01 and abs(d[1] - want[1]) < 0.01:
            return rot
    raise SystemExit(f'回転が決まらない：{fpid} {pin1} {pin2}')


def main(out):
    work = os.path.dirname(os.path.abspath(out))
    tmp = os.path.join(work, '_stripped.kicad_pcb')
    open(tmp, 'w', encoding='utf-8').write(strip_old(open(OLD, encoding='utf-8').read()))
    pins = read_pins(os.environ.get('MR_SCH') or os.path.join(HERE, f'{NAME}.kicad_sch'))
    uu = {}                                  # 部品番号 → 回路図の記号の uuid（make_sch.py の uid と同じ）
    import uuid
    for ref in SOCKETS:
        uu[ref] = str(uuid.uuid5(uuid.NAMESPACE_URL, f'/{NAME}/{ref}'.lstrip('/')))
    rots = {ref: solve_rotation(fp, p1, p2, back) for ref, (fp, p1, p2, back) in SOCKETS.items()}
    new = {ref: load_fp(fp) for ref, (fp, *_r) in SOCKETS.items()}      # LoadBoard のあとでは足型が読めない版がある
    b = pcbnew.LoadBoard(tmp)
    for n in sorted(set(pins.values())):
        if not b.FindNet(n):
            b.Add(pcbnew.NETINFO_ITEM(b, n))
    for g in list(b.GetDrawings()):                     # 中央の窓：旧の 38 mm 角を 32 mm 角にする
        if g.GetLayer() == pcbnew.Edge_Cuts and g.GetShapeStr() == 'Rect' and abs(pcbnew.ToMM(g.GetWidth()) - 0) >= 0:
            s, e = g.GetStart(), g.GetEnd()
            if abs(pcbnew.ToMM(e.x - s.x)) == 38 or abs(pcbnew.ToMM(e.x - s.x)) == 38.0:
                g.SetStart(vec(-WINDOW, -WINDOW))
                g.SetEnd(vec(WINDOW, WINDOW))
    for x, y in BOARD_A_HOLES:                         # 基板A のネジを通す穴（取り付け穴と同じ Ø2.8）
        c = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_CIRCLE)
        c.SetCenter(vec(x, y))
        c.SetEnd(vec(x + 1.4, y))
        c.SetLayer(pcbnew.Edge_Cuts)
        c.SetWidth(mm(0.1))
        b.Add(c)
    for ref, f in new.items():
        fp, p1, p2, back = SOCKETS[ref]
        f.SetReference(ref)
        f.SetValue({'J6': 'A-LEFT', 'J7': 'A-RIGHT', 'J8': 'CORE-J1', 'J9': 'CORE-J2'}[ref])
        f.SetPath(pcbnew.KIID_PATH(f'/{uu[ref]}'))
        f.SetSheetname('/')
        f.SetSheetfile(f'{NAME}.kicad_sch')
        b.Add(f)
        for pad in f.Pads():
            net = pins.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(b.FindNet(net))
        f.SetPosition(vec(*p1))
        f.SetOrientationDegrees(rots[ref])
        if back:
            f.Flip(f.GetPosition(), getattr(pcbnew, 'FLIP_DIRECTION_LEFT_RIGHT', True))
    pro = os.path.join(work, f'{NAME}.kicad_pro')
    keep = open(pro, encoding='utf-8').read() if os.path.exists(pro) else None
    pcbnew.SaveBoard(out, b)
    if keep is not None:
        open(pro, 'w', encoding='utf-8').write(keep)
    os.remove(tmp)
    print(out, '部品', len(list(b.GetFootprints())))


if __name__ == '__main__':
    main(sys.argv[1])
