#!/usr/bin/env python3
"""mother-ring-04 の自動配線（Freerouting）。KiCad 付属の Python で動かす。

  python3 route.py prep  <作業フォルダ>   # ネットクラスを入れ、残した配線をロックして、DSN を出す
  （Freerouting で配線して ses を作る）
  python3 route.py apply <作業フォルダ>   # ses を取り込み、面を塗り直して routed.kicad_pcb に保存

作業フォルダには mother-ring-04.kicad_pcb と mother-ring-04.kicad_pro を置く（元のファイルは書き換えない）。
4 層（旧の 2 層に、内層 In1 = GND、In2 = 3V3_LED の面を足す）。旧の外周の配線（残したもの）はロックして固定する。
外層の面（旧の 3V3_LED = 表、GND = 裏）はそのまま残す。信号は表面と裏面で配線する。

端のクリアランス（銅箔と外形・穴・長穴まで 0.5 mm）を守らせるため、配線用の板だけ、外形を EDGE_INSET（0.4 mm）縮める
（外形の外側は縮み、穴や長穴は広がる）。配線の結果は、元の外形の板へ取り込む。
"""
import json
import os
import sys

import pcbnew

NAME = 'mother-ring-04'
POWER = ['3V3_MCU', '3V3_AON']          # 0.4 mm（3V3_LED と GND は面で受ける）
EDGE_INSET = 0.4
mm = pcbnew.FromMM


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


def set_rules(work):
    p = os.path.join(work, f'{NAME}.kicad_pro')
    d = json.load(open(p))
    ns = d['net_settings']
    base = dict(ns['classes'][0])
    base.update(clearance=float(os.environ.get('MR_CLEARANCE', 0.2)), track_width=0.25, via_diameter=0.6, via_drill=0.3)
    c = dict(base)
    c.update(name='Power', track_width=0.4, clearance=float(os.environ.get('MR_CLEARANCE', 0.2)), via_diameter=0.7, via_drill=0.35, priority=1)
    ns['classes'] = [base, c]
    ns['netclass_patterns'] = [{'netclass': 'Power', 'pattern': n} for n in POWER]
    sev = d['board']['design_settings'].setdefault('rule_severities', {})
    sev['solder_mask_bridge'] = 'ignore'       # ポゴ接点の表（DIN）と裏（DOUT）が同じ位置にある（旧と同じ）
    json.dump(d, open(p, 'w'), indent=2)


def add_cap_vias(b):
    """平滑用のコンデンサ（C1〜C5）の各パッドから、外側へ 1.3 mm のところにビアを置き、短い配線でつなぐ。
    3V3_LED と GND の内層の面へ落とす（自動配線に、パッドのそばでビアを置かせると失敗するため）。"""
    import math
    for f in list(b.GetFootprints()):
        if not f.GetReferenceAsString().startswith('C'):
            continue
        pads = list(f.Pads())
        c = f.GetPosition()
        for pad in pads:
            q = pad.GetPosition()
            dx, dy = q.x - c.x, q.y - c.y
            n = math.hypot(dx, dy)
            ux, uy = dx / n, dy / n
            vx, vy = q.x + int(ux * mm(1.3)), q.y + int(uy * mm(1.3))
            net = b.FindNet(pad.GetNetname())
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(q)
            t.SetEnd(pcbnew.VECTOR2I(vx, vy))
            t.SetWidth(mm(0.4))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(net)
            b.Add(t)
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(vx, vy))
            v.SetWidth(mm(0.6))
            v.SetDrill(mm(0.3))
            v.SetNet(net)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            b.Add(v)


def add_plane(b, layer, net, outline):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(b.FindNet(net))
    o = z.Outline()
    o.NewOutline()
    for i in range(outline.PointCount()):
        q = outline.CPoint(i)
        o.Append(q.x, q.y)
    z.SetMinThickness(mm(0.2))
    z.SetLocalClearance(mm(0.3))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.Add(z)


