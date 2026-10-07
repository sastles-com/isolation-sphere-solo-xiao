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


RING_T = 1.6          # mother-ring の板厚（z = ±0.8）
CLEAR = 0.5           # セルと隣の基板の間（絶縁フィルムなど）


def max_square(meshes, z0, z1, r=BOARD_R):
    """高さ z0〜z1 に置いた角丸の正方形基板の、入る最大の一辺。"""
    lo, hi = 20.0, 50.0
    for _ in range(14):
        mid = (lo + hi) / 2
        c = box_clearance(meshes, dict(cx=0, cy=0, z0=z0, z1=z1, sx=mid, sy=mid, yaw=0, r=r))
        lo, hi = (mid, hi) if c >= 0 else (lo, mid)
    return lo


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

    # 北から：MCU – セル – mother-ring – セル – 基板A – 基板B（ユーザー指定、2026-10-08）
    cell_n = dict(z0=ring_top + CLEAR, z1=ring_top + CLEAR + T)
    cell_s = dict(z0=ring_bot - CLEAR - T, z1=ring_bot - CLEAR)
    a_top = cell_s["z0"] - CLEAR
    a, b = stack_boxes(a_top - BOARD_T)

    report = ["# 電池・基板の配置検討（fit_check.py の出力）", "",
              "重ね順（北から）：MCU – セル – mother-ring – セル – 基板A – 基板B。",
              f"mother-ring は z = 0（板厚 {RING_T} mm）。南（LiPo 側）は −z。",
              f"セル {L:.0f}×{W:.0f}×{T:.0f} mm、基板 {BOARD:.0f} mm 角（角 R{BOARD_R:.0f}）、"
              f"基板A↔B 間隔 {BOARD_GAP} mm、セルと隣の面の間 {CLEAR} mm。", "",
              "コアの断面は島状なので、角度ごとに最も内側の点を壁とみなす（安全側の概算）。", ""]

    report += ["## セル（50×35×10 mm）", "",
               "| 場所 | 高さ z | 入るか | 入る最大（縦横比 50:35） |", "| --- | --- | --- | --- |"]
    for name, c in (("北：MCU と mother-ring の間", cell_n), ("南：mother-ring と基板A の間", cell_s)):
        fit = cell_fits(meshes, c["z0"], c["z1"], L, W)
        mx, deg = max_footprint(meshes, c["z0"], c["z1"], L / W)
        ok = f"入る（回転 {fit[0]}°、すき間 {fit[1]:.1f} mm）" if fit else "**入らない**"
        report.append(f"| {name} | {c['z0']:.1f}〜{c['z1']:.1f} | {ok} | {mx:.1f} × {mx * W / L:.1f} mm（回転 {deg}°） |")
    report.append("")

    report += ["## 基板（40 mm 角）", "",
               "| 基板 | 高さ z | すき間 | 入る最大の正方形 |", "| --- | --- | --- | --- |"]
    for bx in (a, b):
        c = box_clearance(meshes, bx)
        ms = max_square(meshes, bx["z0"], bx["z1"])
        report.append(f"| {bx['name']} | {bx['z0']:.1f}〜{bx['z1']:.1f} | {'**干渉**' if c < 0 else f'{c:.1f} mm'} | {ms:.1f} mm |")
    report.append("")

    ring_r = (BOARD / 2 - BOARD_R) * math.sqrt(2) + BOARD_R
    report += ["## mother-ring と間隔", "",
               f"- 基板の最遠点は軸から {ring_r:.1f} mm（40 mm 角、R{BOARD_R:.0f}）。",
               f"- mother-ring↔基板A の間隔（面から面）は約 {CLEAR * 2 + T:.1f} mm 必要（セル {T:.0f} mm + 両側のすき間）。"
               "ソケット（FH-1x6SG/RH、ハウジング 8.5 mm）とヘッダ（絶縁体 2.5 mm）を重ねた長さが目安。", ""]

    boxes = [dict(a, color="green"), dict(b, color="green")]
    for c in (cell_n, cell_s):
        fit = cell_fits(meshes, c["z0"], c["z1"], L, W)
        if fit:
            boxes.append(dict(cx=0, cy=0, z0=c["z0"], z1=c["z1"], sx=L, sy=W, yaw=math.radians(fit[0]), color="blue"))
    report += ["## 断面図", ""]
    for zs in ((cell_n["z0"] + cell_n["z1"]) / 2, (cell_s["z0"] + cell_s["z1"]) / 2,
               a["z0"] + 0.8, b["z0"] + 0.8):
        fn = f"section_z{zs:+.0f}.svg"
        svg_section(meshes, zs, boxes, os.path.join(out_dir, fn))
        report.append(f"- [{fn}]({fn})")

    open(os.path.join(out_dir, "fit_report.md"), "w").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
