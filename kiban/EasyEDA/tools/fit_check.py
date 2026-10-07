"""電池と基板スタックがコア内に収まるかを、シェル CAD の STL から概算する。

標準ライブラリのみ。STL を z 一定の面で切った断面（線分の集合）と、
配置候補の直方体（z 軸まわりに回転可）の断面を比べ、干渉と最小すき間を求める。

座標系（mm）：赤道面 z = 0、北が +z、南（LiPo 側）が -z。
- mother-ring は作り直す（EasyEDA で改版）ため障害物に含めない。
  代わりに、新しい mother-ring に必要な開口半径を出力する
- core-north-03_fixed.stl はそのまま（z = 0.8〜35.9）
- core-south-03_fixed.stl は同じく +z 向きでモデル化されているので、
  赤道軸まわりに 180° 回して置く（y → -y、z → -z）

使い方:
  python3 -I tools/fit_check.py [STL ディレクトリ] [出力ディレクトリ]
"""
import math
import os
import struct
import sys

DEFAULT_STL_DIR = os.path.expanduser("~/work/FPC-isolation-sphere/shell-cad/output")
DEFAULT_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs", "fit")

BOARD = 40.0          # 基板の外形（角）
BOARD_T = 1.6         # 基板厚
BOARD_R = 3.0         # 基板の角の丸み半径
BOARD_GAP = 7.0       # 基板A↔B 間隔（easyeda_workflow.md §4.2）
FILM = 0.5            # 基板B と LiPo の間の絶縁フィルム
CELL = (50.0, 35.0, 10.0)  # 2000 mAh セル 1 個（FPC-isolation-sphere docs/01 の概寸）
Z_STEP = 1.0


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


def _rot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


ENV_BIN_DEG = 2


