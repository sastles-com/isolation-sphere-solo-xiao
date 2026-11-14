#!/usr/bin/env python3
"""基板A（boardA）の回路図から PCB を作る：部品配置と、電源経路の配線。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/power-AB-02/tools/pcb_boardA.py

出力：kiban/power-AB-02/boardA/boardA.kicad_pcb（信号線は未配線。続けて route.py で配線する）。
**実行すると PCB を作り直す。KiCad で手直ししたあとは実行しない。**

初版（kiban/EasyEDA/kicad/boardA）と同じにしたもの：
- 外形（40 mm 角 ＋ 左右の張り出し、四隅の穴）。初版の PCB の Edge.Cuts をそのまま写す
- 4 層、表面実装の部品はすべて裏面（B.Cu）。表面はセルに接するので部品を置かない
- ヘッダ J1〜J4 の位置と向き。部品の位置も、下の MOVED 以外は初版のまま（FIRST）

初版から変えたもの：
- 電流の大きい経路（下の POWER）を、太い配線で引いてロックする。初版は 0.25〜0.9 mm 幅だった
  - VSYS：J3 → 入力コンデンサ → U4（LED 用降圧）、U3（MCU 用降圧）
  - 3V3_LED：L2 → 出力コンデンサ →（ビア）→ 表面 F.Cu の 2.2 mm 幅 → 左右の J1 / J2 の 1 番
- J11〜J15（別の mother-ring 基板へつなぐ 2.54 mm ピン）は**仮の位置**。相手の基板が決まったら動かす
- J7（3V3_MCU の確認ピン）は、3V3_LED の太い配線の通り道を空けるために動かした

層：B.Cu = 部品と電源、In2.Cu = GND 面（部品面のすぐ隣）、F.Cu = 3V3_LED の太い配線と信号、In1.Cu = 信号。
座標は基板の中心が原点、x 右、y 下（上から見た図）。
"""
import importlib.util
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
_argv, sys.argv = sys.argv, sys.argv[:1]
# 基板B 用の道具（ネットリスト、near_back）と、初版の道具 N.B（Fp、Placer）。どちらもファイル名が pcb_boardB.py なので、名前を変えて読む
_spec = importlib.util.spec_from_file_location('power_ab_02_boardB', os.path.join(HERE, 'pcb_boardB.py'))
N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N)
sys.argv = _argv
B = N.B

BOARD = 'boardA'
KIBAN = N.KIBAN
SCH = os.path.join(KIBAN, 'power-AB-02', BOARD, BOARD + '.kicad_sch')
OUT = os.path.join(KIBAN, 'power-AB-02', BOARD, BOARD + '.kicad_pcb')
FIRST_PCB = os.path.join(KIBAN, 'EasyEDA', 'kicad', 'boardA', 'boardA.kicad_pcb')
FP_DIR = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/'
LIBS = dict(N.LIBS, **{'Connector_PinHeader_2.54mm': FP_DIR + 'Connector_PinHeader_2.54mm.pretty'})
N.SCH = SCH
mm, tomm = pcbnew.FromMM, pcbnew.ToMM
VIA, VIA_PWR = (0.6, 0.3), (0.8, 0.4)
LAYERS = 4 if '--4layer' in sys.argv else 2      # 既定は 2 層。4 層版は boardA-4layer.kicad_pcb に残してある（作り直すときは --4layer で作って写す）
TAB_X, TAB_Y, HOLE = 22.86, 9.25, 18.0


def inside_board(x0, y0, x1, y1, margin=B.EDGE):
    h = 20.0 - margin
    in_square = -h <= x0 and x1 <= h and -h <= y0 and y1 <= h
    in_band = -(TAB_X - margin) <= x0 and x1 <= TAB_X - margin and -(TAB_Y - margin) <= y0 and y1 <= TAB_Y - margin
    return in_square or in_band


B.inside_board = inside_board

