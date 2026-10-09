#!/usr/bin/env python3
"""基板B を「裏表逆」にして取り付ける版（boardB-reverse）を作る。KiCad 付属の Python で動かす。

  python3 tools/kicad/pcb_mirror.py headers kicad/boardB-reverse/boardB-reverse.kicad_pcb
  python3 tools/kicad/pcb_mirror.py unhook  kicad/boardB-reverse/boardB-reverse.kicad_pcb

headers：基板B のルール（部品は表面 F.Cu、In1 = GND）のまま、ヘッダ（J2、J3）だけを 180° 回す。
         この基板は、部品面を下（内殻側）に向け、y 軸まわりに裏返して取り付ける。取り付けると左右が反転するので、
         設計上の 1 番を x = +6.35 に置けば、取り付けたときに基板A の J3 / J4 の 1 番（x = −6.35）と重なる

（以下は、部品ごと裏面へ移す方式。今は使っていない）

  python3 tools/kicad/pcb_mirror.py flip   kicad/boardB-reverse/boardB-reverse.kicad_pcb
  python3 tools/kicad/pcb_mirror.py unhook kicad/boardB-reverse/boardB-reverse.kicad_pcb

flip  ：部品・配線・ビア・ゾーン・図形を、x = 0 の線で左右に裏返す（部品は裏面へ、F.Cu ⇄ B.Cu、In1 ⇄ In2）。
        そのあと、基板A とのヘッダ（J2、J3）を回して、上から見た 1 番の位置を基板A の J3 / J4 と同じに戻す
unhook：回したヘッダのパッドに、別のネットの配線がつながったままになるので、その配線を消す（引き直しは自動配線で）

2 つに分けるのは、KiCad 10.0.3 の Python では、部品を消すと、それまでに取った参照が使えなくなるため。
"""
import sys

import pcbnew

mm = pcbnew.ToMM
HEADERS = {'J2': ('1', -6.35, -16.5), 'J3': ('1', -6.35, 16.5)}     # 基板A の J3 / J4 の 1 番（上から見た座標）


def flip_dir():
    return getattr(pcbnew, 'FLIP_DIRECTION_LEFT_RIGHT', True)


def pad_xy(f, num):
    for p in f.Pads():
        if p.GetNumber() == num:
            q = p.GetPosition()
            return round(mm(q.x), 3), round(mm(q.y), 3)


def flip(path):
    b = pcbnew.LoadBoard(path)
    c = pcbnew.VECTOR2I(0, 0)
    d = flip_dir()
    n = {'fp': 0, 'track': 0, 'zone': 0, 'drawing': 0}
    for f in b.GetFootprints():
        f.Flip(c, d)
        n['fp'] += 1
    for t in b.GetTracks():
        t.Flip(c, d)
        n['track'] += 1
    for z in b.Zones():
        z.Flip(c, d)
        n['zone'] += 1
    for g in b.GetDrawings():
        g.Flip(c, d)
        n['drawing'] += 1
    for f in b.GetFootprints():
        ref = f.GetReferenceAsString()
        if ref in HEADERS:
            num, x, y = HEADERS[ref]
            for ang in (0, 90, 180, 270):
                if pad_xy(f, num) == (x, y):
                    break
                f.SetOrientationDegrees(f.GetOrientationDegrees() + 90)
            print(ref, '1 番', pad_xy(f, num), 'OK' if pad_xy(f, num) == (x, y) else 'NG')
    pcbnew.SaveBoard(path, b)
    print('裏返した', n, '層数', b.GetCopperLayerCount())


def headers(path):
    b = pcbnew.LoadBoard(path)
    for f in b.GetFootprints():
        ref = f.GetReferenceAsString()
        if ref in HEADERS:
            num, x, y = HEADERS[ref]
            want = (-x, y)                    # 取り付けで左右が反転するので、設計上は鏡写しの位置
            for ang in (0, 90, 180, 270):
                if pad_xy(f, num) == want:
                    break
                f.SetOrientationDegrees(f.GetOrientationDegrees() + 90)
            print(ref, '設計上の 1 番', pad_xy(f, num), 'OK' if pad_xy(f, num) == want else 'NG')
    pcbnew.SaveBoard(path, b)


def unhook(path):
    b = pcbnew.LoadBoard(path)
    pads = []
    for f in b.GetFootprints():
        if f.GetReferenceAsString() in HEADERS:
            for p in f.Pads():
                pads.append((p, p.GetNetname()))
    bad = []
    for t in b.GetTracks():
        ends = [t.GetPosition()] if t.GetClass() == 'PCB_VIA' else [t.GetStart(), t.GetEnd()]
        for p, net in pads:
            if t.GetNetname() != net and any(p.HitTest(e) for e in ends):
                bad.append(t)
                break
    print('別のネットのパッドにつながる配線', len(bad), sorted({t.GetNetname() for t in bad}))
    for t in bad:
        b.Remove(t)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)


if __name__ == '__main__':
    {'flip': flip, 'headers': headers, 'unhook': unhook}[sys.argv[1]](sys.argv[2])
