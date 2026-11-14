#!/usr/bin/env python3
"""信号線の自動配線（Freerouting）。KiCad 付属の Python で動かす。pcb_boardB.py / pcb_boardA.py のあとに実行する。

  python3 route.py prep  boardB-reverse      # 作業フォルダへ写し、Specctra の DSN を出す
  java -jar freerouting.jar -de <作業フォルダ>/boardB-reverse.dsn -do <作業フォルダ>/boardB-reverse.ses -mp 80 -mt 0
  python3 route.py apply boardB-reverse      # 結果（SES）を取り込み、足りない GND ビアを足し、面を塗って、元の PCB に上書きする
  python3 route.py link  boardB-reverse CHG_G -12.33 2.24 -14.96 -8.93 F.Cu     # 残った 1 本を、1 つの層でつなぐ

作業フォルダは kiban/power-AB-02/route-work/<基板>（Git には入れない）。
4 層は In2.Cu（GND 面）を電源層にして配線させない。2 層は表と裏の GND の塗りを、apply がビアで縫う。
ロックした電源の配線とビアは、Freerouting は動かさない。
Freerouting は https://github.com/freerouting/freerouting/releases の jar（v2.1.0 で確認）。結果は毎回変わる。
配線が終わってから SES を書くまで 20 分ほど止まることがある。PCB を KiCad で開いていないときに実行する。
"""
import math
import os
import shutil
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))


def paths(name):
    src = os.path.join(ROOT, name, name + '.kicad_pcb')
    work = os.path.join(ROOT, 'route-work', name)
    return src, work, os.path.join(work, name + '.kicad_pcb'), os.path.join(work, name + '.dsn'), os.path.join(work, name + '.ses')


def prep(name):
    src, work, pcb, dsn, ses = paths(name)
    os.makedirs(work, exist_ok=True)
    shutil.copy(src, pcb)
    shutil.copy(src.replace('.kicad_pcb', '.kicad_pro'), pcb.replace('.kicad_pcb', '.kicad_pro'))   # ネットクラス（線幅・クリアランス）
    if os.path.exists(ses):
        os.remove(ses)
    b = pcbnew.LoadBoard(pcb)
    if b.GetCopperLayerCount() == 4:
        b.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    assert pcbnew.ExportSpecctraDSN(b, dsn), 'DSN を出せなかった'
    print(dsn)