def envelope(segs):
    """断面の内側包絡：角度 2° ごとに、軸から最も近い断面点の半径。

    コアは島状の断面（穴あきの殻）なので、島と島のすき間を通り抜けないよう、
    各角度で最も内側の点を壁とみなす。点のない角度は両隣の小さい方で埋める。
    """
    n = 360 // ENV_BIN_DEG
    env = [math.inf] * n
    for a, b in segs:
        for t in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
            i = int((math.degrees(math.atan2(y, x)) % 360) // ENV_BIN_DEG) % (360 // ENV_BIN_DEG)
            env[i] = min(env[i], math.hypot(x, y))
    for _ in range(n):
        filled = False
        for i in range(n):
            if env[i] == math.inf:
                nb = min(env[(i - 1) % n], env[(i + 1) % n])
                if nb < math.inf:
                    env[i] = nb
                    filled = True
        if not filled:
            break
    return env


def rect_clearance(env, cx, cy, sx, sy, yaw, r=0.0):
    """角丸矩形（中心・寸法・回転・角の半径）と内側包絡の最小すき間（半径方向）。負なら干渉。"""
    hx, hy = sx / 2, sy / 2
    pts = []
    steps = max(2, int(max(sx, sy)))
    for k in range(steps + 1):
        t = -1 + 2 * k / steps
        pts += [(t * (hx - r), -hy), (t * (hx - r), hy), (-hx, t * (hy - r)), (hx, t * (hy - r))]
    if r > 0:
        for qx, qy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
            for k in range(7):
                a = math.radians(15 * k)
                pts.append((qx * (hx - r + r * math.cos(a)), qy * (hy - r + r * math.sin(a))))
    best = math.inf
    for p in pts:
        x, y = _rot(p, yaw)
        x, y = cx + x, cy + y
        i = int((math.degrees(math.atan2(y, x)) % 360) // ENV_BIN_DEG) % (360 // ENV_BIN_DEG)
        best = min(best, env[i] - math.hypot(x, y))
    return best


def box_clearance(meshes, box):
    """box = dict(cx, cy, z0, z1, sx, sy, yaw)。全断面での最小すき間。"""
    z = box["z0"] + 0.01
    worst = math.inf
    while z < box["z1"]:
        segs = []
        for m in meshes:
            segs += m.slice(z)
        if not segs:
            z += Z_STEP
            continue
        c = rect_clearance(envelope(segs), box["cx"], box["cy"], box["sx"], box["sy"], box["yaw"], box.get("r", 0.0))
        if c < 0:
            return -1.0
        worst = min(worst, c)
        z += Z_STEP
    return worst


def stack_boxes(board_a_bottom):
    a = dict(name="基板A", cx=0, cy=0, z0=board_a_bottom, z1=board_a_bottom + BOARD_T,
             sx=BOARD, sy=BOARD, yaw=0, r=BOARD_R)
    b_top = board_a_bottom - BOARD_GAP
    b = dict(name="基板B", cx=0, cy=0, z0=b_top - BOARD_T, z1=b_top, sx=BOARD, sy=BOARD, yaw=0, r=BOARD_R)
    return [a, b]


def max_footprint(meshes, z0, z1, aspect, yaw_step=5):
    """高さ z0〜z1、縦横比 aspect の直方体（軸中心）が入る最大の長辺と、そのときの回転。"""
    best = (0.0, 0)
    for deg in range(0, 90, yaw_step):
        lo, hi = 0.0, 80.0
        for _ in range(14):
            mid = (lo + hi) / 2
            c = box_clearance(meshes, dict(cx=0, cy=0, z0=z0, z1=z1, sx=mid, sy=mid / aspect,
                                           yaw=math.radians(deg)))
            lo, hi = (mid, hi) if c >= 0 else (lo, mid)
        if lo > best[0]:
            best = (lo, deg)
    return best


def cell_fits(meshes, z0, z1, sx, sy):
    """sx × sy の矩形を 5° 刻みで回して入るか。入れば (回転, すき間)。"""
    best = None
    for deg in range(0, 180, 5):
        c = box_clearance(meshes, dict(cx=0, cy=0, z0=z0, z1=z1, sx=sx, sy=sy, yaw=math.radians(deg)))
        if c >= 0 and (best is None or c > best[1]):
            best = (deg, c)
    return best


def edge_room(meshes, z, half=BOARD / 2):
    """基板の各辺の中点から外側へ、殻までの距離（XH などを置く余地）。"""
    segs = []
    for m in meshes:
        segs += m.slice(z)
    res = {}
    for name, d in (("+x", (1, 0)), ("-x", (-1, 0)), ("+y", (0, 1)), ("-y", (0, -1))):
        start = (d[0] * half, d[1] * half)
        best = math.inf
        for a, b in segs:
            # 半直線 start + t·d と線分 ab の交点
            ex, ey = b[0] - a[0], b[1] - a[1]
            den = d[0] * ey - d[1] * ex
            if abs(den) < 1e-12:
                continue
            t = ((a[0] - start[0]) * ey - (a[1] - start[1]) * ex) / den
            u = ((a[0] - start[0]) * d[1] - (a[1] - start[1]) * d[0]) / den
            if t > 0 and 0 <= u <= 1:
                best = min(best, t)
        res[name] = best
    return res


def svg_section(meshes, z, boxes, path):
    s = 4.0
    segs = []
    for m in meshes:
        segs += m.slice(z)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-200 -200 400 400" width="400" height="400">',
             '<rect x="-200" y="-200" width="400" height="400" fill="white"/>',
             f'<text x="-195" y="-185" font-size="12">z = {z:.1f} mm</text>']
    for a, b in segs:
        lines.append(f'<line x1="{a[0]*s:.1f}" y1="{-a[1]*s:.1f}" x2="{b[0]*s:.1f}" y2="{-b[1]*s:.1f}" stroke="black" stroke-width="0.6"/>')
    for bx in boxes:
        if not (bx["z0"] <= z <= bx["z1"]):
            continue
        hx, hy = bx["sx"] / 2, bx["sy"] / 2
        pts = [_rot((x, y), bx["yaw"]) for x, y in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
        pts = " ".join(f"{(bx['cx']+x)*s:.1f},{-(bx['cy']+y)*s:.1f}" for x, y in pts)
        color = bx.get("color", "blue")
        lines.append(f'<polygon points="{pts}" fill="{color}" fill-opacity="0.2" stroke="{color}"/>')
    lines.append("</svg>")
    open(path, "w").write("\n".join(lines))


def main():
    stl_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STL_DIR
    out_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    meshes = [
        Mesh(load_stl(os.path.join(stl_dir, "core-north-03_fixed.stl"))),
        Mesh(load_stl(os.path.join(stl_dir, "core-south-03_fixed.stl"), flip=True)),
    ]
    report = ["# 電池・基板の配置検討（fit_check.py の出力）", "",
              f"セル {CELL[0]}×{CELL[1]}×{CELL[2]} mm × 2、基板 {BOARD} mm 角、基板間隔 {BOARD_GAP} mm、フィルム {FILM} mm。",
              "すき間が負（干渉）の候補は載せない。南半球（z < 0）を LiPo 側とする。", ""]

    # 基板Aの下面高さを振って、基板スタック自体が入る範囲を調べる
    report += ["## 基板スタック", "", "基板A下面の高さを 0.5 mm 刻みで振り、両方の基板が殻に当たらない範囲を調べた。", "",
               "| 基板A下面 z | 基板A すき間 | 基板B すき間 |", "| ---: | ---: | ---: |"]
    stack_ok = []
    for za in [x * 0.5 for x in range(-12, 29)]:
        a, b = stack_boxes(za)
        ca, cb = box_clearance(meshes, a), box_clearance(meshes, b)
        fa = "干渉" if ca < 0 else f"{ca:.1f}"
        fb = "干渉" if cb < 0 else f"{cb:.1f}"
        report.append(f"| {za:.1f} | {fa} | {fb} |")
        if ca >= 0 and cb >= 0:
            stack_ok.append(za)
    report.append("")

    if not stack_ok:
        report += ["基板スタックが入る高さがない。"]
        open(os.path.join(out_dir, "fit_report.md"), "w").write("\n".join(report) + "\n")
        print("\n".join(report))
        return
    za = max(stack_ok, key=lambda z: min(box_clearance(meshes, x) for x in stack_boxes(z)))
    a, b = stack_boxes(za)
    report += [f"以下、基板A下面 z = {za:.1f} mm（すき間が最大の高さ）で検討する。", ""]

    L, W, T = CELL
    south_top = b["z0"] - FILM
    north_bottom = max(a["z1"], 1.0) + 0.5   # 基板Aと mother-ring（z = ±1）の上
    regions = [("南：基板Bの下", south_top - 2 * T, south_top, south_top - T, south_top),
               ("北：mother-ring の上", north_bottom, north_bottom + 2 * T, north_bottom, north_bottom + T)]
    report += ["## 電池が入るか", "",
               "セル 1 個（平置き、厚さ 10 mm）と 2 個重ね（20 mm）を、5° 刻みで回して調べた。",
               "", "| 場所 | 高さ範囲 z | 50×35 平置き 1 個 | 50×35 平置き 2 段 | 入る最大（縦横比 50:35、厚さ 10） | 入る最大（正方形、厚さ 10） |",
               "| --- | --- | --- | --- | --- | --- |"]
    fits = {}
    for name, z2a, z2b, z1a, z1b in regions:
        one = cell_fits(meshes, z1a, z1b, L, W)
        two = cell_fits(meshes, z2a, z2b, L, W)
        mx, mdeg = max_footprint(meshes, z1a, z1b, L / W)
        sq, sdeg = max_footprint(meshes, z1a, z1b, 1.0)
        fits[name] = (one, z1a, z1b)
        f1 = f"入る（{one[0]}°、すき間 {one[1]:.1f}）" if one else "入らない"
        f2 = f"入る（{two[0]}°、すき間 {two[1]:.1f}）" if two else "入らない"
        report.append(f"| {name} | {min(z1a, z2a):.1f}〜{max(z1b, z2b):.1f} | {f1} | {f2} | "
                      f"{mx:.1f} × {mx * W / L:.1f}（{mdeg}°） | {sq:.1f} × {sq:.1f}（{sdeg}°） |")
    report.append("")

    ring_r = (BOARD / 2 - BOARD_R) * math.sqrt(2) + BOARD_R
    report += ["## 新しい mother-ring に必要な開口", "",
               f"基板（{BOARD:.0f} mm 角、角 R{BOARD_R:.0f}）の最遠点は軸から {ring_r:.1f} mm。"
               f"基板スタックが赤道面を通る場合、mother-ring の開口は半径 {ring_r + 0.5:.1f} mm 以上（0.5 mm の余裕込み）が必要。"
               "現行 KiCad の mother-ring（kiban-mother-ring.stl）の開口は最小半径約 17 mm で、通らない。", ""]
    room = edge_room(meshes, b["z0"] + BOARD_T / 2)
    report += ["## 基板Bの周囲", "",
               "基板Bの各辺の中点から殻までの距離（横向きコネクタなどを置く余地）：" +
               "、".join(f"{k} {v:.1f} mm" for k, v in room.items()), ""]

    boxes = [dict(a, color="green"), dict(b, color="green")]
    for name, (one, z1a, z1b) in fits.items():
        if one:
            boxes.append(dict(cx=0, cy=0, z0=z1a, z1=z1b, sx=L, sy=W, yaw=math.radians(one[0]), color="blue"))
    sections = [a["z0"] + 0.8, b["z0"] + 0.8, south_top - T / 2, south_top - T - 5, north_bottom + T / 2]
    report.append("## 断面図")
    report.append("")
    for zs in sections:
        fn = f"section_z{zs:+.0f}.svg"
        svg_section(meshes, zs, boxes, os.path.join(out_dir, fn))
        report.append(f"- [{fn}]({fn})")

    open(os.path.join(out_dir, "fit_report.md"), "w").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
