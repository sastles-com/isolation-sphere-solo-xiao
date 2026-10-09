#!/usr/bin/env python3
"""基板B の回路図から PCB を作り、部品を配置する（配線はしない）。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      tools/kicad/pcb_boardB.py [出力 .kicad_pcb]

手順：
1. kicad-cli で boardB.kicad_sch のネットリスト（XML）を出す
2. 外形（40 mm 角、隅を 8 mm 面取り）、4 層、ネットを作る
3. 部品（lcsc.pretty のフットプリント）を読み込み、ピンにネットを付ける。
   出力先の boardB.kicad_pcb に、KiCad の「回路図から基板を更新」で取り込み済みの部品があれば、それをそのまま動かす（ネットは変えない）
4. 主要部品は座標で固定し、受動部品は「つながる IC のピンの近く」に、重ならない位置を探して置く

配置の前提（docs/easyeda_workflow.md §4〜§6）：
- 基板A↔B のヘッダ（J2、J3）は前後（±y）の辺に 1 本ずつ。基板B 表面の部品は、基板A 裏面の部品と合わせて 6 mm 以内
- 電池コネクタ（J4、J5）は縦向きの B2B-XH-A（高さ 9.8 mm）で、基板間隔 7 mm の表面には置けない → 裏面に置く
- 発熱部品（BQ25792 とインダクタ、保護 FET、シャント）は互いに離し、スイッチングノードは I²C と検出線から離す
"""
import json
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
SCH = os.path.join(ROOT, 'kicad', 'boardB', 'boardB.kicad_sch')
PRETTY = os.path.join(ROOT, 'kicad', 'lib', 'lcsc.pretty')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'kicad', 'boardB', 'boardB.kicad_pcb')
CX, CY = 100.0, 100.0                 # PCB シート上での基板中心（mm）
HALF, CHAMFER = 20.0, 8.0
EDGE = 0.6                            # 部品の外形と基板の端の最小すき間
BACK_PENALTY = 20.0                  # 裏面に置くときの距離の割増し（mm）。表面で 20 mm 以内に空きがあれば表面を使う
GAP = 1.0                            # 部品どうしのすき間（パッドを含む外形の間）

mm = pcbnew.FromMM
tomm = pcbnew.ToMM


def vec(x, y):
    return pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))


# ------------------------------------------------------------------ ネットリスト
EXTRA_NETS = {
    'CFX_M': [('C20', '1'), ('C21', '2')],        # 保護 FET をまたぐ 0.1 µF 2 個の中点
    'CPK_M': [('C22', '1'), ('C23', '2')],        # PACK_P と GND の間の 0.1 µF 2 個の中点
    'STAT_K': [('D2', '1'), ('U3', '1')],         # STAT の LED のカソード → U3 の STAT
    'STAT_A': [('D2', '2'), ('R8', '2')],         # LED のアノード → R8
    'CE': [('R7', '1'), ('U3', '13')],            # CE のプルダウン
}


def read_netlist_xml():
    xml = '/tmp/boardB_pcb.xml'
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, SCH],
                   capture_output=True, text=True, check=True)
    return xml


def read_netlist():
    xml = read_netlist_xml()
    t = ET.parse(xml).getroot()
    comps = {}
    for c in t.iter('comp'):
        lc = ''
        for f in c.iter('field'):
            if f.get('name') == 'LCSC Part':
                lc = f.text or ''
        comps[c.get('ref')] = {'value': c.findtext('value') or '', 'fp': (c.findtext('footprint') or '').split(':')[-1], 'lcsc': lc}
    nets = {}
    for n in t.iter('net'):
        nets[n.get('name').lstrip('/')] = [(x.get('ref'), x.get('pin')) for x in n.iter('node')]
    # kicad-cli のネットリストは、名前のない 2 ピンのネットを出力しないことがある（KiCad 10.0.3 で確認）。
    # 回路図の配線から分かっている 5 本を、名前を付けて補う
    for name, pins in EXTRA_NETS.items():
        if name not in nets and not any(p in {q for v in nets.values() for q in v} for p in pins):
            nets[name] = list(pins)
    return comps, nets