# ---------------------------------------------------------------- 配置（x, y, 回転, 裏面か）
# 初版の PCB から読んだ位置
FIRST = {
    'C1': (9.05, 4.88, 90), 'C10': (-8.66, 5.43, -90), 'C11': (-10.36, 5.38, -90), 'C12': (-13.29, -0.93, 180),
    'C13': (-13.36, 1.13, 180), 'C14': (-5.8, -5.9, 90), 'C15': (11.5, -5.5, 0), 'C16': (11.5, -7.85, 0),
    'C17': (11.5, -10.2, 0), 'C18': (11.5, -12.55, 0), 'C2': (12.9, 2.33, 0), 'C20': (-0.7, -5.9, -90),
    'C21': (-4.0, -12.2, -90), 'C22': (-6.0, -11.6, -90), 'C23': (-8.0, -11.6, -90), 'C24': (-10.0, -11.6, -90),
    'C3': (5.15, 2.77, 180), 'C4': (5.15, 4.53, 180), 'C5': (12.9, 0.47, 0), 'C6': (-16.35, -9.3, 90),
    'C7': (-13.2, -12.6, 180), 'C8': (-5.5, 5.75, -90), 'C9': (-3.3, 5.75, -90),
    'J3': (0.0, -16.5, 0), 'J4': (0.0, 16.5, 0), 'J8': (-16.2, 11.25, 180), 'J9': (-9.48, -0.49, 0),
    'J10': (6.55, 6.78, 180),
    'L1': (-4.55, 0.7, -90), 'L2': (4.8, -8.6, 0),
    'R1': (5.15, 0.33, 0), 'R2': (12.95, 4.03, 180), 'R3': (-13.73, 4.03, -90), 'R4': (-12.13, 4.03, 90),
    'R5': (-4.1, -5.9, 90), 'R6': (-5.25, -8.5, 180), 'R7': (-2.5, -5.9, -90),
    'U1': (9.04, 1.46, -90), 'U2': (-13.5, -9.25, 90), 'U3': (-9.62, 2.27, 90), 'U4': (-1.46, -9.35, 90),
}
FRONT = {'J1': (-21.59, 0.0, 90), 'J2': (21.59, 0.0, 90), 'J5': (-10.5, -17.2, 0), 'J6': (11.25, -17.25, 0)}   # 初版と同じ（表面）
MOVED = {
    'J7': (-13.0, 7.2, 180),             # 初版は (−16.25, 6.65)。3V3_LED の太い配線（F.Cu）が J1 へ下りる所に当たる
    # 仮の位置：別の mother-ring 基板へのピン
    'J11': (-5.08, 12.6, 0), 'J12': (-2.54, 12.6, 0), 'J13': (0.0, 12.6, 0), 'J14': (2.54, 12.6, 0), 'J15': (5.08, 12.6, 0),
    'R8': (-8.0, 14.3, 0),               # CHG_INT のプルアップ。初版の位置は J13 に当たる
}
# 自動で置く（つながる相手の近く）：C19（ブートストラップ。初版の位置は VSYS の太い配線に当たる）

