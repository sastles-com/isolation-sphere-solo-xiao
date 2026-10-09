#!/usr/bin/env python3
"""基板B の自動配線（Freerouting）。KiCad 付属の Python で動かす。

  python3 tools/kicad/pcb_route.py prep  <作業フォルダ>   # ネットクラスと GND 面を入れ、Specctra の DSN を出す
  （Freerouting で配線して ses を作る）
  python3 tools/kicad/pcb_route.py apply <作業フォルダ>   # ses を取り込み、ゾーンを塗り直して routed.kicad_pcb に保存

作業フォルダには boardB.kicad_pcb と boardB.kicad_pro を置く（元のファイルは書き換えない）。
層：F.Cu = 配線、In1.Cu = GND 面（電源層にして、自動配線に使わせない）、In2.Cu = 配線、B.Cu = 配線。
BAT_N（セルのマイナス、2 つ目の GND）は面にせず配線で引く。
"""
import json
import os
import sys

import pcbnew

POWER_3A = ['VSYS', 'PACK_P', 'BAT_F', 'BAT_TOP', 'BAT_MID', 'BAT_N']       # 電池電流（最大 約 3 A）が流れる
POWER_SW = ['VBUS', 'PMID', 'SW1', 'SW2']                                    # 充電の電力段
OUTLINE = [(-11.8, -19.7), (11.8, -19.7), (19.7, -11.8), (19.7, 11.8), (11.8, 19.7), (-11.8, 19.7), (-19.7, 11.8), (-19.7, -11.8)]


def set_rules(work):
    p = os.path.join(work, 'boardB.kicad_pro')
    d = json.load(open(p))
    ns = d['net_settings']
    base = dict(ns['classes'][0])
    base.update(clearance=0.15, track_width=0.2, via_diameter=0.6, via_drill=0.3)
    ns['classes'] = [base]
    # 0.4 mm ピッチの QFN（U3）の隣り合うピンをつなぐ必要があるので、自動配線の線幅は控えめにする。
    # 3 A の経路は、配線のあとで太くする（または銅箔のベタで補う）
    for name, width, via in (('Power3A', 0.4, (0.8, 0.4)), ('PowerSW', 0.3, (0.6, 0.3))):
        c = dict(base)
        c.update(name=name, track_width=width, clearance=0.15, via_diameter=via[0], via_drill=via[1], priority=1)
        ns['classes'].append(c)
    ns['netclass_patterns'] = [{'netclass': 'Power3A', 'pattern': n} for n in POWER_3A] + \
                              [{'netclass': 'PowerSW', 'pattern': n} for n in POWER_SW]
    r = d['board']['design_settings']['rules']
    r.update(min_clearance=0.15, min_track_width=0.15, min_text_height=0.5, min_text_thickness=0.08)
    json.dump(d, open(p, 'w'), indent=2)


def add_plane(b, layer, net):
    mm = pcbnew.FromMM
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(b.FindNet(net))
    ol = z.Outline()
    ol.NewOutline()
    for x, y in OUTLINE:
        ol.Append(mm(x), mm(y))
    z.SetMinThickness(mm(0.2))
    z.SetLocalClearance(mm(0.2))
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.4))
    b.Add(z)


if __name__ == '__main__':
    stage, work = sys.argv[1], sys.argv[2]
    pcb = os.path.join(work, 'boardB.kicad_pcb')
    if stage == 'prep':
        set_rules(work)
        b = pcbnew.LoadBoard(pcb)
        b.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)  # 面の層には配線させない
        add_plane(b, pcbnew.In1_Cu, 'GND')
        pcbnew.SaveBoard(pcb, b)
        b = pcbnew.LoadBoard(pcb)
        ok = pcbnew.ExportSpecctraDSN(b, os.path.join(work, 'boardB.dsn'))
        print('DSN', 'OK' if ok else 'NG')
    elif stage == 'apply':
        b = pcbnew.LoadBoard(pcb)
        ok = pcbnew.ImportSpecctraSES(b, os.path.join(work, 'boardB.ses'))
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        pcbnew.SaveBoard(os.path.join(work, 'routed.kicad_pcb'), b)
        print('SES', 'OK' if ok else 'NG', 'tracks', len(b.GetTracks()))