if __name__ == '__main__':
    stage, work = sys.argv[1], sys.argv[2]
    pcb = os.path.join(work, f'{NAME}.kicad_pcb')
    if stage == 'prep':
        set_rules(work)
        b = pcbnew.LoadBoard(pcb)
        ol = pcbnew.SHAPE_POLY_SET()
        b.GetBoardPolygonOutlines(ol, True)
        for t in b.GetTracks():
            t.SetLocked(True)
        if os.environ.get('MR_LAYERS', '4') == '4':
            b.SetCopperLayerCount(4)
            b.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
            b.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
            add_plane(b, pcbnew.In1_Cu, 'GND', ol.COutline(0))
            add_plane(b, pcbnew.In2_Cu, '3V3_LED', ol.COutline(0))
        pcbnew.SaveBoard(os.path.join(work, 'with_planes.kicad_pcb'), b)
        import shutil
        shutil.copy(os.path.join(work, f'{NAME}.kicad_pro'), os.path.join(work, 'with_planes.kicad_pro'))   # SaveBoard は既定値の .kicad_pro を作る
        # 配線用の板：Edge.Cuts を消して、縮めた外形（穴は広げた）を引き直す
        import re
        txt = open(os.path.join(work, 'with_planes.kicad_pcb'), encoding='utf-8').read()
        out, k = [], 0
        for m in re.finditer(r'\n\t\((gr_line|gr_arc|gr_circle|gr_rect)\n', txt):
            if m.start() < k:
                continue
            e = block_end(txt, m.start() + 1)
            if '(layer "Edge.Cuts")' in txt[m.start():e]:
                out.append(txt[k:m.start()])
                k = e
        out.append(txt[k:])
        txt = ''.join(out)
        # ロゴ（銅箔のない図形だけの足型）が入っていると DSN が書き出せない。配線用の板からは除く
        cut = []
        for m in re.finditer(r'\n\t\(footprint[\s"]', txt):
            a = m.start() + 2
            e = block_end(txt, a)
            if '"G***"' in txt[a:e]:
                cut.append((a, e))
        for a, e in sorted(cut, reverse=True):
            txt = txt[:txt.rindex('\n', 0, a)] + txt[e:]
        out = [txt]
        open(os.path.join(work, 'for_route.kicad_pcb'), 'w', encoding='utf-8').write(''.join(out))
        shutil.copy(os.path.join(work, f'{NAME}.kicad_pro'), os.path.join(work, 'for_route.kicad_pro'))
        r = pcbnew.LoadBoard(os.path.join(work, 'for_route.kicad_pcb'))
        inset = pcbnew.SHAPE_POLY_SET(ol)
        inset.Deflate(mm(EDGE_INSET), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, mm(0.01))
        chains = [inset.COutline(i) for i in range(inset.OutlineCount())]
        for i in range(inset.OutlineCount()):
            chains += [inset.CHole(i, j) for j in range(inset.HoleCount(i))]
        for c in chains:
            n = c.PointCount()
            for i in range(n):
                sg = pcbnew.PCB_SHAPE(r, pcbnew.SHAPE_T_SEGMENT)
                sg.SetStart(c.CPoint(i))
                sg.SetEnd(c.CPoint((i + 1) % n))
                sg.SetLayer(pcbnew.Edge_Cuts)
                sg.SetWidth(mm(0.1))
                r.Add(sg)
        pcbnew.SaveBoard(os.path.join(work, 'for_route.kicad_pcb'), r)
        shutil.copy(os.path.join(work, f'{NAME}.kicad_pro'), os.path.join(work, 'for_route.kicad_pro'))
        r = pcbnew.LoadBoard(os.path.join(work, 'for_route.kicad_pcb'))
        print('DSN', 'OK' if pcbnew.ExportSpecctraDSN(r, os.path.join(work, f'{NAME}.dsn')) else 'NG')
    else:
        b = pcbnew.LoadBoard(os.path.join(work, 'with_planes.kicad_pcb'))
        print('SES', 'OK' if pcbnew.ImportSpecctraSES(b, os.path.join(work, f'{NAME}.ses')) else 'NG')
        pcbnew.SaveBoard(os.path.join(work, 'routed.kicad_pcb'), b)
        b = pcbnew.LoadBoard(os.path.join(work, 'routed.kicad_pcb'))
        for t in b.GetTracks():
            t.SetLocked(False)
            if t.GetClass() != 'PCB_VIA' and t.GetWidth() < mm(0.2):       # 自動配線がパッドの出口で細くした配線
                t.SetWidth(mm(0.25))
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        pcbnew.SaveBoard(os.path.join(work, 'routed.kicad_pcb'), b)
        print('tracks', len([t for t in b.GetTracks() if t.GetClass() != 'PCB_VIA']), 'vias', len([t for t in b.GetTracks() if t.GetClass() == 'PCB_VIA']))