# 太い配線：(ネット, 層, 幅, [点...])。細いピンからは、ピンと同じ幅で引き出してから太くする
BC, FC = pcbnew.B_Cu, pcbnew.F_Cu
POWER = [
    # --- VSYS：J3 の 1〜3 番 → 母線（y = −14.3）→ 入力コンデンサ C21〜C24 → U4 の VIN（5・6 番）
    ('VSYS', BC, 1.7, [(-6.35, -16.5), (-1.27, -16.5)]),
    ('VSYS', BC, 1.6, [(-10.0, -14.3), (-2.6, -14.3)]),
    ('VSYS', BC, 1.6, [(-6.35, -16.5), (-6.35, -14.3)]),
    ('VSYS', BC, 1.6, [(-3.81, -16.5), (-3.81, -14.3)]),
    ('VSYS', BC, 1.2, [(-10.0, -12.6), (-10.0, -14.3)]),
    ('VSYS', BC, 1.2, [(-8.0, -12.6), (-8.0, -14.3)]),
    ('VSYS', BC, 1.2, [(-6.0, -12.6), (-6.0, -14.3)]),
    ('VSYS', BC, 0.8, [(-4.0, -12.9), (-4.0, -14.3)]),
    ('VSYS', BC, 1.2, [(-2.6, -14.3), (-1.8, -13.5), (-1.8, -11.3)]),
    ('VSYS', BC, 0.75, [(-1.8, -11.3), (-1.8, -10.3)]),
    ('VSYS', BC, 1.0, [(-10.5, -17.2), (-10.5, -14.3), (-10.0, -14.3)]),          # J5（確認ピン）
    # --- VSYS：常時オン 3.3 V（U2、C7）と、MCU 用降圧の入力コンデンサ（C12、C13）
    ('VSYS', BC, 0.6, [(-10.5, -14.3), (-12.5, -14.3)]),
    ('VSYS', BC, 0.5, [(-12.5, -14.3), (-12.5, -10.6)]),
    ('VSYS', BC, 0.6, [(-11.3, -14.3), (-11.3, 1.13), (-12.66, 1.13)]),
    ('VSYS', BC, 0.6, [(-11.3, -0.93), (-12.29, -0.93)]),
    # --- GND：入力コンデンサの戻り → U4 の PGND（4 番）
    ('GND', BC, 1.0, [(-10.0, -10.1), (-3.6, -10.1)]),
    ('GND', BC, 0.8, [(-9.5, -9.3), (-7.1, -9.3)]),
    ('GND', BC, 0.5, [(-3.6, -10.1), (-3.0, -9.1)]),
    ('GND', BC, 0.25, [(-3.0, -9.1), (-2.0, -9.1)]),
    ('GND', BC, 0.6, [(-4.0, -11.5), (-4.0, -10.1)]),
    ('GND', BC, 0.5, [(-6.0, -8.5), (-6.0, -10.1)]),
    # --- L_SW：U4 の 8 番 → L2
    ('L_SW', BC, 0.25, [(-1.25, -9.6), (0.0, -9.6)]),
    ('L_SW', BC, 0.9, [(0.0, -9.6), (1.5, -9.6)]),
    # --- 3V3_LED：L2 → 出力コンデンサ C15〜C18 → ビア 6 個 → 表面（F.Cu）
    ('3V3_LED', BC, 3.0, [(7.6, -8.6), (9.3, -8.6)]),
    ('3V3_LED', BC, 1.2, [(10.4, -12.55), (10.4, -5.5)]),
    ('3V3_LED', BC, 2.0, [(10.0, -5.5), (10.0, -2.6)]),
    ('3V3_LED', FC, 2.2, [(10.0, -4.5), (10.0, 9.6)]),
    ('3V3_LED', FC, 2.2, [(-16.2, 9.6), (15.5, 9.6)]),
    ('3V3_LED', FC, 2.0, [(15.5, 9.6), (18.75, 6.35), (20.9, 6.35)]),             # → J2 の 1 番（張り出しの端に近いので、最後はパッドの幅）
    ('3V3_LED', FC, 1.6, [(20.9, 6.35), (21.4, 6.35)]),
    ('3V3_LED', FC, 2.0, [(-16.2, 9.6), (-19.45, 6.35), (-20.9, 6.35)]),          # → J1 の 1 番
    ('3V3_LED', FC, 1.6, [(-20.9, 6.35), (-21.4, 6.35)]),
    ('3V3_LED', FC, 1.0, [(-16.2, 11.25), (-16.2, 9.6)]),                         # J8（確認ピン）
    # --- GND：出力コンデンサの戻り
    ('GND', BC, 1.4, [(13.2, -12.55), (13.2, -5.5)]),
    # --- MCU 用降圧：M_SW（U3 の 5 番 → L1）、3V3_MCU（L1 → C8・C9 → ビア → 表面 → J1 の 3 番）
    # U3 の北側のピン（1〜4 番）は、まわりが詰まっていて自動配線では出し切れないので、すべて引いておく
    ('MCU_EN', BC, 0.15, [(-9.48, -0.49), (-9.87, 0.6), (-9.87, 1.5)]),          # J9 → 2 番
    ('VSYS', BC, 0.2, [(-9.37, 1.55), (-9.37, 0.8), (-9.07, 0.5), (-8.63, 0.5), (-8.48, 0.35), (-8.48, -1.35), (-8.83, -1.7), (-11.3, -1.7)]),   # 3 番。J9 の東を回る
    ('GND', BC, 0.25, [(-8.87, 1.63), (-8.15, 1.45)]),                            # 4 番 → 東のビア
    ('GND', BC, 0.25, [(-10.37, 1.7), (-10.86, 1.9)]),                            # U3 の 1 番（GND）
    ('M_SW', BC, 0.28, [(-8.87, 2.95), (-8.87, 3.6)]),
    ('M_SW', BC, 0.5, [(-8.87, 3.6), (-7.4, 3.6), (-7.4, -0.5), (-6.3, -0.9)]),
    ('3V3_MCU', BC, 1.0, [(-5.5, 4.75), (-5.5, 2.3)]),
    ('3V3_MCU', BC, 1.0, [(-3.3, 4.75), (-3.3, 2.3)]),
    ('3V3_MCU', BC, 0.8, [(-3.3, 3.5), (-1.9, 3.6)]),
    ('3V3_MCU', FC, 0.8, [(-1.9, 3.6), (-17.0, 3.6), (-19.3, 1.27), (-21.59, 1.27)]),
]
PWR_VIAS = [('3V3_LED', x, y) for x in (9.4, 10.6) for y in (-4.5, -3.4, -2.3)] + [('3V3_MCU', -1.9, 3.6)]
GND_VIAS = [(13.6, y) for y in (-12.55, -11.4, -10.2, -9.0, -7.85, -6.7, -5.5)] + \
           [(-9.5, -9.3), (-8.3, -9.3), (-7.1, -9.3), (-3.3, -10.3)]
