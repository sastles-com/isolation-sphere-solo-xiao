// tilt-plate.scad — 45deg-plate.stl を角度調整式にした版
//
// 板（60 × 60 mm）を 0〜90° のあいだで 5° 刻みに傾けて、M5 ボルト 1 本で固定する。
// 支点の合わせ面に 72 山（360 / 72 = 5°）のギザギザを付けてある。
//
//   台（base）  ：2020 アルミフレームに M5 × 2 本で留める足と、2 枚の側板（クレビス）。
//                 側板の内面にギザギザ。+X 側の外面に M5 ナットの六角穴。
//   板（plate） ：60 × 60 × 5 mm の板と、側板のあいだに入る羽根（ナックル）。
//                 羽根の両面にギザギザ。
//
// 組み立て：羽根を側板のあいだに入れ、-X 側から M5 × 30 を通して六角穴のナットで締める。
//          緩めると側板が開いてギザギザが外れ、回せる。締めると側板がたわんで噛み合う。
// 角度   ：羽根の付け根（板の中心線）を、-X 側の側板の目盛に合わせる。
//          長い目盛は 15° ごと、0° = 板が水平（真上を向く）、90° = 板が垂直。
//
// 出力：openscad -D 'part="base"'  -o tilt-plate-base.stl  tilt-plate.scad
//       openscad -D 'part="plate"' -o tilt-plate-plate.stl tilt-plate.scad
//       part="assembly" は組んだ姿（angle で角度）。
//
// 座標：X = 支点の軸（板の幅の向き）、Y = フレームの向き、Z = 上。支点は (0, 0, H)。

part  = "assembly";   // "base" | "plate" | "assembly" | "collide"
with_teeth = true;    // false で歯を省く（干渉チェック用）
angle = 45;           // assembly のときの板の角度 [deg]（0〜90、5 の倍数）

$fn = 64;
eps = 0.01;

// ---- ギザギザ ----
N_TEETH = 72;         // 5°
T_RI    = 9;          // 歯の内径（半径）
T_RO    = 17;         // 歯の外径（半径）
T_H     = 0.6;        // 歯の高さ（どの半径でも同じ。同じ形どうしが噛み合う）

// ---- 支点 ----
KNUCKLE_R = 18;       // 羽根と側板の円の半径
KNUCKLE_W = 8;        // 羽根の厚み（歯を除く）
GAP_CLR   = 0.3;      // 緩めたとき、歯の先どうしのすき間（片側）
GAP_HALF  = KNUCKLE_W/2 + 2*T_H + GAP_CLR;   // 側板の内面（歯の付け根）の X。締めると片側 T_H+GAP_CLR たわむ
CHEEK_T   = 6;        // 側板の厚み
H         = 36;       // 足の底から支点までの高さ
M5_HOLE   = 5.4;
M5_NUT_AF = 8.2;      // ナットの二面幅 + すき間
M5_NUT_T  = 4.2;

// ---- 足（2020 フレーム用。元の 45deg-plate のキーと穴を引き継ぐ） ----
FOOT_T     = 5;
FOOT_L     = 58;      // Y 方向
FOOT_HOLE_Y = 23;     // 取り付け穴 ±Y
KEY_W      = 5.8;     // 2020 の溝に入るキー
KEY_H      = 1;

// ---- 板 ----
PLATE_W = 60;         // X
PLATE_L = 60;         // 傾く向き
PLATE_T = 5;
PLATE_D = 24;         // 支点から板の裏面まで（側板の円 KNUCKLE_R より外）
RIB_T   = 4;          // 板の裏の横リブの高さ
RIB_W   = 8;

CHEEK_X = GAP_HALF + CHEEK_T;   // 側板の外面の X

// 板の向き（支点から板への向き）: 角度 a で +Z から -Y へ回る。rotate([a,0,0]) と同じ。

// ---------- ギザギザ ----------
// 面 x = 0 の上に、+X 向きに高さ T_H の歯を 72 個。peak0 は最初の山の角度。
module teeth(peak0) { if (with_teeth) {
    w = 2 * T_RI * tan(180 / N_TEETH);
    for (k = [0 : N_TEETH - 1])
        rotate([peak0 + k * 360 / N_TEETH, 0, 0])
            translate([0, 0, T_RI])
                multmatrix([[0,1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1]])   // 局所 X→Y、Y→X
                    linear_extrude(height = T_RO - T_RI, scale = [T_RO / T_RI, 1])
                        polygon([[-w/2, -eps], [w/2, -eps], [0, T_H]]);
}
}

