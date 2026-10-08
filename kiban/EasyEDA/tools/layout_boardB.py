"""基板B の回路図（CHARGER / PROTECTION の 2 ページ）を、人が読める形で描く。

回路の内容は docs/boardB_schematic_notes.md。描き方は tools/schematic_layout.py。
既存の部品と線を消してから描き直す（clear_page）。

  python3 tools/layout_boardB.py           # 両ページを描き直す
  python3 tools/layout_boardB.py charger   # CHARGER だけ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_bridge as e
from schematic_layout import Sheet

CHARGER = '94446b1a98d03840'
PROTECTION = '3c04743d7cb514cc'


def charger():
    s = Sheet(CHARGER)
    # ---------------- 部品
    s.part('U1', 'C2862876', 'BQ25792', 590, 615)
    s.part('J_CHG', 'C492401', 'CHG IN (wire pads)', 50, 640, bom=False)
    s.part('D_TVS', 'C2900732', 'SMF15A', 120, 640, rot=90)
    for i, (ref, lc, v) in enumerate([('CIN1', 'C15850', '10uF'), ('CIN2', 'C15850', '10uF'), ('CIN3', 'C1591', '0.1uF')]):
        s.part(ref, lc, v, 180 + 55 * i, 640, rot=90)
    for i, (ref, lc, v) in enumerate([('CPM1', 'C15850', '10uF'), ('CPM2', 'C15850', '10uF'),
                                      ('CPM3', 'C15850', '10uF'), ('CPM4', 'C1591', '0.1uF')]):
        s.part(ref, lc, v, 120 + 55 * i, 510, rot=90)
    for i in range(6):
        lc, v = ('C1591', '0.1uF') if i == 5 else ('C15850', '10uF')
        s.part(f'CSY{i + 1}', lc, v, 880 + 45 * i, 690, rot=90)
    s.part('CBA1', 'C15850', '10uF', 890, 550, rot=90)
    s.part('CBA2', 'C15850', '10uF', 940, 550, rot=90)
    s.part('RBP', 'C22775', '100', 1060, 550, rot=90)
    s.part('L1', 'C87572', '1uH', 980, 380)
    s.part('CBT1', 'C1622', '47nF', 870, 330, rot=90)
    s.part('CBT2', 'C1622', '47nF', 1090, 330, rot=90)
    s.part('RPROG', 'C25977', '6.04k', 70, 300, rot=90)
    s.part('RIL1', 'C22869', '127k', 190, 360, rot=90)
    s.part('RIL2', 'C25803', '100k', 190, 220, rot=90)
    s.part('RTS1', 'C23068', '5.23k', 340, 360, rot=90)
    s.part('RTS2', 'C23000', '30.1k', 340, 220, rot=90)
    s.part('RT1', 'C13564', '10k NTC', 420, 220, rot=90)
    s.part('RCE', 'C25804', '10k', 520, 300, rot=90)
    s.part('RST', 'C4190', '2.2k', 620, 360, rot=90)
    s.part('DST', 'C2286', 'STAT', 620, 220, rot=270)
    s.part('CREGN', 'C19666', '4.7uF', 700, 300, rot=90)
    s.part('CSD', 'C1588', '1nF', 760, 300, rot=90)
    s.place()

    # ---------------- 枠
    s.frame(20, 790, 350, 330, '充電入力（線をはんだ付けする 2 穴、5〜12 V）')
    s.frame(380, 790, 420, 330, '充電 IC  U1 BQ25792')
    s.frame(810, 790, 340, 330, '出力（VSYS → 基板A、PACK_P → 保護部）')
    s.frame(810, 450, 340, 200, '電力段（インダクタ、ブートストラップ）')
    s.frame(20, 450, 780, 420, '設定（PROG、入力電流、温度、CE、STAT）と REGN')

    # ---------------- U1：全ピンにラベル
    u1 = {'1': 'STAT', '2': 'VBUS', '3': 'VBUS', '4': 'BTST1', '5': 'REGN', '8': 'VBUS', '9': 'VBUS',
          '10': 'GND', '11': 'GND', '13': 'CE', '14': 'I2C_SCL', '15': 'I2C_SDA', '16': 'TS',
          '17': 'ILIM_HIZ', '18': 'BATP', '19': 'BTST2', '20': 'PROG', '21': 'CHG_INT', '22': 'PACK_P',
          '23': 'PACK_P', '24': 'SDRV', '25': 'VSYS', '26': 'SW2', '27': 'GND', '28': 'SW1', '29': 'PMID'}
    for k, net in u1.items():
        s.label('U1', k, net)
    for k in ('6', '7', '12'):
        x, y = s.pin('U1', k)
        s.text(x - 25, y + 3, 'NC', size=7)

    # ---------------- 充電入力：VBUS レールと PMID レール
    s.rail('VBUS', 700, 90, 350, flag_at=350)
    j1, j2 = s.pin('J_CHG', '1'), s.pin('J_CHG', '2')
    s.wv(j1, (90, 700), 'VBUS') if j1[1] > j2[1] else s.wv(j2, (90, 700), 'VBUS')
    s.gnd(min(j1, j2, key=lambda p: p[1]))
    s.text(30, 590, 'J_CHG：PH 2P の線をはんだ付け（部品なし）', size=7)
    for r in ('D_TVS', 'CIN1', 'CIN2', 'CIN3'):
        s.hang(r, 700, 'VBUS')
    s.rail('PMID', 560, 90, 350, flag_at=350)
    for r in ('CPM1', 'CPM2', 'CPM3', 'CPM4'):
        s.hang(r, 560, 'PMID')

    # ---------------- 出力
    s.rail('VSYS', 740, 850, 1130, flag_at=850)
    for i in range(6):
        s.hang(f'CSY{i + 1}', 740, 'VSYS')
    s.rail('PACK_P', 600, 850, 1130, flag_at=850)
    s.hang('CBA1', 600, 'PACK_P')
    s.hang('CBA2', 600, 'PACK_P')
    s.hang('RBP', 600, 'PACK_P', bottom='BATP', bottom_kind='port')
    s.text(1080, 520, 'BATP：電池の＋を検出', size=7)

    # ---------------- 電力段
    s.label('L1', '1', 'SW1')
    s.label('L1', '2', 'SW2')
    for c, top, bot in (('CBT1', 'BTST1', 'SW1'), ('CBT2', 'BTST2', 'SW2')):
        s.end_label(s.pin(c, s.top(c)), top, 'T', stub=10)
        s.end_label(s.pin(c, s.bottom(c)), bot, 'B', stub=10)

    # ---------------- 設定
    def divider(top_ref, bot_ref, net, port_x, extra=None):
        t_top = s.pin(top_ref, s.top(top_ref))
        s.pwr(t_top, 'REGN')
        a = s.pin(top_ref, s.bottom(top_ref))
        b = s.pin(bot_ref, s.top(bot_ref))
        mid = (a[0], (a[1] + b[1]) // 2)
        s.w(a, mid, net)
        s.w(mid, b, net)
        s.w(mid, (port_x, mid[1]), net)
        s.port((port_x, mid[1]), net, 'L' if port_x < mid[0] else 'R')
        s.gnd(s.pin(bot_ref, s.bottom(bot_ref)))
        if extra:
            c = s.pin(extra, s.top(extra))
            s.w(mid, (c[0], mid[1]), net)
            s.w((c[0], mid[1]), c, net)
            s.gnd(s.pin(extra, s.bottom(extra)))

    s.end_label(s.pin('RPROG', s.top('RPROG')), 'PROG', 'T', stub=10)
    s.gnd(s.pin('RPROG', s.bottom('RPROG')))
    s.text(35, 410, 'PROG 6.04k', size=7)
    s.text(35, 400, '2S / 1.5 MHz', size=7)
    divider('RIL1', 'RIL2', 'ILIM_HIZ', 240)
    s.text(150, 410, '入力電流の上限', size=7)
    divider('RTS1', 'RTS2', 'TS', 290, extra='RT1')
    s.text(300, 410, '温度 TS（NTC は基板上）', size=7)
    s.end_label(s.pin('RCE', s.top('RCE')), 'CE', 'T', stub=10)
    s.gnd(s.pin('RCE', s.bottom('RCE')))
    s.text(480, 410, 'CE：L で充電', size=7)
    s.pwr(s.pin('RST', s.top('RST')), 'REGN')
    s.w(s.pin('RST', s.bottom('RST')), s.pin('DST', 'A'), 'STAT_A')
    s.end_label(s.pin('DST', 'K'), 'STAT', 'B', stub=10)
    s.text(580, 410, '充電表示 LED', size=7)
    s.pwr(s.pin('CREGN', s.top('CREGN')), 'REGN')
    s.gnd(s.pin('CREGN', s.bottom('CREGN')))
    s.end_label(s.pin('CSD', s.top('CSD')), 'SDRV', 'T', stub=10)
    s.gnd(s.pin('CSD', s.bottom('CSD')))
    s.text(680, 410, 'REGN / SDRV', size=7)
    print('CHARGER ops:', s.flush())
    return s


def protection():
    s = Sheet(PROTECTION)
    # ---------------- 部品
    s.part('U2', 'C20345237', 'BQ28Z620', 580, 485)
    s.part('J_CELL2', 'C158012', 'CELL2 (BM/B+)', 60, 730)
    s.part('J_CELL1', 'C158012', 'CELL1 (B-/BM)', 60, 660)
    s.part('F1', 'C108585', 'PTC 5A', 230, 740)
    s.part('Q1', 'C908265', 'FS8205A', 480, 730)
    s.part('CFX1', 'C1591', '0.1uF', 690, 770)
    s.part('CFX2', 'C1591', '0.1uF', 770, 770)
    s.part('CPK1', 'C1591', '0.1uF', 880, 720)
    s.part('CPK2', 'C1591', '0.1uF', 960, 720)
    s.part('RPK', 'C22859', '10', 1070, 760)
    s.part('RVC2', 'C25197', '5.1', 140, 560)
    s.part('RVC1', 'C22775', '100', 140, 510)
    for i, (ref, lc, v) in enumerate([('CVC', 'C15849', '1uF'), ('CVC1', 'C1591', '0.1uF'),
                                      ('CPBI', 'C23630', '2.2uF'), ('RT2', 'C13564', '10k NTC')]):
        s.part(ref, lc, v, 50 + 80 * i, 430, rot=90)
    for i, ref in enumerate(('RCHG', 'RDSG', 'RGC', 'RGD')):
        lc, v = ('C23186', '5.1k') if i < 2 else ('C7250', '10M')
        s.part(ref, lc, v, 960, 560 - 50 * i)
    s.part('RSNS', 'C154630', '2m', 200, 290)
    s.part('RSRN', 'C22775', '100', 180, 190, rot=90)
    s.part('RSRP', 'C22775', '100', 220, 190, rot=90)
    for i, (ref, v) in enumerate([('CSRN', '0.1uF'), ('CSRP', '0.1uF'), ('CSRD', '0.1uF')]):
        s.part(ref, 'C1591', v, 60 + 120 * i, 80, rot=90)
    for y, a, b, dz in ((280, 'RSCL1', 'RSCL2', 'DZ1'), (150, 'RSDA1', 'RSDA2', 'DZ2')):
        s.part(a, 'C22775', '100', 500, y)
        s.part(b, 'C22775', '100', 640, y)
        s.part(dz, 'C22612', '5.6V', 570, y - 60, rot=90)
    s.part('J_AB1', 'C492405', 'TO BOARD A PWR', 880, 220)
    s.part('J_AB2', 'C492405', 'TO BOARD A SIG', 1060, 220)
    s.place()

    # ---------------- 枠
    s.frame(20, 800, 1130, 190, '主電流路：セル → ヒューズ → 保護 FET（共通ドレイン）→ PACK_P')
    s.frame(20, 600, 350, 230, 'セル電圧の検出（VC1 / VC2 / PBI）と温度')
    s.frame(380, 600, 400, 230, '残量計・保護  U2 BQ28Z620')
    s.frame(790, 600, 360, 230, '保護 FET のゲート駆動')
    s.frame(20, 360, 400, 330, '電流シャント（ケルビン接続）')
    s.frame(430, 360, 360, 330, 'I2C の保護（基板A → U2）')
    s.frame(800, 360, 350, 330, '基板A との接続（ピンヘッダ 1x6 × 2）')

    # ---------------- U2
    u2 = {'1': 'BAT_N', '2': 'SRN_F', '3': 'SRP_F', '4': 'TS1', '5': 'G_SCL', '6': 'G_SDA', '7': 'DSG_O',
          '8': 'PACK_S', '9': 'CHG_O', '10': 'PBI', '11': 'VC2_F', '12': 'VC1_F', '13': 'BAT_N'}
    for k, net in u2.items():
        s.label('U2', k, net)

    # ---------------- 主電流路
    c2a, c2b = s.pin('J_CELL2', '1'), s.pin('J_CELL2', '2')
    s.label('J_CELL2', '1', 'BAT_MID')
    j = (150, s.pin('F1', '1')[1])
    s.w(c2b, j, 'BAT_TOP')
    s.w(j, s.pin('F1', '1'), 'BAT_TOP')
    s.w(j, (j[0], j[1] + 30), 'BAT_TOP')
    s.port((j[0], j[1] + 30), 'BAT_TOP', 'T')
    s.label('J_CELL1', '1', 'BAT_N')
    s.label('J_CELL1', '2', 'BAT_MID')
    f_out = s.pin('F1', '2')
    s1, s2 = s.pin('Q1', 'S1'), s.pin('Q1', 'S2')
    k = (380, s1[1])
    s.w(f_out, (k[0], f_out[1]), 'BAT_F')
    s.w((k[0], f_out[1]), k, 'BAT_F')
    s.w(k, s1, 'BAT_F')
    s.w(k, (k[0], k[1] + 30), 'BAT_F')
    s.port((k[0], k[1] + 30), 'BAT_F', 'T')
    s.w(s2, (400, s2[1]), 'PACK_P')
    s.w((400, s2[1]), (400, 650), 'PACK_P')
    s.rail('PACK_P', 650, 400, 1120, flag_at=1120)
    for p in s.P['Q1']['raw']:
        if p[1] == 'D1/D2':  # p = [番号, 名前, x, y, 回転]
            d = 'L' if p[2] < s.P['Q1']['x'] else 'R'
            s.w((p[2], p[3]), (p[2] + (-15 if d == 'L' else 15), p[3]), 'FET_D')
    s.label('Q1', 'G1', 'CHG_G')
    s.label('Q1', 'G2', 'DSG_G')
    s.text(445, 770, 'FET1=充電（電池側） / FET2=放電（パック側）', size=7)
    s.label('CFX1', '1', 'BAT_F')
    s.w(s.pin('CFX1', '2'), s.pin('CFX2', '1'), 'CFX_M')
    s.label('CFX2', '2', 'PACK_P')
    s.text(660, 790, 'FET の両端', size=7)
    s.label('CPK1', '1', 'PACK_P')
    s.w(s.pin('CPK1', '2'), s.pin('CPK2', '1'), 'CPK_M')
    s.gnd(s.pin('CPK2', '2'))
    s.text(860, 745, 'パック端子の ESD', size=7)
    s.label('RPK', '1', 'PACK_P')
    s.label('RPK', '2', 'PACK_S')

    # ---------------- セル電圧・温度
    s.label('RVC2', '1', 'BAT_TOP')
    s.label('RVC2', '2', 'VC2_F')
    s.label('RVC1', '1', 'BAT_MID')
    s.label('RVC1', '2', 'VC1_F')
    for ref, top, bot in (('CVC', 'VC2_F', 'VC1_F'), ('CVC1', 'VC1_F', 'BAT_N'),
                          ('CPBI', 'PBI', 'BAT_N'), ('RT2', 'TS1', 'BAT_N')):
        t, b = s.pin(ref, s.top(ref)), s.pin(ref, s.bottom(ref))
        s.w(t, (t[0], t[1] + 10), top)
        s.port((t[0], t[1] + 10), top, 'R')
        s.w(b, (b[0], b[1] - 10), bot)
        s.port((b[0], b[1] - 10), bot, 'R')

    # ---------------- ゲート駆動
    for ref, a, b in (('RCHG', 'CHG_O', 'CHG_G'), ('RDSG', 'DSG_O', 'DSG_G'),
                      ('RGC', 'CHG_G', 'BAT_F'), ('RGD', 'DSG_G', 'PACK_P')):
        s.label(ref, '1', a)
        s.label(ref, '2', b)

    # ---------------- シャント（ケルビン）
    l, r = s.pin('RSNS', '1'), s.pin('RSNS', '2')
    s.w(l, (100, l[1]), 'GND')
    s.gnd((100, l[1]))
    s.w(r, (300, r[1]), 'BAT_N')
    s.port((300, r[1]), 'BAT_N', 'R')
    s.w(s.pin('RSRN', s.top('RSRN')), l, 'GND')
    s.w(s.pin('RSRP', s.top('RSRP')), r, 'BAT_N')
    s.end_label(s.pin('RSRN', s.bottom('RSRN')), 'SRN_F', 'B', stub=10)
    s.end_label(s.pin('RSRP', s.bottom('RSRP')), 'SRP_F', 'B', stub=10)
    s.text(40, 330, 'GND（PACK−）側 ← RSNS 2mΩ → BAT_N（セル−）側', size=7)
    s.text(40, 320, 'SRN / SRP はシャントの両端のパッドから直接取る', size=7)
    for ref, top, bot in (('CSRN', 'SRN_F', 'BAT_N'), ('CSRP', 'SRP_F', 'BAT_N'), ('CSRD', 'SRN_F', 'SRP_F')):
        t, b = s.pin(ref, s.top(ref)), s.pin(ref, s.bottom(ref))
        s.w(t, (t[0], t[1] + 10), top)
        s.port((t[0], t[1] + 10), top, 'R')
        s.w(b, (b[0], b[1] - 10), bot)
        s.port((b[0], b[1] - 10), bot, 'R')

    # ---------------- I2C
    for a, b, dz, bus, gnet, node in (('RSCL1', 'RSCL2', 'DZ1', 'I2C_SCL', 'G_SCL', 'G_SCLP'),
                                      ('RSDA1', 'RSDA2', 'DZ2', 'I2C_SDA', 'G_SDA', 'G_SDAP')):
        s.label(a, '1', bus)
        n = (s.pin(dz, 'K')[0], s.pin(a, '2')[1])
        s.w(s.pin(a, '2'), n, node)
        s.w(n, s.pin(b, '1'), node)
        s.w(n, s.pin(dz, 'K'), node)
        s.gnd(s.pin(dz, 'A'))
        s.label(b, '2', gnet)

    # ---------------- 基板A 接続
    for k, net in {'1': 'VSYS', '2': 'VSYS', '3': 'VSYS', '4': 'GND', '5': 'GND', '6': 'GND'}.items():
        s.label('J_AB1', k, net)
    for k, net in {'1': 'I2C_SDA', '2': 'GND', '3': 'I2C_SCL', '4': 'CHG_INT', '6': 'GND'}.items():
        s.label('J_AB2', k, net)
    x, y = s.pin('J_AB2', '5')
    s.text(x - 25, y + 3, 'NC', size=7)
    print('PROTECTION ops:', s.flush())
    return s


if __name__ == '__main__':
    which = sys.argv[1:] or ['charger', 'protection']
    if 'charger' in which:
        print('clear CHARGER:', e.clear_page(CHARGER))
        charger()
    if 'protection' in which:
        print('clear PROTECTION:', e.clear_page(PROTECTION))
        protection()