CAP_VIAS = [('C8', '2', 0, 1.0), ('C9', '2', 0, 1.0)]        # (部品, ピン, dx, dy)
KEEP_OUT = []

# 機能ブロックの枠（部品面のシルクに点線）：(名前, 名前の位置, [枠の頂点...])
FRAMES = [
    ('LED BUCK', (5.0, -12.8), [(-10.9, -15.3), (14.4, -15.3), (14.4, -1.6), (8.4, -1.6), (8.4, -4.2), (-6.8, -4.2), (-6.8, -8.7), (-10.9, -8.7)]),
    ('3V3 AON', (-14.6, -14.2), [(-17.6, -14.9), (-11.7, -14.9), (-11.7, -7.0), (-17.6, -7.0)]),
    ('MCU BUCK', (-9.0, 7.8), [(-15.4, -2.3), (-1.2, -2.3), (-1.2, 4.4), (-2.3, 4.4), (-2.3, 8.5), (-15.4, 8.5)]),
    ('PWR SW', (11.9, 5.8), [(3.2, -0.9), (15.0, -0.9), (15.0, 6.4), (8.2, 6.4), (8.2, 8.3), (4.8, 8.3), (4.8, 5.4), (3.2, 5.4)]),
    ('EXT', (0.0, 10.55), [(-6.9, 10.0), (6.9, 10.0), (6.9, 14.3), (-6.9, 14.3)]),
]


def copy_outline(board):
    """初版の PCB の Edge.Cuts（外形と四隅の穴）を写す。"""
    first = pcbnew.LoadBoard(FIRST_PCB)
    for d in first.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts:
            continue
        s = pcbnew.PCB_SHAPE(board, d.GetShape())
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        if d.GetShape() == pcbnew.SHAPE_T_ARC:
            s.SetArcGeometry(d.GetStart(), d.GetArcMid(), d.GetEnd())
        else:
            s.SetStart(d.GetStart())
            s.SetEnd(d.GetEnd())
        board.Add(s)


