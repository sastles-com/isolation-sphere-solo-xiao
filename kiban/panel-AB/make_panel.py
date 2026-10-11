#!/usr/bin/env python3
"""基板A と基板B（boardB-reverse）を 1 枚の板にまとめた「面付け」用の PCB を作る。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/panel-AB/make_panel.py

元の基板（kicad/boardA、kicad/boardB-reverse）は書き換えない。出力：kiban/panel-AB/panel-AB.kicad_pcb

構成（JLCPCB の PCBA、「基板を顧客が面付けする」形式）
- 横並び：A を左（原点）、B を右。A の張り出し（x = ±22.86）と B の八角形の間は 2.5 mm 空ける
- 外周に枠（レール）：上下は 5 mm（搬送用）、左右は 3 mm。横幅を 100 mm 以内に収めるため。
  基板と枠の間は、横 2.5 mm、縦 3 mm 空け、幅 3 mm のタブでつなぐ
- タブには、基板の縁の近く（0.45 mm 内側）に 0.5 mm の穴（ミシン目）を 4 つ並べる。手で折って切り離す
- 枠の四隅にツーリング穴（2 mm、NPTH）、3 か所にフィデューシャル（銅 1 mm、マスク開口 2 mm。両面）
- 部品番号とネット名は、重ならないよう A_ / B_（ネットは B 側だけ B_）を付ける。LCSC 品番などの欄は、そのまま引き継ぐ
- BOM と部品位置ファイル（JLCPCB の PCBA 用）：表面実装の部品だけを入れる。スルーホールの部品（ヘッダ、テスト用ピン）と、
  ミシン目・ツーリング穴・フィデューシャル・ロゴは、BOM と部品位置ファイルから外す（HAND_SOLDER_THT）
- 座標の原点（補助原点）は、板の左下（枠の左下の角）。BOM と部品位置ファイルは、KiCad の「製造用ファイル」プラグインで作る：
  kiban/panel-AB/make_production.py
- 設計ルールは boardB-reverse のものを使う（最小線幅 0.15 mm）。panel-AB.kicad_pro があれば、それを使う
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
A_PCB = os.path.join(REPO, 'kiban', 'EasyEDA', 'kicad', 'boardA', 'boardA.kicad_pcb')
B_PCB = os.path.join(REPO, 'kiban', 'EasyEDA', 'kicad', 'boardB-reverse', 'boardB-reverse.kicad_pcb')
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
OUT = os.path.join(HERE, 'panel-AB.kicad_pcb')

GAP_X = 2.5                # 横方向の間隔（A と B の間、基板と左右の枠の間）
GAP_Y = 3.0                # 縦方向の間隔（基板と上下の枠の間）
RAIL_X = 3.0               # 左右の枠の幅（搬送には使わない。横幅を 100 mm 以内に収めるため細くした）
RAIL_Y = 5.0               # 上下の枠の幅（搬送に使う。JLCPCB の推奨 5 mm）
MAX_WIDTH = 100.0          # 板の横幅の上限（mm）
TAB = 3.0                  # タブの幅
A_HALF_X, A_HALF_Y = 22.86, 20.0
B_HALF = 20.0
B_CX = A_HALF_X + GAP_X + B_HALF        # B の中心の x
BITE_D, BITE_N, BITE_PITCH, BITE_IN = 0.5, 4, 0.75, 0.45
HAND_SOLDER_THT = True     # スルーホールの部品（ヘッダ、テスト用ピン）は手はんだ。BOM と部品位置ファイルから外す

INNER = (-(A_HALF_X + GAP_X), -(A_HALF_Y + GAP_Y), B_CX + B_HALF + GAP_X, A_HALF_Y + GAP_Y)   # 枠の内側
OUTER = (INNER[0] - RAIL_X, INNER[1] - RAIL_Y, INNER[2] + RAIL_X, INNER[3] + RAIL_Y)
assert OUTER[2] - OUTER[0] <= MAX_WIDTH, f'横幅 {OUTER[2] - OUTER[0]:.2f} mm が上限 {MAX_WIDTH} mm を超えている'


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def rect_poly(x0, y0, x1, y1):
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        s.Append(mm(x), mm(y))
    return s


def tabs():
    """(矩形, ミシン目の穴の中心のリスト) を返す。矩形は基板に 0.2 mm 重ねる。"""
    out = []
    ov = 0.2

    def bites_h(x_edge, ys, direction):          # 縦の縁（x = x_edge）から direction 方向のタブに、y に並べる
        return [(x_edge + direction * BITE_IN, y) for y in ys]

    def bites_v(y_edge, xs, direction):
        return [(x, y_edge + direction * BITE_IN) for x in xs]

    offs = [(-(BITE_N - 1) / 2 + i) * BITE_PITCH for i in range(BITE_N)]
    # A と B の間（y = ±5）
    for yc in (-5.0, 5.0):
        ys = [yc + o for o in offs]
        out.append((rect_poly(A_HALF_X - ov, yc - TAB / 2, B_CX - B_HALF + ov, yc + TAB / 2),
                    bites_h(A_HALF_X, ys, +1) + bites_h(B_CX - B_HALF, ys, -1)))
    # A の左（y = ±5）
    for yc in (-5.0, 5.0):
        ys = [yc + o for o in offs]
        out.append((rect_poly(INNER[0] - 0.5, yc - TAB / 2, -A_HALF_X + ov, yc + TAB / 2), bites_h(-A_HALF_X, ys, -1)))
    # A の上下（x = ±8）
    for xc in (-8.0, 8.0):
        xs = [xc + o for o in offs]
        out.append((rect_poly(xc - TAB / 2, INNER[1] - 0.5, xc + TAB / 2, -A_HALF_Y + ov), bites_v(-A_HALF_Y, xs, -1)))
        out.append((rect_poly(xc - TAB / 2, A_HALF_Y - ov, xc + TAB / 2, INNER[3] + 0.5), bites_v(A_HALF_Y, xs, +1)))
    # B の上下（x = B_CX ± 6）
    for xc in (B_CX - 6.0, B_CX + 6.0):
        xs = [xc + o for o in offs]
        out.append((rect_poly(xc - TAB / 2, INNER[1] - 0.5, xc + TAB / 2, -B_HALF + ov), bites_v(-B_HALF, xs, -1)))
        out.append((rect_poly(xc - TAB / 2, B_HALF - ov, xc + TAB / 2, INNER[3] + 0.5), bites_v(B_HALF, xs, +1)))
    # B の右（y = ±6）
    for yc in (-6.0, 6.0):
        ys = [yc + o for o in offs]
        out.append((rect_poly(B_CX + B_HALF - ov, yc - TAB / 2, INNER[2] + 0.5, yc + TAB / 2), bites_h(B_CX + B_HALF, ys, +1)))
    return out


def seg(board, a, b, layer=pcbnew.Edge_Cuts, w=0.1):
    s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(a)
    s.SetEnd(b)
    s.SetLayer(layer)
    s.SetWidth(mm(w))
    board.Add(s)


def draw_chain(board, chain):
    n = chain.PointCount()
    for i in range(n):
        seg(board, chain.CPoint(i), chain.CPoint((i + 1) % n))


def npth(board, ref, x, y, d):
    f = pcbnew.FOOTPRINT(board)
    f.SetReference(ref)
    f.GetField('Reference').SetVisible(False) if hasattr(f, 'GetField') else None
    p = pcbnew.PAD(f)
    p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    p.SetSize(pcbnew.VECTOR2I(mm(d), mm(d)))
    p.SetDrillSize(pcbnew.VECTOR2I(mm(d), mm(d)))
    ls = pcbnew.LSET.AllCuMask()
    ls.AddLayer(pcbnew.F_Mask)
    ls.AddLayer(pcbnew.B_Mask)
    p.SetLayerSet(ls)
    f.Add(p)
    f.SetAttributes(f.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_BOARD_ONLY)
    board.Add(f)
    f.SetPosition(vec(x, y))
    return f


def fiducial(board, ref, x, y, back):
    f = pcbnew.FOOTPRINT(board)
    f.SetReference(ref)
    p = pcbnew.PAD(f)
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    p.SetSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.B_Cu if back else pcbnew.F_Cu)
    ls.AddLayer(pcbnew.B_Mask if back else pcbnew.F_Mask)
    p.SetLayerSet(ls)
    p.SetLocalSolderMaskMargin(mm(0.5))
    f.Add(p)
    f.SetAttributes(f.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_BOARD_ONLY)
    board.Add(f)
    f.SetPosition(vec(x, y))
    return f


def sch_fields(pcb_path):
    """PCB と同じフォルダの回路図から、部品番号 → (値, LCSC 品番) を取る。PCB の欄は、足型ライブラリの古い値が残っていることがある。"""
    sch = pcb_path.replace('.kicad_pcb', '.kicad_sch')
    xml = '/tmp/panel_' + os.path.basename(sch) + '.xml'
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, sch],
                   capture_output=True, text=True, check=True)
    out = {}
    for c in ET.parse(xml).getroot().iter('comp'):
        f = {x.get('name'): (x.text or '') for x in c.iter('field')}
        out[c.get('ref')] = (c.findtext('value') or '', f.get('LCSC Part', '') or f.get('LCSC', ''))
    return out


def copy_board(src, dst, prefix, dx, nets, fields=None, report=None):
    """src の部品・配線・ビア・ゾーン・図形（外形を除く）を dst へ、x 方向に dx（mm）ずらして写す。"""
    move = vec(dx, 0)
    n = {'fp': 0, 'trk': 0, 'zone': 0, 'draw': 0}
    for f in src.GetFootprints():
        nf = pcbnew.FOOTPRINT(f)
        nf.SetReference(prefix + f.GetReferenceAsString())
        nf.SetPath(pcbnew.KIID_PATH())
        ref0 = f.GetReferenceAsString()
        if fields is not None and ref0 in fields:
            val, lcsc = fields[ref0]
            old = nf.GetFieldText('LCSC Part') if nf.HasField('LCSC Part') else ''
            if lcsc and old != lcsc:
                if report is not None:
                    report.append((prefix + ref0, val, old, lcsc))
                if nf.HasField('LCSC Part'):
                    nf.GetField('LCSC Part').SetText(lcsc)
                else:
                    fld = pcbnew.PCB_FIELD(nf, nf.GetNextFieldOrdinal(), 'LCSC Part')
                    fld.SetText(lcsc)
                    fld.SetVisible(False)
                    fld.SetLayer(pcbnew.F_Fab)
                    nf.Add(fld)
        for p in nf.Pads():
            name = p.GetNetname()
            p.SetNet(nets[name] if name in nets else dst.FindNet(''))
        nf.Move(move)
        attr = nf.GetAttributes()
        if HAND_SOLDER_THT and (attr & pcbnew.FP_THROUGH_HOLE) and not (attr & pcbnew.FP_SMD):
            nf.SetAttributes(attr | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        dst.Add(nf)
        n['fp'] += 1
    for t in src.GetTracks():
        name = t.GetNetname()
        d = t.Duplicate()
        d.SetNet(nets[name] if name in nets else dst.FindNet(''))
        d.Move(move)
        dst.Add(d)
        n['trk'] += 1
    for z in src.Zones():
        if z.GetIsRuleArea():
            d = z.Duplicate()
        else:
            d = z.Duplicate()
            d.SetNet(nets.get(z.GetNetname(), dst.FindNet('')))
        d.Move(move)
        dst.Add(d)
        n['zone'] += 1
    for g in src.GetDrawings():
        if g.GetLayer() == pcbnew.Edge_Cuts:
            continue
        d = g.Duplicate()
        d.Move(move)
        dst.Add(d)
        n['draw'] += 1
    return n


def main():
    a = pcbnew.LoadBoard(A_PCB)
    b = pcbnew.LoadBoard(B_PCB)
    # 外形（Edge.Cuts を多角形にしたもの。円弧は折れ線になる）
    pa = pcbnew.SHAPE_POLY_SET()
    a.GetBoardPolygonOutlines(pa, True)
    pb = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(pb, True)
    pb.Move(vec(B_CX, 0))
    solid = pcbnew.SHAPE_POLY_SET(pa)
    solid.BooleanAdd(pb)
    bites = []
    for poly, holes in tabs():
        solid.BooleanAdd(poly)
        bites += holes
    slots = rect_poly(*INNER)
    slots.BooleanSubtract(solid)

    panel = pcbnew.CreateEmptyBoard()
    panel.SetCopperLayerCount(4)
    panel.GetDesignSettings().SetBoardThickness(mm(1.6))
    nets_a, nets_b = {}, {}
    for src, nets, pre in ((a, nets_a, ''), (b, nets_b, 'B_')):
        for name in src.GetNetsByName().keys():
            name = str(name)
            if name and name not in nets:
                ni = pcbnew.NETINFO_ITEM(panel, pre + name)
                panel.Add(ni)
                nets[name] = ni
    fixed = []
    na = copy_board(a, panel, 'A_', 0.0, nets_a, sch_fields(A_PCB), fixed)
    nb = copy_board(b, panel, 'B_', B_CX, nets_b, sch_fields(B_PCB), fixed)
    print(f'LCSC 品番を、回路図の値で更新した部品 {len(fixed)} 個')
    for r in fixed[:60]:
        print('  ', r)

    # 外形：枠の外周と、枠の内側の抜き（基板・タブ以外の部分）
    x0, y0, x1, y1 = OUTER
    corners = [vec(x0, y0), vec(x1, y0), vec(x1, y1), vec(x0, y1)]
    for i in range(4):
        seg(panel, corners[i], corners[(i + 1) % 4])
    for i in range(slots.OutlineCount()):
        draw_chain(panel, slots.COutline(i))
        for j in range(slots.HoleCount(i)):
            draw_chain(panel, slots.CHole(i, j))
    # ミシン目、ツーリング穴、フィデューシャル
    for k, (x, y) in enumerate(bites, 1):
        npth(panel, f'MB{k}', x, y, BITE_D)
    my = (OUTER[1] + INNER[1]) / 2          # 上の枠の中心線
    ny = (OUTER[3] + INNER[3]) / 2          # 下の枠の中心線
    tx0, tx1 = OUTER[0] + RAIL_X + 3.0, OUTER[2] - RAIL_X - 3.0     # ツーリング穴は、上下の枠の両端（左右の枠は細いので使わない）
    for k, (x, y) in enumerate(((tx0, my), (tx1, my), (tx0, ny), (tx1, ny)), 1):
        npth(panel, f'TH{k}', x, y, 2.0)
    for k, (x, y) in enumerate(((-15.0, my), (B_CX + 10.0, my), (-15.0, ny)), 1):
        fiducial(panel, f'FID{k}F', x, y, False)
        fiducial(panel, f'FID{k}B', x, y, True)
    panel.GetDesignSettings().SetAuxOrigin(vec(OUTER[0], OUTER[3]))      # 補助原点 = 板の左下の角
    # 枠に印字（0.5 × 0.7 × 0.1）
    t = pcbnew.PCB_TEXT(panel)
    t.SetText('A | B-reverse  panel (2.5 mm gap, 3 mm tabs, mouse bites)')
    t.SetLayer(pcbnew.F_SilkS)
    t.SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.7)))
    t.SetTextThickness(mm(0.1))
    t.SetPosition(vec((INNER[0] + INNER[2]) / 2, ny))
    panel.Add(t)

    pro = os.path.join(HERE, 'panel-AB.kicad_pro')
    keep = open(pro, encoding='utf-8').read() if os.path.exists(pro) else None   # SaveBoard が既定値で書き直すので戻す
    pcbnew.SaveBoard(OUT, panel)
    # ゾーンは、保存したものを読み直してから塗る（作った直後の板で塗るとクラッシュする）
    panel = pcbnew.LoadBoard(OUT)
    pcbnew.ZONE_FILLER(panel).Fill(panel.Zones())
    pcbnew.SaveBoard(OUT, panel)
    if keep is not None:
        open(pro, 'w', encoding='utf-8').write(keep)
    bb = panel.GetBoardEdgesBoundingBox()
    print(f'{OUT}')
    print(f'A：部品 {na["fp"]}、配線・ビア {na["trk"]}、ゾーン {na["zone"]}、図形 {na["draw"]}')
    print(f'B：部品 {nb["fp"]}、配線・ビア {nb["trk"]}、ゾーン {nb["zone"]}、図形 {nb["draw"]}')
    print(f'ミシン目の穴 {len(bites)}、板の大きさ {pcbnew.ToMM(bb.GetWidth()):.2f} x {pcbnew.ToMM(bb.GetHeight()):.2f} mm、'
          f'枠の外側 {OUTER[2] - OUTER[0]:.2f} x {OUTER[3] - OUTER[1]:.2f}（横幅の上限 {MAX_WIDTH:.0f} mm）')


if __name__ == '__main__':
    main()
