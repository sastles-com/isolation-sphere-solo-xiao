"""電池と基板スタックがコア内に収まるかを、コアの STL から概算する。

標準ライブラリのみ。STL を z 一定の面で切った断面（閉じた輪郭の線分の集合）を障害物とし、
基板やセルの輪郭（多角形）が障害物と交差するか、最小のすき間はいくつかを求める。

座標系（mm）：赤道面 z = 0、北が +z、南（LiPo 側）が -z。mother-ring は z = ±0.8。
- core-north-03_fixed.stl はそのまま
- core-south-03_fixed.stl は北と同じ向きでモデル化されているので、
  赤道軸まわりに 180° 回して置く（y → -y、z → -z）

重ね順（北から）：MCU – セル – mother-ring – セル – 基板A – 基板B

使い方:
  python3 -I tools/fit_check.py [STL ディレクトリ] [出力ディレクトリ]
STL の既定の場所は docs/cad/（`docs/cad/README.md` 参照）。
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STL_DIR = os.path.join(HERE, "..", "docs", "cad")
DEFAULT_OUT_DIR = os.path.join(HERE, "..", "outputs", "fit")

# ---- 寸法（mm）。実機の値が分かったら、ここを直して再実行する ----
RING_T = 1.6            # mother-ring の板厚
BOARD_T = 1.6           # 基板厚
SOCKET_GAP = 11.0       # ソケット 8.5 + ヘッダ絶縁体 2.5。mother-ring（または MCU）↔基板A の面間距離
BOARD_GAP = 7.0         # 基板A↔B（基板Aの下面から基板Bの上面まで）
CELL = (40.0, 40.0, 10.0)   # LiPo（ユーザー確認、2026-10-08）
CORNER_R = 3.0          # 基板の角の丸み
BODY = 40.0             # 基板本体の一辺

# 実機（power-2s-legacy.kicad_pcb）の張り出し：x が ±20〜±25、y が ±9.25
LEGACY_TAB = dict(x_out=25.0, half_y=9.25)

# ピンソケット FH-1x6SG/RH（6 極、2.54 mm ピッチ、ハウジング 15.24 × 2.54 mm）
SOCKET_PINS = 6
SOCKET_PITCH = 2.54
SOCKET_X = 22.86        # ソケット中心の x（実機 J7 / J8 の位置）
SOCKET_MARGIN = 0.5     # ハウジングから基板の縁まで

Z_STEP = 0.5            # 断面を切る z の刻み


# ------------------------------------------------------------------ STL と断面
def load_stl(path, flip=False):
    data = open(path, "rb").read()
    n = struct.unpack("<I", data[80:84])[0]
    tris = []
    for i in range(n):
        o = 84 + i * 50 + 12
        t = []
        for k in range(3):
            x, y, z = struct.unpack("<3f", data[o + 12 * k:o + 12 * k + 12])
            if flip:
                y, z = -y, -z
            t.append((x, y, z))
        tris.append(t)
    return tris


class Mesh:
    """z 方向に 1 mm 刻みで三角形を振り分け、断面計算を速くする。"""

    def __init__(self, tris):
        self.buckets = {}
        for t in tris:
            z0 = min(p[2] for p in t)
            z1 = max(p[2] for p in t)
            for b in range(math.floor(z0), math.floor(z1) + 1):
                self.buckets.setdefault(b, []).append(t)
        self.cache = {}

    def slice(self, z):
        key = round(z, 3)
        if key in self.cache:
            return self.cache[key]
        segs = []
        for t in self.buckets.get(math.floor(z), []):
            pts = []
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                if (a[2] - z) * (b[2] - z) < 0:
                    r = (z - a[2]) / (b[2] - a[2])
                    pts.append((a[0] + r * (b[0] - a[0]), a[1] + r * (b[1] - a[1])))
            if len(pts) == 2:
                segs.append((pts[0], pts[1]))
        self.cache[key] = segs
        return segs


def slice_all(meshes, z):
    segs = []
    for m in meshes:
        segs += m.slice(z)
    return segs


# ------------------------------------------------------------------ 幾何
def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _seg_inter(p1, p2, q1, q2):
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _pt_seg_dist(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)


def _inside(poly, p):
    c = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                c = not c
    return c


def _arc(cx, cy, r, a0, n=6):
    """中心 (cx, cy)、半径 r の円弧。角度 a0 から a0 + 90° まで。"""
    return [(cx + r * math.cos(math.radians(a0 + 90 * k / n)),
             cy + r * math.sin(math.radians(a0 + 90 * k / n))) for k in range(n + 1)]


def rounded_rect(sx, sy, r):
    """角丸の長方形（原点中心）の頂点列（反時計回り）。"""
    hx, hy = sx / 2 - r, sy / 2 - r
    return (_arc(hx, -hy, r, 270) + _arc(hx, hy, r, 0) +
            _arc(-hx, hy, r, 90) + _arc(-hx, -hy, r, 180))


def board_outline(side=BODY, tab=None, r=CORNER_R):
    """基板の外形（反時計回り）。tab = dict(x_out, half_y) なら左右の辺に張り出しを付ける。"""
    if not tab:
        return rounded_rect(side, side, r)
    h, c = side / 2, side / 2 - r
    tx, ty = tab["x_out"], tab["half_y"]
    return (_arc(c, -c, r, 270) + [(h, -ty), (tx, -ty), (tx, ty), (h, ty)] +
            _arc(c, c, r, 0) + _arc(-c, c, r, 90) +
            [(-h, ty), (-tx, ty), (-tx, -ty), (-h, -ty)] + _arc(-c, -c, r, 180))


def socket_tab(socket_x=SOCKET_X):
    """ピンソケット（6 極）のハウジングが収まる最小の張り出し。"""
    housing_len = SOCKET_PINS * SOCKET_PITCH
    return dict(x_out=socket_x + SOCKET_PITCH / 2 + SOCKET_MARGIN,
                half_y=housing_len / 2 + SOCKET_MARGIN)


def transform(poly, cx=0.0, cy=0.0, yaw=0.0):
    c, s = math.cos(yaw), math.sin(yaw)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in poly]


def clearance(segs, poly, margin=3.0):
    """多角形と断面の最小すき間。交差・内包なら -1。margin 以上離れた線分は無視して速くする。"""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin
    edges = list(zip(poly, poly[1:] + poly[:1]))
    best = math.inf
    for a, b in segs:
        if (max(a[0], b[0]) < x0 or min(a[0], b[0]) > x1 or
                max(a[1], b[1]) < y0 or min(a[1], b[1]) > y1):
            continue
        if _inside(poly, a) or _inside(poly, b):
            return -1.0
        for e1, e2 in edges:
            if _seg_inter(a, b, e1, e2):
                return -1.0
        for p in poly:
            best = min(best, _pt_seg_dist(p, a, b))
        for e1, e2 in edges:
            best = min(best, _pt_seg_dist(a, e1, e2), _pt_seg_dist(b, e1, e2))
    return best


def solid_clearance(meshes, poly, z0, z1):
    """高さ z0〜z1 の柱（多角形を押し出した立体）と障害物の最小すき間。干渉なら -1。"""
    worst = math.inf
    z = z0 + 0.01
    while z < z1:
        c = clearance(slice_all(meshes, z), poly)
        if c < 0:
            return -1.0
        worst = min(worst, c)
        z += Z_STEP
    c = clearance(slice_all(meshes, z1 - 0.01), poly)
    return -1.0 if c < 0 else min(worst, c)


def best_yaw(meshes, poly, z0, z1, step=5, span=180):
    """多角形を軸のまわりで回して、すき間が最大になる回転と値を返す（入らなければ None）。"""
    best = None
    for deg in range(0, span, step):
        c = solid_clearance(meshes, transform(poly, yaw=math.radians(deg)), z0, z1)
        if c >= 0 and (best is None or c > best[1]):
            best = (deg, c)
    return best


def max_side(meshes, outline_fn, z0, z1, lo=20.0, hi=44.0):
    """outline_fn(side) が入る最大の一辺（回転なし）。"""
    for _ in range(12):
        mid = (lo + hi) / 2
        if solid_clearance(meshes, outline_fn(mid), z0, z1) >= 0:
            lo = mid
        else:
            hi = mid
    return lo


# ------------------------------------------------------------------ SVG
def svg_section(meshes, z, shapes, path):
    s = 4.0
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="-200 -200 400 400" width="400" height="400">',
             '<rect x="-200" y="-200" width="400" height="400" fill="white"/>',
             f'<text x="-195" y="-185" font-size="12">z = {z:.1f} mm</text>']
    for a, b in slice_all(meshes, z):
        lines.append(f'<line x1="{a[0]*s:.1f}" y1="{-a[1]*s:.1f}" x2="{b[0]*s:.1f}" y2="{-b[1]*s:.1f}" '
                     'stroke="black" stroke-width="0.6"/>')
    for poly, z0, z1, color in shapes:
        if z0 <= z <= z1:
            pts = " ".join(f"{x*s:.1f},{-y*s:.1f}" for x, y in poly)
            lines.append(f'<polygon points="{pts}" fill="{color}" fill-opacity="0.2" stroke="{color}"/>')
    lines.append("</svg>")
    open(path, "w").write("\n".join(lines))


# ------------------------------------------------------------------ メイン
def chamfered(side, c):
    """隅を c mm 面取りした正方形（八角形）。"""
    h = side / 2
    return [(h - c, -h), (h, -h + c), (h, h - c), (h - c, h), (-h + c, h), (-h, h - c), (-h, -h + c), (-h + c, -h)]


def hits(meshes, poly, z0, z1):
    """多角形に当たる断面の点を集めて、当たる場所の特徴（高さ・x・y・半径の範囲）を返す。"""
    pts = []
    edges = list(zip(poly, poly[1:] + poly[:1]))
    z = z0 + 0.01
    while z < z1:
        for a, b in slice_all(meshes, z):
            if _inside(poly, a) or _inside(poly, b) or any(_seg_inter(a, b, e1, e2) for e1, e2 in edges):
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                pts.append((z, m[0], m[1], math.hypot(*m)))
        z += Z_STEP
    if not pts:
        return None
    zs, xs, ys, rs = zip(*pts)
    return dict(n=len(pts), z=(min(zs), max(zs)), absx=(min(map(abs, xs)), max(map(abs, xs))),
                absy=(min(map(abs, ys)), max(map(abs, ys))), r=(min(rs), max(rs)))


def cell(v):
    return "**干渉**" if v < 0 else f"{v:.1f} mm"


def main():
    stl_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STL_DIR
    out_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    meshes = [
        Mesh(load_stl(os.path.join(stl_dir, "core-north-03_fixed.stl"))),
        Mesh(load_stl(os.path.join(stl_dir, "core-south-03_fixed.stl"), flip=True)),
    ]
    L, W, T = CELL
    ring_top, ring_bot = RING_T / 2, -RING_T / 2

    # 北から：MCU – セル – mother-ring – セル – 基板A – 基板B
    a_top = ring_bot - SOCKET_GAP
    a_z = (a_top - BOARD_T, a_top)
    b_top = a_z[0] - BOARD_GAP
    b_z = (b_top - BOARD_T, b_top)
    cell_s = (a_top + 0.5, a_top + 0.5 + T)
    cell_n = (ring_top + SOCKET_GAP - 0.5 - T, ring_top + SOCKET_GAP - 0.5)

    rep = ["# 電池・基板の配置検討（fit_check.py の出力）", "",
           "重ね順（北から）：MCU – セル – mother-ring – セル – 基板A – 基板B。",
           f"mother-ring は z = 0（板厚 {RING_T} mm）、南（LiPo 側）は −z。",
           f"mother-ring・MCU 基板と基板A の面間距離 {SOCKET_GAP} mm（ソケット 8.5 + ヘッダ絶縁体 2.5）、"
           f"基板A↔B {BOARD_GAP} mm、基板厚 {BOARD_T} mm、セル {L:.0f}×{W:.0f}×{T:.0f} mm。", "",
           "STL は `docs/cad/` の core-north-03_fixed / core-south-03_fixed。断面に現れる塊を一つずつ障害物として扱い、",
           "基板やセルの輪郭が塊に当たるか、最小のすき間はいくつかを調べる。「干渉」は当たること。", ""]

    # ---- 基板A
    legacy = board_outline(BODY, LEGACY_TAB)
    rep += ["## 基板A（実機の外形：張り出し x = ±25、y = ±9.25）", "",
            f"高さ z = {a_z[0]:.1f}〜{a_z[1]:.1f} mm。外形を軸のまわりに回したときのすき間：", "",
            "| 回転 | 張り出しの向き | すき間 |", "| ---: | --- | --- |"]
    for deg in range(0, 180, 15):
        c = solid_clearance(meshes, transform(legacy, yaw=math.radians(deg)), *a_z)
        rep.append(f"| {deg}° | {'±x 方向' if deg == 0 else '±y 方向' if deg == 90 else ''} | {cell(c)} |")
    rep += ["", "張り出しの先端 x（回転 90°、幅 y = ±8.12 mm）の限界：", "", "| 先端 x | すき間 |", "| ---: | --- |"]
    for x_out in (24.63, 26, 27, 28, 29, 30):
        c = solid_clearance(meshes, transform(board_outline(BODY, dict(x_out=x_out, half_y=socket_tab()['half_y'])),
                                              yaw=math.radians(90)), *a_z)
        rep.append(f"| {x_out} mm | {cell(c)} |")
    rep.append("")

    # ---- 基板B
    rep += ["## 基板B", "",
            "基板A↔B の間隔ごとに、基板B（本体 40 mm 角、角 R3）が入るかを調べた。", "",
            "| A↔B 間隔 | 基板Bの高さ z | 40 mm 角 | 隅を 7 mm 面取り | 隅を 9 mm 面取り | 入る最大の一辺 |",
            "| ---: | --- | --- | --- | --- | --- |"]
    for gap in (3, 4, 5, 6, 7, 8):
        bt = a_z[0] - gap
        bb = bt - BOARD_T
        c0 = solid_clearance(meshes, board_outline(BODY), bb, bt)
        c7 = solid_clearance(meshes, chamfered(BODY, 7), bb, bt)
        c9 = solid_clearance(meshes, chamfered(BODY, 9), bb, bt)
        ms = max_side(meshes, lambda s_: board_outline(s_), bb, bt)
        rep.append(f"| {gap} mm | {bb:.1f}〜{bt:.1f} | {cell(c0)} | {cell(c7)} | {cell(c9)} | {ms:.1f} mm |")
    rep.append("")
    h = hits(meshes, board_outline(BODY), *b_z)
    if h:
        rep += [f"間隔 {BOARD_GAP:.0f} mm で 40 mm 角が当たる場所：z = {h['z'][0]:.1f}〜{h['z'][1]:.1f}、"
                f"軸からの半径 {h['r'][0]:.1f}〜{h['r'][1]:.1f} mm（四隅の 45° 方向）。", ""]

    # ---- セル
    rep += ["## セル（40×40×10 mm）", "",
            "| 場所 | 高さ z | 一辺 40 mm | 一辺 39.5 mm | 一辺 39 mm |", "| --- | --- | --- | --- | --- |"]
    for name, z in (("北：MCU 基板と mother-ring の間", cell_n), ("南：mother-ring と基板A の間", cell_s)):
        cs = [solid_clearance(meshes, rounded_rect(side, side, 1.0), *z) for side in (40.0, 39.5, 39.0)]
        rep.append(f"| {name} | {z[0]:.1f}〜{z[1]:.1f} | " + " | ".join(cell(c) for c in cs) + " |")
    rep.append("")
    h = hits(meshes, rounded_rect(L, W, 1.0), *cell_n)
    if h:
        rep += [f"北のセル（40 mm）が当たる場所：z = {h['z'][0]:.1f}〜{h['z'][1]:.1f}、|x| = {h['absx'][0]:.1f}〜{h['absx'][1]:.1f}、"
                f"|y| = {h['absy'][0]:.1f}〜{h['absy'][1]:.1f}（x = ±20 mm の側面にある塊）。", ""]

    shapes = [(transform(legacy, yaw=math.radians(90)), a_z[0], a_z[1], "green"),
              (chamfered(BODY, 7), b_z[0], b_z[1], "green"),
              (rounded_rect(L - 0.5, W - 0.5, 1.0), cell_n[0], cell_n[1], "blue"),
              (rounded_rect(L, W, 1.0), cell_s[0], cell_s[1], "blue")]
    rep += ["## 断面図", "", "緑：基板A（張り出しを ±y に向けた実機外形）・基板B（隅 7 mm 面取り）、青：セル。", ""]
    for zs in ((cell_n[0] + cell_n[1]) / 2, (cell_s[0] + cell_s[1]) / 2, a_z[0] + 0.8, b_z[0] + 0.8):
        fn = f"section_z{zs:+.0f}.svg"
        svg_section(meshes, zs, shapes, os.path.join(out_dir, fn))
        rep.append(f"- [{fn}]({fn})")

    open(os.path.join(out_dir, "fit_report.md"), "w").write("\n".join(rep) + "\n")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