def build():
    comps, nets = N.read_netlist()
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(LAYERS)
    board.GetDesignSettings().SetBoardThickness(mm(1.6))
    netmap = {}
    for name, pins in nets.items():
        board.Add(pcbnew.NETINFO_ITEM(board, name))
        for ref, pin in pins:
            netmap[(ref, pin)] = name
    copy_outline(board)

    parts = {}
    for ref, info in comps.items():
        B.PRETTY = LIBS[info['lib']]
        f = parts[ref] = B.Fp(ref, info, board, netmap)
        f.fp.SetFPID(pcbnew.LIB_ID(info['lib'], info['fp']))
        f.fp.SetPath(pcbnew.KIID_PATH(info['path']))
        f.fp.SetSheetname(info['sheet'])
        f.fp.SetSheetfile(BOARD + '.kicad_sch')
        if info['lcsc']:
            fld = pcbnew.PCB_FIELD(f.fp, f.fp.GetNextFieldOrdinal(), 'LCSC Part')
            fld.SetText(info['lcsc'])
            fld.SetVisible(False)
            fld.SetLayer(pcbnew.F_Fab)
            f.fp.Add(fld)

    pl = B.Placer()
    for sx in (-1, 1):                                   # 四隅の穴（半径 1.4 mm）
        for sy in (-1, 1):
            r = (sx * HOLE - 1.7, sy * HOLE - 1.7, sx * HOLE + 1.7, sy * HOLE + 1.7)
            pl.occ[True].append(r)
            pl.occ[False].append(r)
    fixed = {}
    fixed.update({k: v + (True,) for k, v in FIRST.items()})
    fixed.update({k: v + (False,) for k, v in FRONT.items()})
    fixed.update({k: v + (True,) for k, v in MOVED.items()})
    for ref, (x, y, rot, back) in fixed.items():
        pl.fixed(parts[ref], x, y, rot, back)

    def track(net, layer, w, a, b):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(B.vec(*a))
        t.SetEnd(B.vec(*b))
        t.SetWidth(mm(w))
        t.SetLayer(layer)
        t.SetNet(board.FindNet(net))
        t.SetLocked(True)
        board.Add(t)
        pl.occ[layer == BC].append(N.seg_rect(a, b, w))

    def via(net, x, y, size=VIA_PWR):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(B.vec(x, y))
        v.SetWidth(pcbnew.F_Cu, mm(size[0]))
        v.SetDrill(mm(size[1]))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(board.FindNet(net))
        v.SetLocked(True)
        board.Add(v)
        r = size[0] / 2
        pl.occ[True].append((x - r, y - r, x + r, y + r))

    for net, layer, w, line in POWER:
        for a, b in zip(line, line[1:]):
            track(net, layer, w, a, b)
    for net, x, y in PWR_VIAS:
        via(net, x, y)
    for x, y in GND_VIAS:
        via('GND', x, y)
    via('GND', -8.15, 1.45, (0.5, 0.3))                        # U3 の 4 番
    via('GND', -10.86, 1.9, (0.5, 0.3))                      # U3 の 1 番
    for ref, pin, dx, dy in CAP_VIAS:
        px, py = parts[ref].pad_pos(pin)
        assert netmap[(ref, pin)] == 'GND', (ref, pin)
        track('GND', BC, 0.6, (px, py), (px + dx, py + dy))
        via('GND', px + dx, py + dy, VIA)
    pl.occ[True].extend(KEEP_OUT)

    # 残りの部品：つながる相手（置き終わった部品のピン）のうち、いちばん小さいネットのピンの近くへ
    placed = set(fixed)
    by_ref = {}
    for (ref, pin), nm in netmap.items():
        by_ref.setdefault(ref, {})[pin] = nm
    rest = [r for r in parts if r not in placed]
    while rest:
        best = None
        for ref in rest:
            for pin, nm in by_ref.get(ref, {}).items():
                if nm == 'GND':
                    continue
                for r2, p2 in nets[nm]:
                    if r2 in placed:
                        key = (len(nets[nm]), ref)
                        if best is None or key < best[0]:
                            best = (key, ref, parts[r2].pad_pos(p2))
        assert best, f'つながる相手が置かれていない部品：{rest}'
        _, ref, (tx, ty) = best
        N.near_back(pl, parts[ref], tx, ty)
        placed.add(ref)
        rest.remove(ref)

    # GND 面（In2）。部品面（B.Cu）のすぐ隣の層
    # 2 層のときは、表面（F.Cu）と部品面（B.Cu）の空いた所を両方 GND で塗る
    for layer in ((pcbnew.In2_Cu,) if LAYERS == 4 else (pcbnew.F_Cu, pcbnew.B_Cu)):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(board.FindNet('GND'))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((-TAB_X, -20), (TAB_X, -20), (TAB_X, 20), (-TAB_X, 20)):     # 外形より大きく取る（塗りは外形で切られる）
            ol.Append(mm(x), mm(y))
        z.SetMinThickness(mm(0.2))
        z.SetLocalClearance(mm(0.2 if LAYERS == 4 else 0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        board.Add(z)

    B.silk_text(board)
    N.draw_frames(board, FRAMES)
    pro = OUT.replace('.kicad_pcb', '.kicad_pro')
    keep = open(pro, encoding='utf-8').read()          # SaveBoard が既定値で書き直すので戻す
    pcbnew.SaveBoard(OUT, board)
    open(pro, 'w', encoding='utf-8').write(keep)
    print(OUT)
    if '-v' in sys.argv:
        for ref in sorted(parts, key=lambda r: (r[0], int(''.join(c for c in r if c.isdigit()) or 0))):
            f = parts[ref]
            pads = ' '.join(f'{p.GetNumber()}:{p.GetNetname()}({tomm(p.GetPosition().x):.2f},{tomm(p.GetPosition().y):.2f})' for p in f.fp.Pads())
            print(f'  {ref:4} ({f.x:7.2f}, {f.y:7.2f}) rot {f.rot:4}  {pads}')


if __name__ == '__main__':
    build()