def ground_vias(b, net='GND', via=(0.5, 0.3), w=0.25, clr=0.15):
    """GND 面（In2）につながっていない GND の表面実装パッドに、短い配線とビアを足す。

    Freerouting は、電源層へ落とすビアを打たないまま終わることがある。ビアの位置は、パッドのまわりで
    ほかのネットの銅箔（全層）と clr 以上離れる、いちばん近い点。
    """
    mm, tomm = pcbnew.FromMM, pcbnew.ToMM
    code = b.FindNet(net).GetNetCode()
    P = lambda v: (tomm(v.x), tomm(v.y))

    def seg_d(p, a, c):
        (px, py), (ax, ay), (cx, cy) = p, a, c
        dx, dy = cx - ax, cy - ay
        t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    def rect_d(p, r):
        return math.hypot(max(r[0] - p[0], 0, p[0] - r[2]), max(r[1] - p[1], 0, p[1] - r[3]))

    def rect(pd):
        bb = pd.GetBoundingBox()
        return (tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom()))

    pads = [(pd, rect(pd)) for pd in b.GetPads()]
    tracks = [t for t in b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T]
    vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
    poly = pcbnew.SHAPE_POLY_SET()
    assert b.GetBoardPolygonOutlines(poly, False)
    ol = poly.Outline(0)
    edge = [P(ol.CPoint(i)) for i in range(ol.PointCount())]

    def in_board(p, margin):
        inside = False
        for a, c in zip(edge, edge[1:] + edge[:1]):
            if seg_d(p, a, c) < margin:
                return False
            if (a[1] > p[1]) != (c[1] > p[1]) and p[0] < a[0] + (p[1] - a[1]) * (c[0] - a[0]) / (c[1] - a[1]):
                inside = not inside
        return inside

    def free(p, r, layer=None):
        """中心 p、半径 r の銅箔を置けるか。layer が None なら全層（ビア）、そうでなければその層だけ。"""
        if not in_board(p, r + 0.5):
            return False
        for pd, rc in pads:
            through = pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or pd.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
            if not through and layer is not None and not pd.IsOnLayer(layer):
                continue
            if pd.GetNetCode() == code and layer is not None:
                continue
            gap = clr if pd.GetNetCode() != code else 0.1          # ビアは、同じ GND のパッドにも重ねない（はんだが流れる）
            if pd.GetShape(pcbnew.F_Cu if pd.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu) == pcbnew.PAD_SHAPE_CIRCLE:   # 丸いパッドは、外接する四角ではなく円で測る
                c = ((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2)
                if math.hypot(p[0] - c[0], p[1] - c[1]) < (rc[2] - rc[0]) / 2 + r + gap:
                    return False
            elif rect_d(p, rc) < r + gap:
                return False
        for t in tracks:
            if t.GetNetCode() == code or (layer is not None and t.GetLayer() != layer):
                continue
            if seg_d(p, P(t.GetStart()), P(t.GetEnd())) < r + tomm(t.GetWidth()) / 2 + clr:
                return False
        for v in vias + added:
            vp, vr = P(v.GetPosition()), tomm(v.GetWidth(pcbnew.F_Cu)) / 2
            d = math.hypot(p[0] - vp[0], p[1] - vp[1])
            if layer is None and d < 0.3 + 0.25 + 0.15:                        # 穴どうし
                return False
            if v.GetNetCode() != code and d < r + vr + clr:
                return False
        return True

    # GND のかたまりを作る（パッド・配線・ビアが触れていれば同じ）。ビアかスルーホールがあれば面につながる
    items = [('pad', pd, rc) for pd, rc in pads if pd.GetNetCode() == code] + \
            [('trk', t, None) for t in tracks if t.GetNetCode() == code] + [('via', v, None) for v in vias if v.GetNetCode() == code]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def touch(a, c):
        (ka, ia, ra), (kc, ic, rc) = a, c
        if ka == 'pad' and kc == 'pad':
            return False
        if ka != 'pad' and kc == 'pad':
            return touch(c, a)
        if ka == 'pad':
            if kc == 'via':
                pts = [P(ic.GetPosition())]
            else:                                            # 線の途中がパッドを通る場合もあるので、0.05 mm ごとに調べる
                a0, a1 = P(ic.GetStart()), P(ic.GetEnd())
                n = max(1, int(math.hypot(a1[0] - a0[0], a1[1] - a0[1]) / 0.05))
                pts = [(a0[0] + (a1[0] - a0[0]) * k / n, a0[1] + (a1[1] - a0[1]) * k / n) for k in range(n + 1)]
            if kc == 'trk' and not ia.IsOnLayer(ic.GetLayer()):
                return False
            return any(rect_d(p, ra) < 0.01 for p in pts)
        if ka == 'via' and kc == 'via':
            return False
        if ka == 'via':
            return touch(c, a)
        if kc == 'via':
            return seg_d(P(ic.GetPosition()), P(ia.GetStart()), P(ia.GetEnd())) < tomm(ia.GetWidth()) / 2
        if ia.GetLayer() != ic.GetLayer():
            return False
        return any(seg_d(p, P(ic.GetStart()), P(ic.GetEnd())) < 0.01 for p in (P(ia.GetStart()), P(ia.GetEnd()))) or \
            any(seg_d(p, P(ia.GetStart()), P(ia.GetEnd())) < 0.01 for p in (P(ic.GetStart()), P(ic.GetEnd())))

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if touch(items[i], items[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)

    added = []
    side = lambda pd: pcbnew.B_Cu if pd.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu      # 裏返した部品でも pd.GetLayer() は F.Cu を返す
    for g in groups.values():
        if any(k == 'via' or (k == 'pad' and i.GetAttribute() == pcbnew.PAD_ATTRIB_PTH) for k, i, _ in g):
            continue
        gpads = [(i, rc) for k, i, rc in g if k == 'pad']
        if not gpads:
            continue
        best = None
        for pd, rc in gpads:
            c = ((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2)
            for d in [x * 0.05 for x in range(10, 61)]:
                for ang in range(0, 360, 5):
                    p = (c[0] + d * math.cos(math.radians(ang)), c[1] + d * math.sin(math.radians(ang)))
                    if best and d >= best[0]:
                        continue
                    n = max(1, int(d / 0.05))
                    if free(p, via[0] / 2) and all(free((c[0] + (p[0] - c[0]) * k / n, c[1] + (p[1] - c[1]) * k / n), w / 2, side(pd)) for k in range(n + 1)):
                        best = (d, c, p, pd)
        name = '、'.join(f'{pd.GetParentFootprint().GetReference()}.{pd.GetNumber()}' for pd, _ in gpads)
        if not best and b.GetCopperLayerCount() == 2:       # 2 層は部品面も GND で塗るので、ビアが無くてもつながることが多い（DRC で確かめる）
            print(f'  GND ビアを置けない：{name}')
            continue
        assert best, f'{name}: GND ビアを置ける場所がない'
        _, c, p, pd = best
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I(mm(c[0]), mm(c[1])))
        t.SetEnd(pcbnew.VECTOR2I(mm(p[0]), mm(p[1])))
        t.SetWidth(mm(w))
        t.SetLayer(side(pd))
        t.SetNetCode(code)
        b.Add(t)
        tracks.append(t)
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(mm(p[0]), mm(p[1])))
        v.SetWidth(pcbnew.F_Cu, mm(via[0]))
        v.SetDrill(mm(via[1]))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(code)
        b.Add(v)
        added.append(v)
        print(f'  GND ビアを追加：{name} → ({p[0]:.2f}, {p[1]:.2f})')


def link(name, net, x1, y1, x2, y2, layer='F.Cu', w=0.15, clr=0.15, step=0.1):
    """自動配線が残した 1 本を、1 つの層の上でつなぐ（格子の最短経路）。両端はビアかスルーホールの位置。

      python3 route.py link boardB-reverse CHG_G -12.33 2.24 -14.96 -8.93 F.Cu
    """
    import heapq
    mm, tomm = pcbnew.FromMM, pcbnew.ToMM
    src = paths(name)[0]
    b = pcbnew.LoadBoard(src)
    code = b.FindNet(net).GetNetCode()
    lay = b.GetLayerID(layer)
    P = lambda v: (tomm(v.x), tomm(v.y))
    a, z = (float(x1), float(y1)), (float(x2), float(y2))
    segs, circles, rects = [], [], []                    # ほかのネットの銅箔（この層にあるもの）
    for t in b.GetTracks():
        if t.GetNetCode() == code:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            circles.append((P(t.GetPosition()), tomm(t.GetWidth(lay)) / 2))
        elif t.GetLayer() == lay:
            segs.append((P(t.GetStart()), P(t.GetEnd()), tomm(t.GetWidth()) / 2))
    for pd in b.GetPads():
        if pd.GetNetCode() == code or not pd.IsOnLayer(lay):
            continue
        bb = pd.GetBoundingBox()
        rects.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
    poly = pcbnew.SHAPE_POLY_SET()
    assert b.GetBoardPolygonOutlines(poly, False)
    ol = poly.Outline(0)
    edge = [P(ol.CPoint(i)) for i in range(ol.PointCount())]
    r = w / 2 + clr

    def seg_d(p, s, e):
        dx, dy = e[0] - s[0], e[1] - s[1]
        t = 0 if dx == dy == 0 else max(0, min(1, ((p[0] - s[0]) * dx + (p[1] - s[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[0] - s[0] - t * dx, p[1] - s[1] - t * dy)

    ok = {}

    def free(c):
        if c not in ok:
            p = (a[0] + c[0] * step, a[1] + c[1] * step)
            ok[c] = all(seg_d(p, s, e) >= r + hw for s, e, hw in segs) and \
                all(math.hypot(p[0] - q[0], p[1] - q[1]) >= r + cr for q, cr in circles) and \
                all(math.hypot(max(rc[0] - p[0], 0, p[0] - rc[2]), max(rc[1] - p[1], 0, p[1] - rc[3])) >= r for rc in rects) and \
                all(seg_d(p, s, e) >= w / 2 + 0.5 for s, e in zip(edge, edge[1:] + edge[:1]))
        return ok[c]

    goal = (round((z[0] - a[0]) / step), round((z[1] - a[1]) / step))
    ok[(0, 0)] = ok[goal] = True
    lim = max(abs(goal[0]), abs(goal[1])) + 80
    dist, prev, heap = {(0, 0): 0.0}, {}, [(0.0, (0, 0))]
    while heap:
        _, c = heapq.heappop(heap)
        if c == goal:
            break
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (c[0] + dx, c[1] + dy)
                if (dx or dy) and abs(n[0]) <= lim and abs(n[1]) <= lim and free(n):
                    d = dist[c] + math.hypot(dx, dy) + (0.3 if c in prev and (c[0] - prev[c][0], c[1] - prev[c][1]) != (dx, dy) else 0)
                    if d < dist.get(n, 1e9):
                        dist[n], prev[n] = d, c
                        heapq.heappush(heap, (d + math.hypot(goal[0] - n[0], goal[1] - n[1]), n))
    assert goal in prev, f'{net}: {layer} ではつなげない'
    cells = [goal]
    while cells[-1] != (0, 0):
        cells.append(prev[cells[-1]])
    pts = [cells[0]]                                     # 同じ向きの続きは 1 本にまとめる
    for i in range(1, len(cells) - 1):
        if (cells[i][0] - cells[i - 1][0], cells[i][1] - cells[i - 1][1]) != (cells[i + 1][0] - cells[i][0], cells[i + 1][1] - cells[i][1]):
            pts.append(cells[i])
    pts.append(cells[-1])
    xy = [(a[0] + c[0] * step, a[1] + c[1] * step) for c in pts]
    xy[0], xy[-1] = z, a
    for s, e in zip(xy, xy[1:]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I(mm(s[0]), mm(s[1])))
        t.SetEnd(pcbnew.VECTOR2I(mm(e[0]), mm(e[1])))
        t.SetWidth(mm(w))
        t.SetLayer(lay)
        t.SetNetCode(code)
        b.Add(t)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pro = src.replace('.kicad_pcb', '.kicad_pro')
    keep = open(pro, encoding='utf-8').read()
    pcbnew.SaveBoard(src, b)
    open(pro, 'w', encoding='utf-8').write(keep)
    print(f'{net}: {layer} に {len(xy) - 1} 本')


def stitch(b, net='GND', via=(0.6, 0.3), per_link=4):
    """2 層：表と裏の GND の塗りが、島に分かれてつながっていない所を、ビアで縫う。

    塗りの島（表・裏）を、GND のビアとスルーホールで結んだグラフにして、かたまりが 1 つになるまで、
    表の島と裏の島が重なる所にビアを足す（1 か所につき per_link 個まで）。ビアは両面とも塗りの中に置くので、ほかのネットには当たらない。
    """
    mm, tomm = pcbnew.FromMM, pcbnew.ToMM
    code = b.FindNet(net).GetNetCode()
    filler = pcbnew.ZONE_FILLER(b)
    r = via[0] / 2 + 0.15
    ring = [(r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(0, 360, 30)] + [(0, 0)]
    for _ in range(10):
        filler.Fill(b.Zones())
        isl = []                                             # (層, 塗り, 番号)
        for z in b.Zones():
            if z.GetNetCode() == code:
                fp = z.GetFilledPolysList(z.GetLayer())
                isl += [(z.GetLayer(), fp, i) for i in range(fp.OutlineCount())]
        inside = lambda k, x, y: isl[k][1].Contains(pcbnew.VECTOR2I(mm(x), mm(y)), isl[k][2])
        parent = list(range(len(isl)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        holes = []                                           # 表と裏を結ぶもの
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                holes.append((tomm(t.GetPosition().x), tomm(t.GetPosition().y), t.GetNetCode()))
        pads = []
        for pd in b.GetPads():
            bb = pd.GetBoundingBox()
            pads.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                holes.append((tomm(pd.GetPosition().x), tomm(pd.GetPosition().y), pd.GetNetCode()))
        for x, y, c in holes:
            if c == code:
                ks = [k for k in range(len(isl)) if any(inside(k, x + dx, y + dy) for dx, dy in ((0.6, 0), (-0.6, 0), (0, 0.6), (0, -0.6), (0.95, 0), (-0.95, 0), (0, 0.95), (0, -0.95)))]
                for k in ks[1:]:
                    parent[find(k)] = find(ks[0])
        if len({find(k) for k in range(len(isl))}) == 1:
            return
        done = False
        for i in range(len(isl)):
            for j in range(len(isl)):
                if isl[i][0] == isl[j][0] or find(i) == find(j) or i > j:
                    continue
                bi, bj = isl[i][1].Outline(isl[i][2]).BBox(), isl[j][1].Outline(isl[j][2]).BBox()
                x0, x1 = max(tomm(bi.GetLeft()), tomm(bj.GetLeft())), min(tomm(bi.GetRight()), tomm(bj.GetRight()))
                y0, y1 = max(tomm(bi.GetTop()), tomm(bj.GetTop())), min(tomm(bi.GetBottom()), tomm(bj.GetBottom()))
                n = 0
                y = y0
                while y <= y1 and n < per_link:
                    x = x0
                    while x <= x1 and n < per_link:
                        if all(inside(i, x + dx, y + dy) and inside(j, x + dx, y + dy) for dx, dy in ring) and \
                                all(math.hypot(x - hx, y - hy) >= 1.2 for hx, hy, _ in holes) and \
                                all(not (p[0] - 0.5 < x < p[2] + 0.5 and p[1] - 0.5 < y < p[3] + 0.5) for p in pads):
                            v = pcbnew.PCB_VIA(b)
                            v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
                            v.SetWidth(pcbnew.F_Cu, mm(via[0]))
                            v.SetDrill(mm(via[1]))
                            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                            v.SetNetCode(code)
                            b.Add(v)
                            holes.append((x, y, code))
                            n += 1
                            print(f'  GND の島を縫うビア：({x:.2f}, {y:.2f})')
                        x += 0.4
                    y += 0.4
                if n:
                    parent[find(i)] = find(j)
                    done = True
        if not done:                                         # 置ける所が無い島は残す（DRC の未接続に出るので、手で直す）
            print('  GND の島をつなげるビアを置けない所がある')
            return


def apply(name):
    src, work, pcb, dsn, ses = paths(name)
    assert os.path.exists(ses), f'{ses} が無い（Freerouting を先に実行する）'
    b = pcbnew.LoadBoard(pcb)
    assert pcbnew.ImportSpecctraSES(b, ses), 'SES を取り込めなかった'
    ground_vias(b)
    if b.GetCopperLayerCount() == 2:
        stitch(b)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pro = src.replace('.kicad_pcb', '.kicad_pro')
    keep = open(pro, encoding='utf-8').read()          # SaveBoard が既定値で書き直すので戻す
    pcbnew.SaveBoard(src, b)
    open(pro, 'w', encoding='utf-8').write(keep)
    print(src, '配線・ビア', len(b.GetTracks()))


if __name__ == '__main__':
    {'prep': prep, 'apply': apply, 'link': link}[sys.argv[1]](*sys.argv[2:])