// ---------- 台 ----------
module cheek_profile_3d(x0, x1) {
    // 支点の円と、足までの柱をつないだ形（X は x0..x1）
    translate([x0, 0, 0]) rotate([0, 90, 0]) linear_extrude(x1 - x0)
        hull() {
            translate([-H, 0]) circle(r = KNUCKLE_R);
            translate([-FOOT_T, -KNUCKLE_R]) square([FOOT_T, 2 * KNUCKLE_R]);
        }
}

module ticks() {
    // -X 側の外面に目盛（5° ごと、15° ごとに長く）
    for (a = [0 : 5 : 90]) {
        len = (a % 15 == 0) ? 5 : 2.5;
        translate([-CHEEK_X - eps, 0, H]) rotate([a, 0, 0])
            translate([0, -0.35, KNUCKLE_R - len]) cube([0.6 + eps, 0.7, len + 1]);
    }
}

module base() {
    difference() {
        union() {
            // 足
            translate([-CHEEK_X, -FOOT_L/2, 0]) cube([2 * CHEEK_X, FOOT_L, FOOT_T]);
            translate([-KEY_W/2, -FOOT_L/2 + 2, -KEY_H]) cube([KEY_W, FOOT_L - 4, KEY_H + eps]);
            // 側板
            cheek_profile_3d(-CHEEK_X, -GAP_HALF);
            cheek_profile_3d( GAP_HALF,  CHEEK_X);
            // 側板の内面のギザギザ（谷が 2.5° のところ → 山は 0°, 5°, ...）
            translate([-GAP_HALF, 0, H]) teeth(0);
            translate([ GAP_HALF, 0, H]) mirror([1, 0, 0]) teeth(0);
        }
        // 支点の穴
        translate([0, 0, H]) rotate([0, 90, 0]) cylinder(d = M5_HOLE, h = 3 * CHEEK_X, center = true);
        // ナットの六角穴（+X 外面）
        translate([CHEEK_X - M5_NUT_T, 0, H]) rotate([0, 90, 0]) rotate([0, 0, 30])
            cylinder(d = M5_NUT_AF / cos(30), h = M5_NUT_T + 1, $fn = 6);
        // 取り付け穴（2020 の M5）
        for (y = [-FOOT_HOLE_Y, FOOT_HOLE_Y])
            translate([0, y, -KEY_H - 1]) cylinder(d = M5_HOLE, h = FOOT_T + KEY_H + 2);
        ticks();
    }
}

// ---------- 板（角度 0 の姿。支点が原点） ----------
module plate() {
    difference() {
        union() {
            // 板
            translate([-PLATE_W/2, -PLATE_L/2, PLATE_D]) cube([PLATE_W, PLATE_L, PLATE_T]);
            // 裏の横リブ
            translate([-PLATE_W/2, -RIB_W/2, PLATE_D - RIB_T]) cube([PLATE_W, RIB_W, RIB_T + eps]);
            // 羽根：支点の円から板の裏までの三角の板
            hull() {
                rotate([0, 90, 0]) cylinder(r = KNUCKLE_R, h = KNUCKLE_W, center = true);
                translate([-KNUCKLE_W/2, -PLATE_L/2 + 6, PLATE_D - eps]) cube([KNUCKLE_W, PLATE_L - 12, eps]);
            }
            // 羽根の両面のギザギザ（山を 2.5° ずらす → 5° の倍数で側板と噛み合う）
            translate([ KNUCKLE_W/2, 0, 0]) teeth(180 / N_TEETH);
            translate([-KNUCKLE_W/2, 0, 0]) mirror([1, 0, 0]) teeth(180 / N_TEETH);
        }
        rotate([0, 90, 0]) cylinder(d = M5_HOLE, h = 3 * KNUCKLE_W, center = true);
    }
}

if (part == "base") {
    base();
} else if (part == "plate") {
    // 板の表を下にして印刷（羽根が上を向く）
    rotate([180, 0, 0]) translate([0, 0, -(PLATE_D + PLATE_T)]) plate();
} else if (part == "collide") {
    // 干渉チェック：台と板の重なり（with_teeth=false で使う）
    intersection() { base(); translate([0, 0, H]) rotate([angle, 0, 0]) plate(); }
} else {
    color("SteelBlue") base();
    color("Orange") translate([0, 0, H]) rotate([angle, 0, 0]) plate();
}
