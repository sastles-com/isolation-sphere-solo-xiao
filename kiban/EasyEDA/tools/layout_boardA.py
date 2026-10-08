"""基板A の回路図（POWER / LED_IO の 2 ページ）を、人が読める形で描く。

部品の選定と値は docs/boardA_schematic_notes.md。描き方は tools/schematic_layout.py。
既存の部品と線を消してから描き直す。

  python3 tools/layout_boardA.py          # 両ページ
  python3 tools/layout_boardA.py power    # POWER だけ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_bridge as e
from schematic_layout import Sheet

POWER = 'e671a2341d4b3a66'
LED_IO = 'a9ace616ca30334c'


def vlab(s, ref, top, bot):
    """縦の 2 端子部品：上のピンと下のピンに、ネット名の文字を付ける（GND は下向き）。"""
    s.end_label(s.pin(ref, s.top(ref)), top, 'T')
    s.end_label(s.pin(ref, s.bottom(ref)), bot, 'B')


def hlab(s, ref, left, right):
    """横の 2 端子部品：左右のピンに、ネット名の文字を付ける。"""
    l, r = sorted(('1', '2'), key=lambda k: s.pin(ref, k)[0])
    s.label(ref, l, left, stub=20)
    s.label(ref, r, right, stub=20)


def divider(s, top_ref, bot_ref, top_net, mid_net, bot_net='GND', port_dx=50):
    """縦に 2 つ並べた抵抗：上の端を top_net、中点を mid_net（右へ引き出す）、下の端を bot_net に。"""
    s.end_label(s.pin(top_ref, s.top(top_ref)), top_net, 'T')
    a = s.pin(top_ref, s.bottom(top_ref))
    b = s.pin(bot_ref, s.top(bot_ref))
    mid = (a[0], (a[1] + b[1]) // 2)
    s.w(a, mid, mid_net)
    s.w(mid, b, mid_net)
    s.w(mid, (mid[0] + port_dx, mid[1]), mid_net)
    s.port((mid[0] + port_dx, mid[1]), mid_net, 'R')
    s.end_label(s.pin(bot_ref, s.bottom(bot_ref)), bot_net, 'B')
    return mid


def power():
    s = Sheet(POWER)
    # ---------------- 部品
    s.part('U3', 'C683782', 'LTC2954-1', 160, 640)
    s.part('RPB', 'C23186', '5.1k', 330, 720)
    s.part('CPB', 'C1591', '0.1uF', 420, 640, rot=90)
    s.part('CONT', 'C159798', '0.33uF', 300, 520, rot=90)
    s.part('CPDT1', 'C15849', '1uF', 380, 520, rot=90)
    s.part('CPDT2', 'C64705', '0.22uF', 460, 520, rot=90)
    s.part('CVIN3', 'C1591', '0.1uF', 60, 520, rot=90)
    s.part('RKILL', 'C25803', '100k', 520, 640, rot=90)
    s.part('U4', 'C89347', 'TPS70933', 760, 660)
    s.part('CIN4', 'C15849', '1uF', 920, 560, rot=90)
    s.part('COUT4', 'C23630', '2.2uF', 1010, 560, rot=90)
    s.part('U5', 'C3200405', 'TPS62933', 200, 230)
    s.part('CIN5', 'C15850', '10uF', 400, 180, rot=90)
    s.part('CIN6', 'C1591', '0.1uF', 460, 180, rot=90)
    s.part('CSS', 'C1589', '10nF', 520, 180, rot=90)
    s.part('CBST2', 'C1591', '0.1uF', 600, 180, rot=90)
    s.part('L2', 'C279948', '2.2uH', 730, 300)
    s.part('RFT', 'C25967', '31.6k', 860, 250, rot=90)
    s.part('RFB', 'C25804', '10k', 860, 130, rot=90)
    s.part('COUT5', 'C45783', '22uF', 980, 180, rot=90)
    s.part('COUT6', 'C45783', '22uF', 1050, 180, rot=90)
    s.place()

    # ---------------- 枠
    s.frame(20, 790, 560, 380, '電源 ON/OFF  U3 LTC2954-1（磁石の長押し）')
    s.frame(590, 790, 560, 380, '常時オン 3.3 V  U4 TPS70933')
    s.frame(20, 400, 1130, 370, 'MCU 用 3.3 V 降圧  U5 TPS62933（1.2 MHz、LTC2954 が EN を制御）')

    # ---------------- U3 LTC2954-1（TSOT-23-8：1 VIN、2 PB、3 ONT、4 GND、5 INT、6 EN、7 PDT、8 KILL）
    for k, net in {'1': 'VSYS', '2': 'PB_F', '3': 'ONT', '4': 'GND', '5': 'PWR_INT', '6': 'MCU_EN',
                   '7': 'PDT', '8': 'PWR_KILL'}.items():
        s.label('U3', k, net)
    hlab(s, 'RPB', 'HALL_WAKE', 'PB_F')
    vlab(s, 'CPB', 'PB_F', 'GND')
    s.text(300, 760, 'HALL_WAKE：北極 DRV5032FC（磁石で L）', size=7)
    vlab(s, 'CONT', 'ONT', 'GND')
    vlab(s, 'CPDT1', 'PDT', 'GND')
    vlab(s, 'CPDT2', 'PDT', 'GND')
    s.text(270, 580, 'ON 長押し 約 2.15 s', size=7)
    s.text(360, 580, '強制 OFF 約 7.9 s（1 + 0.22 uF）', size=7)
    vlab(s, 'CVIN3', 'VSYS', 'GND')
    vlab(s, 'RKILL', '3V3_MCU', 'PWR_KILL')
    s.text(480, 700, 'KILL は 3V3_MCU へプルアップ', size=7)
    s.text(40, 450, 'EN（MCU_EN）は U5 の EN に直結（外付けプルアップなし。U5 の内部プルアップ 0.7 uA）', size=7)
    s.text(40, 440, 'PWR_INT はテストパッドへ（任意）', size=7)

    # ---------------- U4 TPS70933（SOT-23-5：1 IN、2 GND、3 EN、4 NC、5 OUT）
    for k, net in {'1': 'VSYS', '2': 'GND', '3': 'VSYS', '5': '3V3_AON'}.items():
        s.label('U4', k, net)
    x, y = s.pin('U4', '4')
    s.text(x + (5 if x > s.P['U4']['x'] else -25), y + 3, 'NC', size=7)
    vlab(s, 'CIN4', 'VSYS', 'GND')
    vlab(s, 'COUT4', '3V3_AON', 'GND')
    s.text(620, 470, '3V3_AON：北極の DRV5032FC だけに給電（待機電流 1.4 uA）', size=7)

    # ---------------- U5 TPS62933（SOT-583-8：1 RT、2 EN、3 VIN、4 GND、5 SW、6 BST、7 SS、8 FB）
    for k, net in {'1': 'GND', '2': 'MCU_EN', '3': 'VSYS', '4': 'GND', '5': 'M_SW', '6': 'M_BST',
                   '7': 'M_SS', '8': 'M_FB'}.items():
        s.label('U5', k, net)
    vlab(s, 'CIN5', 'VSYS', 'GND')
    vlab(s, 'CIN6', 'VSYS', 'GND')
    vlab(s, 'CSS', 'M_SS', 'GND')
    vlab(s, 'CBST2', 'M_BST', 'M_SW')
    hlab(s, 'L2', 'M_SW', '3V3_MCU')
    divider(s, 'RFT', 'RFB', '3V3_MCU', 'M_FB')
    vlab(s, 'COUT5', '3V3_MCU', 'GND')
    vlab(s, 'COUT6', '3V3_MCU', 'GND')
    s.text(40, 360, 'RT = GND：1.2 MHz', size=7)
    s.text(800, 360, '3.3 V = 0.8 x (1 + 31.6k / 10k)', size=7)
    print('POWER ops:', s.flush())
    return s


def led_io():
    s = Sheet(LED_IO)
    # ---------------- 部品
    s.part('U6', 'C2876603', 'TPS566238P', 180, 620)
    for i, (ref, lc, v) in enumerate([('CIN7', 'C15850', '10uF'), ('CIN8', 'C15850', '10uF'),
                                      ('CIN9', 'C15850', '10uF'), ('CIN10', 'C1591', '0.1uF')]):
        s.part(ref, lc, v, 380 + 60 * i, 720, rot=90)
    s.part('CVCC', 'C15849', '1uF', 380, 560, rot=90)
    s.part('CBST3', 'C1591', '0.1uF', 450, 560, rot=90)
    s.part('L3', 'C76855', '2.2uH', 560, 470)
    s.part('RUP', 'C23266', '93.1k', 680, 650, rot=90)
    s.part('RLO', 'C4184', '20k', 680, 530, rot=90)
    s.part('CFF', 'C1671', '47pF', 740, 650, rot=90)
    for i in range(4):
        s.part(f'COUT{7 + i}', 'C45783', '22uF', 60 + 60 * i, 450, rot=90)
    s.part('RLEN', 'C25803', '100k', 330, 450, rot=90)
    s.part('RSDA', 'C23162', '4.7k', 830, 680, rot=90)
    s.part('RSCL', 'C23162', '4.7k', 910, 680, rot=90)
    s.part('RINT', 'C25804', '10k', 990, 680, rot=90)
    s.part('J_ML', 'C492405', 'MOTHER LEFT', 120, 220)
    s.part('J_MR', 'C492405', 'MOTHER RIGHT', 380, 220)
    s.part('J_BA1', 'C492405', 'TO BOARD B PWR', 720, 220)
    s.part('J_BA2', 'C492405', 'TO BOARD B SIG', 980, 220)
    s.place()

    # ---------------- 枠
    s.frame(20, 790, 780, 420, 'LED 用 3.3 V 降圧  U6 TPS566238P（6 A、LED_EN で ON）')
    s.frame(810, 790, 340, 420, 'プルアップ（3V3_MCU、基板A に集約）')
    s.frame(20, 360, 540, 330, 'mother-ring 接続（1x6 × 2、左右の張り出し）')
    s.frame(570, 360, 580, 330, '基板B 接続（ピンヘッダ 1x6 × 2）')

    # ---------------- U6 TPS566238P（1 VCC、2 FB、3 EN、4 PGND、5/6 VIN、7 BST、8 SW、9 PG）
    for k, net in {'1': 'L_VCC', '2': 'L_FB', '3': 'LED_EN', '4': 'GND', '5': 'VSYS', '6': 'VSYS',
                   '7': 'L_BST', '8': 'L_SW', '9': 'L_PG'}.items():
        s.label('U6', k, net)
    for r in ('CIN7', 'CIN8', 'CIN9', 'CIN10'):
        vlab(s, r, 'VSYS', 'GND')
    vlab(s, 'CVCC', 'L_VCC', 'GND')
    vlab(s, 'CBST3', 'L_BST', 'L_SW')
    hlab(s, 'L3', 'L_SW', '3V3_LED')
    mid = divider(s, 'RUP', 'RLO', '3V3_LED', 'L_FB', port_dx=-50)
    vlab(s, 'CFF', '3V3_LED', 'L_FB')
    for i in range(4):
        vlab(s, f'COUT{7 + i}', '3V3_LED', 'GND')
    vlab(s, 'RLEN', 'LED_EN', 'GND')
    s.text(620, 770, '出力 = 0.6 x (1 + 93.1k / 20k) = 3.39 V', size=7)
    s.text(620, 760, '（WS2812C の下限 3.3 V に余裕。実測後に RUP を調整）', size=7)
    s.text(300, 400, 'LED_EN：GND へ 100k（MCU 起動前は OFF）', size=7)
    s.text(40, 400, 'L_PG：テストパッドへ（任意）', size=7)

    # ---------------- プルアップ
    vlab(s, 'RSDA', '3V3_MCU', 'I2C_SDA')
    vlab(s, 'RSCL', '3V3_MCU', 'I2C_SCL')
    vlab(s, 'RINT', '3V3_MCU', 'CHG_INT')
    s.text(830, 600, 'I2C 4.7k、CHG_INT 10k', size=7)
    s.text(830, 590, 'PWR_KILL の 100k は POWER ページ', size=7)

    # ---------------- コネクタ（interfaces.md §2、easyeda_workflow.md §4.3）
    for ref, pins in (('J_ML', {'1': '3V3_LED', '2': 'GND', '3': '3V3_MCU', '4': 'I2C_SDA', '5': 'I2C_SCL', '6': '3V3_AON'}),
                      ('J_MR', {'1': '3V3_LED', '2': 'GND', '3': 'GND', '4': 'HALL_WAKE', '5': 'PWR_KILL', '6': 'LED_EN'}),
                      ('J_BA1', {'1': 'VSYS', '2': 'VSYS', '3': 'VSYS', '4': 'GND', '5': 'GND', '6': 'GND'}),
                      ('J_BA2', {'1': 'I2C_SDA', '2': 'GND', '3': 'I2C_SCL', '4': 'CHG_INT', '6': 'GND'})):
        for k, net in pins.items():
            s.label(ref, k, net)
    x, y = s.pin('J_BA2', '5')
    s.text(x - 25, y + 3, 'NC', size=7)
    s.text(40, 330, 'J_ML：左（3V3_LED_L / GND_L / 3V3_MCU / SDA / SCL / 3V3_AON）', size=7)
    s.text(40, 320, 'J_MR：右（3V3_LED_R / GND_R / GND_SYS / HALL_WAKE / PWR_KILL / LED_EN）', size=7)
    s.text(590, 330, 'J_BA1 / J_BA2 は基板B の J_AB1 / J_AB2 と同じピン配置', size=7)
    print('LED_IO ops:', s.flush())
    return s


if __name__ == '__main__':
    which = sys.argv[1:] or ['power', 'led_io']
    if 'power' in which:
        print('clear POWER:', e.clear_page(POWER))
        power()
    if 'led_io' in which:
        print('clear LED_IO:', e.clear_page(LED_IO))
        led_io()
