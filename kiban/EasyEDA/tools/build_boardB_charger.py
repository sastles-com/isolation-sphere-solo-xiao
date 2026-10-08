"""基板B 充電部（BQ25792）の受動部品を、EasyEDA の BoardB 回路図に置く。

U1（BQ25792、C2862876）を (560, 520) に置き、受動部品を下に並べる。値は docs/boardB_schematic_notes.md §2。
再実行すると部品が二重になるので、やり直すときは先に tools/eda_bridge.py の clear_page() で消す。
"""
import sys, time
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_bridge as e
PAGE = '94446b1a98d03840'   # BoardB 回路図の CHARGER ページ
U1 = {'id': 'C2862876', 'ref': 'U1', 'x': 560, 'y': 520, 'val': 'BQ25792', 'nets': {
    '1': 'STAT', '2': 'VBUS', '3': 'VBUS', '4': 'BTST1', '5': 'REGN', '8': 'VBUS', '9': 'VBUS',
    '10': 'GND', '11': 'GND', '13': 'CE', '14': 'I2C_SCL', '15': 'I2C_SDA', '16': 'TS', '17': 'ILIM_HIZ',
    '18': 'BATP', '19': 'BTST2', '20': 'PROG', '21': 'CHG_INT', '22': 'PACK_P', '23': 'PACK_P',
    '24': 'SDRV', '25': 'VSYS', '26': 'SW2', '27': 'GND', '28': 'SW1', '29': 'PMID'}}
# 6（D+）、7（D-）、12（QON#）は未接続（USB 検出とシップ FET は使わない）

P = [
 ('L1','C87572','1uH',{'1':'SW1','2':'SW2'}),
 ('CBT1','C1622','47nF',{'1':'BTST1','2':'SW1'}),
 ('CBT2','C1622','47nF',{'1':'BTST2','2':'SW2'}),
 ('CREGN','C19666','4.7uF',{'1':'REGN','2':'GND'}),
 ('CIN1','C15850','10uF',{'1':'VBUS','2':'GND'}),
 ('CIN2','C15850','10uF',{'1':'VBUS','2':'GND'}),
 ('CIN3','C1591','0.1uF',{'1':'VBUS','2':'GND'}),
 ('CPM1','C15850','10uF',{'1':'PMID','2':'GND'}),
 ('CPM2','C15850','10uF',{'1':'PMID','2':'GND'}),
 ('CPM3','C15850','10uF',{'1':'PMID','2':'GND'}),
 ('CPM4','C1591','0.1uF',{'1':'PMID','2':'GND'}),
 ('CSY1','C15850','10uF',{'1':'VSYS','2':'GND'}),
 ('CSY2','C15850','10uF',{'1':'VSYS','2':'GND'}),
 ('CSY3','C15850','10uF',{'1':'VSYS','2':'GND'}),
 ('CSY4','C15850','10uF',{'1':'VSYS','2':'GND'}),
 ('CSY5','C15850','10uF',{'1':'VSYS','2':'GND'}),
 ('CSY6','C1591','0.1uF',{'1':'VSYS','2':'GND'}),
 ('CBA1','C15850','10uF',{'1':'PACK_P','2':'GND'}),
 ('CBA2','C15850','10uF',{'1':'PACK_P','2':'GND'}),
 ('CSD','C1588','1nF',{'1':'SDRV','2':'GND'}),
 ('RPROG','C25977','6.04k',{'1':'PROG','2':'GND'}),
 ('RIL1','C22869','127k',{'1':'REGN','2':'ILIM_HIZ'}),
 ('RIL2','C25803','100k',{'1':'ILIM_HIZ','2':'GND'}),
 ('RTS1','C23068','5.23k',{'1':'REGN','2':'TS'}),
 ('RTS2','C23000','30.1k',{'1':'TS','2':'GND'}),
 ('RT1','C13564','10k NTC',{'1':'TS','2':'GND'}),
 ('RBP','C22775','100',{'1':'PACK_P','2':'BATP'}),
 ('RCE','C25804','10k',{'1':'CE','2':'GND'}),
 ('RST','C4190','2.2k',{'1':'REGN','2':'STAT_A'}),
 ('DST','C2286','STAT',{'A':'STAT_A','K':'STAT'}),
]
specs = [U1]
for i, (ref, lc, val, nets) in enumerate(P):
    col, row = i % 11, i // 11
    specs.append({'id': lc, 'ref': ref, 'x': 120 + 100 * col, 'y': 380 - 70 * row, 'val': val, 'nets': nets})
for k in range(0, len(specs), 8):
    t = time.time()
    r = e.place(specs[k:k + 8], PAGE)
    print('batch', k // 10, round(time.time() - t, 1), 's', [x.get('err') or x['ref'] for x in r])