# ------------------------------------------------------------------ 外形
def outline_points():
    h, c = HALF, CHAMFER
    return [(-h + c, -h), (h - c, -h), (h, -h + c), (h, h - c), (h - c, h), (-h + c, h), (-h, h - c), (-h, -h + c)]


def inside_board(x0, y0, x1, y1, margin=EDGE):
    """長方形が、面取りした外形の中に margin 以上離れて収まるか。"""
    h, c = HALF - margin, CHAMFER
    if x0 < -h or x1 > h or y0 < -h or y1 > h:
        return False
    # 45° の面取り：x + y <= (h + (h - c)) の形の 4 つの直線
    lim = 2 * HALF - c - margin * math.sqrt(2)
    for sx in (-1, 1):
        for sy in (-1, 1):
            px = x1 if sx > 0 else x0
            py = y1 if sy > 0 else y0
            if sx * px + sy * py > lim:
                return False
    return True


# ------------------------------------------------------------------ 部品
class Fp:
    def __init__(self, ref, info, board, netmap, existing=None):
        self.ref, self.info = ref, info
        if existing is not None:              # KiCad の「回路図から基板を更新」で取り込み済みのもの（ネットも付いている）
            self.fp = existing
        else:
            self.fp = pcbnew.FootprintLoad(PRETTY, info['fp'])
            self.fp.SetReference(ref)
            self.fp.SetValue(info['value'])
            self.fp.SetFPID(pcbnew.LIB_ID('lcsc', info['fp']))
            for pad in self.fp.Pads():
                nm = netmap.get((ref, pad.GetNumber()))
                if nm:
                    pad.SetNet(board.FindNet(nm))
            board.Add(self.fp)
        if self.fp.IsFlipped():               # 常に表面・回転 0 の状態から測る
            self.fp.Flip(self.fp.GetPosition(), True)
        self.fp.SetOrientationDegrees(0)
        c = self.fp.GetPosition()
        boxes = [pd.GetBoundingBox() for pd in self.fp.Pads()]        # パッドは必ず含める（外形線より外に出ることがある）
        cy = self.fp.GetCourtyard(pcbnew.F_CrtYd)
        if cy.OutlineCount():
            boxes.append(cy.BBox())
        self.rel = (tomm(min(b.GetLeft() for b in boxes) - c.x), tomm(min(b.GetTop() for b in boxes) - c.y),
                    tomm(max(b.GetRight() for b in boxes) - c.x), tomm(max(b.GetBottom() for b in boxes) - c.y))
        self.tht = any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in self.fp.Pads())
        self.x = self.y = 0.0
        self.rot = 0
        self.back = False

    def rect(self, x, y, rot, back):
        x0, y0, x1, y1 = self.rel
        if back:
            x0, x1 = -x1, -x0           # 裏返すと左右が反転する
        for _ in range(rot // 90 % 4):
            x0, y0, x1, y1 = y0, -x1, y1, -x0       # 90° 回転（KiCad は反時計回りが正。y は下向き：(x, y) → (y, −x)）
        return (x + x0, y + y0, x + x1, y + y1)

    def put(self, x, y, rot=0, back=False):
        self.x, self.y, self.rot, self.back = x, y, rot, back
        if back != self.fp.IsFlipped():
            self.fp.Flip(self.fp.GetPosition(), True)
        self.fp.SetOrientationDegrees(rot)
        self.fp.SetPosition(vec(x, y))

    def placed_by_grid(self):
        return not (self.x == 0.0 and self.y == 0.0)

    def pad_pos(self, num):
        for p in self.fp.Pads():
            if p.GetNumber() == num:
                q = p.GetPosition()
                return tomm(q.x) - CX, tomm(q.y) - CY
        return None


def overlap(a, b, gap=GAP):
    e = 1e-6                              # 隣り合う部品の境界ちょうどは「重ならない」（小数の誤差を許す）
    return not (a[2] + gap <= b[0] + e or b[2] + gap <= a[0] + e or a[3] + gap <= b[1] + e or b[3] + gap <= a[1] + e)


class Placer:
    def __init__(self):
        self.occ = {False: [], True: []}

    def free(self, r, back, tht=False):
        if not inside_board(*r):
            return False
        sides = (False, True) if tht else (back,)
        return all(not overlap(r, o) for s in sides for o in self.occ[s])

    def commit(self, f):
        r = f.rect(f.x, f.y, f.rot, f.back)
        for s in ((False, True) if f.tht else (f.back,)):
            self.occ[s].append(r)

    def fixed(self, f, x, y, rot=0, back=False):
        f.put(x, y, rot, back)
        r = f.rect(x, y, rot, back)
        if not inside_board(*r):
            print(f'  ⚠️ {f.ref}: 基板の外にはみ出す {tuple(round(v, 1) for v in r)}')
        if not self.free(r, back, f.tht):
            print(f'  ⚠️ {f.ref}: 他の部品と重なる')
        self.commit(f)

    def grid(self, parts, refs, ax, ay, rot=0, per_row=4):
        """refs を、(ax, ay) を左上として、同じ向き・同じ高さの行にそろえて並べる（行は下へ進む）。"""
        y = ay
        i = 0
        while i < len(refs):
            row = refs[i:i + per_row]
            x = ax
            row_h = 0.0
            placed = []
            for ref in row:
                f = parts[ref]
                x0, y0, x1, y1 = f.rect(0, 0, rot, False)
                w, h = x1 - x0, y1 - y0
                ok = False
                xx = x
                while xx + w <= 21:
                    cx, cy = xx - x0, y - y0                  # 左上が (xx, y) になる中心
                    r = f.rect(cx, cy, rot, False)
                    if self.free(r, False, f.tht):
                        f.put(cx, cy, rot, False)
                        self.commit(f)
                        x = xx + w + GAP
                        row_h = max(row_h, h)
                        ok = True
                        break
                    xx += 0.5
                if not ok:
                    print(f'  ⚠️ {ref}: 行 y={y:.1f} に置けない（あとで近くに置く）')
                else:
                    placed.append(ref)
            y += (row_h or 2.0) + GAP
            i += per_row
        return

    def near(self, f, tx, ty, back_ok=True, max_r=40.0):
        """目標 (tx, ty) にいちばん近い、空いた位置に置く（表面を優先）。"""
        best = None
        step = 0.5
        cands = []
        n = int(max_r / step)
        for ix in range(-n, n + 1):
            for iy in range(-n, n + 1):
                x, y = tx + ix * step, ty + iy * step
                d = math.hypot(x - tx, y - ty)
                if d > max_r:
                    continue
                cands.append((d, x, y))
        cands.sort()
        for back in ((False, True) if back_ok else (False,)):
            for d, x, y in cands:
                if best and d + (BACK_PENALTY if back else 0) > best[0]:
                    break
                for rot in (0, 90):
                    r = f.rect(x, y, rot, back)
                    if self.free(r, back, f.tht):
                        score = d + (BACK_PENALTY if back else 0.0)
                        if not best or score < best[0]:
                            best = (score, x, y, rot, back)
                        break
        if not best:
            print(f'  ⚠️ {f.ref}: 置ける場所がない')
            return False
        f.put(*best[1:])
        self.commit(f)
        return True


# ------------------------------------------------------------------ 組み立て
def build():
    global CX, CY
    update = os.path.exists(OUT) and OUT.endswith('boardB.kicad_pcb') and os.path.getsize(OUT) > 20000
    if update:
        CX = CY = 0.0                         # ユーザーの基板は、原点が基板の中心
        board = pcbnew.LoadBoard(OUT)
        board.SetCopperLayerCount(4)
        comps, nets, padnets = {}, {}, {}
        for f in board.GetFootprints():
            ref = f.GetReferenceAsString()
            comps[ref] = {'value': f.GetValueAsString(), 'fp': str(f.GetFPID().GetLibItemName())}
            padnets[ref] = {pd.GetNumber(): pd.GetNetname() for pd in f.Pads()}
            for pd in f.Pads():
                if pd.GetNetname():
                    nets.setdefault(pd.GetNetname(), []).append((ref, pd.GetNumber()))
        netmap = {(r, p): n for n, pins in nets.items() for r, p in pins}
        existing = {f.GetReferenceAsString(): f for f in board.GetFootprints()}
        edge = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
        if len(edge) == 1:                            # 正方形 1 個（取り込み直後）なら面取りした外形に置き換える。
            board.Remove(edge[0])                     # すでに外形があれば触らない（Remove のあと、部品の参照が使えなくなるため）
            existing = {f.GetReferenceAsString(): f for f in board.GetFootprints()}
            edge = []
        has_outline = bool(edge)
    else:
        comps, nets = read_netlist()
        board = pcbnew.CreateEmptyBoard()
        board.SetCopperLayerCount(4)
        netmap = {}
        for name, pins in nets.items():
            if name.startswith('unconnected-'):
                continue
            ni = pcbnew.NETINFO_ITEM(board, name)
            board.Add(ni)
            for ref, pin in pins:
                netmap[(ref, pin)] = name
        existing = {}
    # 外形
    pts = outline_points()
    for i, p in enumerate([] if update and has_outline else pts):
        q = pts[(i + 1) % len(pts)]
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetStart(vec(*p))
        seg.SetEnd(vec(*q))
        seg.SetWidth(mm(0.1))
        board.Add(seg)

    if update:                            # 回路図のフットプリントが変わった部品は、ネットを引き継いで入れ替える
        want = {c.get('ref'): (c.findtext('footprint') or '').split(':')[-1] for c in
                ET.parse(read_netlist_xml()).getroot().iter('comp')}
        swaps = {}
        for ref in existing:
            if want.get(ref) and want[ref] != comps[ref]['fp']:
                swaps[ref] = (want[ref], comps[ref]['value'], padnets[ref])
        if swaps:
            # LoadBoard のあとでは FootprintLoad や新しい部品の操作が使えない（KiCad 10.0.3 の Python の制約）ので、
            # 別のプロセスで部品を入れた一時基板を作り、それを読み込んで移す
            tmp = '/tmp/boardB_swap.kicad_pcb'
            subprocess.run([sys.executable, __file__, '--mkfp', tmp, json.dumps(swaps)], check=True, capture_output=True)
            tb = pcbnew.LoadBoard(tmp)
            items = []
            for nf in tb.GetFootprints():       # Remove / Add のあとは参照が使えなくなるので、先にすべて調べておく
                items.append((nf, nf.GetReferenceAsString(), [(pd, pd.GetNumber()) for pd in nf.Pads()]))
            for nf, ref, pads in items:
                tb.Remove(nf)
                board.Remove(existing[ref])
                board.Add(nf)
                for pd, num in pads:
                    nm = swaps[ref][2].get(num)
                    pd.SetNet(board.FindNet(nm) if nm else board.FindNet(''))
                existing[ref] = nf
                comps[ref]['fp'] = swaps[ref][0]
                print(f'  {ref}: フットプリントを {swaps[ref][0]} に入れ替え')
            pcbnew.SaveBoard(OUT, board)         # 入れ替えたら保存して終わる（このあとの操作は、読み直さないと使えない）
            print('  入れ替えを保存した。もう一度実行すると配置する')
            sys.exit(0)
    parts = {ref: Fp(ref, info, board, netmap, existing.get(ref)) for ref, info in comps.items()}
    pl = Placer()
    for ref, (x, y, rot, back) in PLAN.items():
        pl.fixed(parts[ref], x, y, rot, back)

    # 受動部品：つながる IC / 主要部品のピンの近くへ
    anchors = {r for r in PLAN}
    by_ref_nets = {}
    for (ref, pin), nm in netmap.items():
        by_ref_nets.setdefault(ref, {})[pin] = nm
    rest = [r for r in parts if r not in anchors]

    def target(ref):
        mine = by_ref_nets.get(ref, {})
        best, bd = None, -1
        for pin, nm in mine.items():
            others = [(r, p) for r, p in nets[nm] if r in anchors]
            if nm == 'GND':
                continue
            for r, p in others:
                pp = parts[r].pad_pos(p)
                if pp and (best is None or len(nets[nm]) < bd or bd < 0):
                    best, bd = pp, len(nets[nm])
        return best

    # 機能ごとのまとまりを、行をそろえて置く
    for name, refs, ax, ay, rot, per_row in GROUPS:
        pl.grid(parts, [r for r in refs if r in rest], ax, ay, rot, per_row)
        for r in refs:
            if r in rest and parts[r].placed_by_grid():
                rest.remove(r)

    prio = {'U': 0, 'R': 2, 'C': 1}
    rest.sort(key=lambda r: (0 if any(nm in ('VSYS', 'VBUS', 'PMID', 'PACK_P', 'SW1', 'SW2', 'REGN') for nm in by_ref_nets.get(r, {}).values()) else 1,
                             prio.get(r[0], 3), -parts[r].rel[2] * parts[r].rel[3], r))
    for ref in rest:
        t = target(ref) or (0.0, 0.0)
        pl.near(parts[ref], t[0], t[1])
    silk_text(board)
    pcbnew.SaveBoard(OUT, board)
    dump = []
    for ref, f in parts.items():
        pads = []
        for pd in f.fp.Pads():
            bb = pd.GetBoundingBox()
            pads.append([tomm(bb.GetLeft()) - CX, tomm(bb.GetTop()) - CY, tomm(bb.GetRight()) - CX, tomm(bb.GetBottom()) - CY,
                         pd.GetNumber(), pd.GetNetname(), pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH])
        dump.append({'ref': ref, 'value': f.info['value'], 'back': f.back, 'rect': f.rect(f.x, f.y, f.rot, f.back), 'pads': pads})
    json.dump({'outline': outline_points(), 'parts': dump}, open(OUT.replace('.kicad_pcb', '.layout.json'), 'w'), ensure_ascii=False)
    placed = {ref: (round(p.x, 2), round(p.y, 2), p.rot, 'B' if p.back else 'F') for ref, p in parts.items()}
    return placed


SILK_W, SILK_H, SILK_T = 0.5, 0.7, 0.1      # シルク文字：幅 × 高さ × 線の太さ（mm）


def silk_text(board):
    """シルク（F.SilkS / B.SilkS）の文字を、すべて 0.5 × 0.7、線の太さ 0.1 mm にする。"""
    silk = (pcbnew.F_SilkS, pcbnew.B_SilkS)
    ds = board.GetDesignSettings()
    try:                                  # 新しく置く文字の既定値（API の名前が版で違うので、使えなければ飛ばす）
        ds.m_TextSize[pcbnew.LAYER_CLASS_SILK] = pcbnew.VECTOR2I(mm(SILK_W), mm(SILK_H))
        ds.m_TextThickness[pcbnew.LAYER_CLASS_SILK] = mm(SILK_T)
    except Exception as e:  # noqa: BLE001
        print('  （既定の文字サイズは設定できなかった：', type(e).__name__, '）')

    def fix(t):
        t.SetTextSize(pcbnew.VECTOR2I(mm(SILK_W), mm(SILK_H)))
        t.SetTextThickness(mm(SILK_T))
    n = 0
    for f in board.GetFootprints():
        for t in [f.Reference(), f.Value()] + [g for g in f.GraphicalItems() if hasattr(g, 'SetTextSize')]:
            if t.GetLayer() in silk:
                fix(t)
                n += 1
    for d in board.GetDrawings():
        if hasattr(d, 'SetTextSize') and d.GetLayer() in silk:
            fix(d)
            n += 1
    fab = (pcbnew.F_Fab, pcbnew.B_Fab)
    h = 0
    for f in board.GetFootprints():              # Fab 層の文字（値など）は非表示にする
        for t in [f.Reference(), f.Value()] + [g for g in f.GraphicalItems() if hasattr(g, 'SetTextSize')]:
            if t.GetLayer() in fab and t.IsVisible():
                t.SetVisible(False)
                h += 1
    print(f'  Fab 層の文字 {h} 個を非表示')
    print(f'  シルク文字 {n} 個を {SILK_W} x {SILK_H} x {SILK_T} mm に変更')


# 主要部品の固定位置（基板中心が原点、x 右、y 下、mm）。(x, y, 回転, 裏面か)
PLAN = {
    'J2': (0.0, -16.5, 0, False),        # 基板A への電源ヘッダ（北辺）
    'J3': (0.0, 16.5, 0, False),         # 基板A への信号ヘッダ（南辺）
    'J1': (-17.8, -2.0, 90, False),      # 充電入力（西辺）
    'U3': (-4.0, -1.0, 0, False),        # BQ25792：入力は西、電力段は北、電池側は東
    'L2': (-2.5, -10.5, 0, False),       # 電力段のインダクタ（U3 の北）
    'Q2': (4.0, 2.8, 0, False),          # 保護 FET（U3 の電池側のすぐ東）
    'F2': (12.0, 1.0, 0, False),         # ヒューズ（さらに東）
    'U1': (12.5, 8.8, 0, False),        # BQ28Z620
    'J4': (17.8, 9.0, 90, False),        # セル 1 の 2P ピンヘッダ（東辺）
    'J5': (-14.0, 12.5, 90, False),      # セル 2 の 2P ピンヘッダ（南西）。J4 と離す
    'D1': (-17.8, 4.2, 90, False),       # TVS は充電入力 J1 のすぐ南
    'R18': (13.0, 13.6, 90, False),      # シャント（U1 の南）
}

# 機能ごとのまとまり：(名前, 部品, 左上の x, y, 向き, 1 行の個数)。同じ行は同じ高さにそろえる
GROUPS = [
    ('PMID', ['C4', 'C5', 'C6', 'C7'], -16.5, -13.5, 0, 2),
    ('VBUS 入力', ['C1', 'C2', 'C3'], -14.2, -5.5, 0, 1),
    ('VSYS 出力', ['C14', 'C15', 'C16', 'C17', 'C18', 'C19'], 3.5, -14.0, 90, 3),
    ('PACK_P', ['C12', 'C13', 'R9'], -0.2, -4.9, 90, 2),
    ('設定抵抗', ['R7', 'R8', 'D2', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6'], -12.5, 4.0, 0, 4),
    ('FET まわり', ['C20', 'C21', 'C22', 'C23', 'R10'], 1.5, 9.0, 0, 2),
    ('ゲート', ['R14', 'R15', 'R16', 'R17'], 1.5, 5.2, 0, 2),
    ('ゲージ', ['R11', 'R12', 'R13', 'R19', 'R20', 'C24', 'C25', 'C26', 'C27', 'C28', 'C29'], -12.5, 9.5, 0, 4),
]


def make_swap_board(path, swaps):
    b = pcbnew.CreateEmptyBoard()
    for ref, (fpname, value, nets) in swaps.items():
        for nm in set(nets.values()):
            if nm and not b.FindNet(nm):
                b.Add(pcbnew.NETINFO_ITEM(b, nm))
        f = pcbnew.FootprintLoad(PRETTY, fpname)
        f.SetReference(ref)
        f.SetValue(value)
        f.SetFPID(pcbnew.LIB_ID('lcsc', fpname))
        for pd in f.Pads():
            nm = nets.get(pd.GetNumber())
            if nm:
                pd.SetNet(b.FindNet(nm))
        b.Add(f)
    pcbnew.SaveBoard(path, b)


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == '--mkfp':
    make_swap_board(sys.argv[2], json.loads(sys.argv[3]))
    sys.exit(0)

if __name__ == '__main__':
    placed = build()
    print(json.dumps(placed, ensure_ascii=False))
