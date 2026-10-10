#!/usr/bin/env python3
"""core-XIAO-04（MCU 基板）と north-pole-04（北極基板）の回路図を作る。基板A / B と同じ書き方の 1 枚の回路図。

  python3 kiban/core-XIAO-04/make_sch.py [core-XIAO-04] [north-pole-04]   # 名前を省くと両方

KiCad で回路図を開いていないときに実行する。出力（基板ごと）：
- <名前>.kicad_sch（回路図）、<名前>.kicad_pro（基板B の設計ルールを引き継ぐ。既にあれば触らない）
共通：core-XIAO-04.kicad_sym（XIAO とブザーの記号）、lib/lcsc.*（北極の部品。easyeda2kicad で取得）、
sym-lib-table / fp-lib-table。最後に kicad-cli でネットリストを書き出し、PARTS の表と一致するかを確かめる。

書き方は kiban/EasyEDA/tools/kicad/kicad_flat.py と同じ（点線の枠と見出し、ピンから 2.54 mm の線 + グローバルラベル、
部品ごとの GND 記号、未接続は × 印）。ネット名は kiban/EasyEDA/docs/interfaces.md に合わせる。
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'kiban', 'EasyEDA', 'tools', 'kicad'))
import kicad_flat as K  # noqa: E402
from eda2kicad_core import det_uuid  # noqa: E402

NAME = 'core-XIAO-04'
NORTH = 'north-pole-04'
SRC03 = '/Users/katano/work/FPC-isolation-sphere/kiban/core-XIAO-03/core-XIAO-03.kicad_sch'


# 部品表（BOM）に入れない部品（はんだジャンパと、テスト用の 1 ピンヘッダ）
NO_BOM = {'JP1', 'TP1', 'TP2'}


class Out(K.Out):
    """部品の位置を 1.27 mm の格子に合わせてから書く（ピンと線の端が格子に乗る）。"""
    def part(self, p, ref_at, val_at):
        p.x, p.y = K_snap(p.x), K_snap(p.y)
        super().part(p, ref_at, val_at)
        # kicad_flat.py が付ける「EasyEDA」欄（旧部品名）は、この基板では意味がないので消す
        self.lines[-1] = re.sub(r'\n\t\t\(property "EasyEDA" "[^"]*"\n(?:\t\t\t.*\n)*?\t\t\)', '', self.lines[-1])
        if p.new in NO_BOM:
            self.lines[-1] = self.lines[-1].replace('(in_bom yes)', '(in_bom no)', 1)


def K_snap(v, g=1.27):
    return round(round(v / g) * g, 4)


BOARD_B_PRO = os.path.join(REPO, 'kiban', 'EasyEDA', 'kicad', 'boardB', 'boardB.kicad_pro')

R0603 = 'Resistor_SMD:R_0603_1608Metric'
C0603 = 'Capacitor_SMD:C_0603_1608Metric'
H254 = 'Connector_PinHeader_2.54mm:PinHeader_1x{:02d}_P2.54mm_Vertical'
H200 = 'Connector_PinHeader_2.00mm:PinHeader_1x{:02d}_P2.00mm_Vertical'

# 北極ケーブル（core-XIAO-04 の J3 = north-pole-04 の J1）
NORTH_PINS = {'1': '3V3_AON', '2': 'HALL_WAKE', '3': 'GND', '4': 'LED_D6', '5': '3V3_MCU'}

# XIAO ESP32S3 のピン名（03 の記号は RP2040 の名前なので付け直す）
XIAO_PINS = {'1': 'D0/GPIO1', '2': 'D1/GPIO2', '3': 'D2/GPIO3', '4': 'D3/GPIO4', '5': 'D4/GPIO5',
             '6': 'D5/GPIO6', '7': 'D6/TX/GPIO43', '8': 'D7/RX/GPIO44', '9': 'D8/GPIO7', '10': 'D9/GPIO8',
             '11': 'D10/GPIO9', '12': '3V3', '13': 'GND', '14': '5V'}

# ピンの割り当て：XIAO の 1〜7 番側（D0〜D6）に LED データ 6 本とブザー、8〜11 番側（D7〜D10）に制御と I2C。
# - D6（GPIO43）は UART0 TX。起動中に High やブートログが出るので LED データには使わない（ブザーなら害がない）
# - D7（GPIO44）は RX。起動中は入力のままなので LED_EN（基板A のプルダウンで OFF）に使う
# - PWR_KILL は D10（GPIO9）。ストラッピングピンではなく、起動中に Low にならない
# - I2C は D8 / D9。ESP32-S3 はどのピンにも割り当てられるので、ファームの Wire.begin() でピンを指定する
# 部品：(部品番号, 記号, 値, フットプリント, LCSC, 種類, {ピン: ネット})
PARTS = {
    'U1': ('XIAO', 'XIAO ESP32S3', f'{NAME}:XIAO-ESP32S3', '', 'ic',
           {'1': 'LED_GPIO1', '2': 'LED_GPIO2', '3': 'LED_GPIO3', '4': 'LED_GPIO4', '5': 'LED_GPIO5', '6': 'LED_GPIO6',
            '7': 'BUZZER', '8': 'LED_EN', '9': 'I2C_SDA', '10': 'I2C_SCL', '11': 'PWR_KILL',
            '12': '3V3_XIAO', '13': 'GND', '14': None}),
    'JP1': ('Jumper:SolderJumper_2_Bridged', '3V3 切り離し', 'Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm',
            '', 'ic', {'1': '3V3_MCU', '2': '3V3_XIAO'}),
    'C1': ('Device:C_Small', '10uF', C0603, 'C19702', 'passive', {'1': '3V3_XIAO', '2': 'GND'}),
    'C2': ('Device:C_Small', '0.1uF', C0603, 'C14663', 'passive', {'1': '3V3_XIAO', '2': 'GND'}),
    # LED データ線の直列抵抗（送り側 = XIAO の近くに置く）。6 本目は北極の LED
    **{f'R{i}': ('Device:R_Small_US', '33Ω', R0603, 'C23140', 'passive',
                 {'1': f'LED_GPIO{i}', '2': f'LED_D{i}'}) for i in range(1, 7)},
    'R7': ('Device:R_Small_US', '10kΩ', R0603, 'C25804', 'passive', {'1': 'LED_D6', '2': 'GND'}),
    'J1': ('Connector_Generic:Conn_01x07', 'RING-L', H254.format(7), '', 'conn',
           {'1': 'GND', '2': '3V3_MCU', '3': 'I2C_SDA', '4': 'I2C_SCL', '5': 'PWR_KILL', '6': 'LED_EN',
            '7': '3V3_AON'}),
    'J2': ('Connector_Generic:Conn_01x07', 'RING-R', H254.format(7), '', 'conn',
           {'1': 'LED_D1', '2': 'LED_D2', '3': 'LED_D3', '4': 'LED_D4', '5': 'LED_D5', '6': 'GND',
            '7': 'HALL_WAKE'}),
    # 北極へ 5 本。GND を真ん中に置き、HALL_WAKE と LED データの両方の隣にする
    'J3': ('Connector_Generic:Conn_01x05', 'NORTH', H200.format(5), '', 'conn', NORTH_PINS),
    # 秋月 AE-BNO055-BO（18 × 11 mm、2.54 mm × 4 ピン 2 列、列間 7.62 mm = DIP-8 と同じ並び）を直接はんだ付けする。
    # 1 VIN、2 GND、3 SDA、4 SCL、5 RESET、6 INT（2.8 V）、7 GND、8 VOUT（2.8 V）。I2C アドレス 0x28（出荷時）
    'U2': ('Connector_Generic:Conn_02x04_Counter_Clockwise', 'AE-BNO055-BO', 'Package_DIP:DIP-8_W7.62mm', '', 'conn',
           {'1': '3V3_MCU', '2': 'GND', '3': 'I2C_SDA', '4': 'I2C_SCL', '5': None, '6': None, '7': 'GND', '8': None}),
    'LS1': ('BUZZER', 'PKLCS1212E4001', f'{NAME}:Buzzer-PKLCS1212', '', 'ic', {'LEAD+': 'BUZZER', 'LEAD-': 'GND'}),
    'C3': ('Device:C_Small', '0.1uF', C0603, 'C14663', 'passive', {'1': 'BUZZER', '2': 'GND'}),
    'D1': ('Device:LED_Small', 'RED', 'LED_SMD:LED_0603_1608Metric', 'C2286', 'ic', {'1': 'GND', '2': 'PWR_LED'}),
    'R8': ('Device:R_Small_US', '1kΩ', R0603, 'C21190', 'passive', {'1': '3V3_MCU', '2': 'PWR_LED'}),
    'TP1': ('Connector_Generic:Conn_01x01', '3V3_MCU', H254.format(1), '', 'conn', {'1': '3V3_MCU'}),
    'TP2': ('Connector_Generic:Conn_01x01', 'GND', H254.format(1), '', 'conn', {'1': 'GND'}),
}

FRAMES = [
    ('MCU（XIAO ESP32S3）', ['U1', 'JP1', 'C1', 'C2'],
     ['基板A の 3V3_MCU を XIAO の 3V3 ピンへ入れる。5V ピンは使わない',
      'USB で書き込むときは、電池側を OFF にするか JP1 を切る（XIAO 内蔵の 3.3 V と 3V3_MCU がぶつかるため）',
      'I2C は D8 / D9（ファームで指定）。プルアップは U2（AE-BNO055-BO）内蔵のものを使う',
      'D6（TX）は起動中に High / ログが出るので LED データに使わない。D7（RX）は起動中は入力']),
    ('LED データ線（33 Ω、XIAO の近くに置く）', ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7'],
     ['LED_D1〜D5 は mother-ring の LINE01〜05 の DIN へ',
      'LED_D6 は北極の LED（6 本目のストリップ、1 個）。起動中の誤点灯を防ぐため R7 でプルダウン']),
    ('mother-ring 接続（1×7、2.54 mm）', ['J1', 'J2'],
     ['J1 / J2 は 03 と同じ位置（x = ±22.54）。mother-ring 側も 1×7 に改版する',
      'GND は J1-1 と J2-6 の 2 本']),
    ('北極（pillar 配線 5 本）', ['J3'],
     ['DRV5032FC（3V3_AON、HALL_WAKE → 基板A の LTC2954）と北極 LED。I2C は北極へ行かない',
      'ジェスチャは磁石ではなくシェイク（U2 の BNO055）。磁石は ON（約 2.15 s）と強制 OFF（約 7.8 s）だけ',
      '北極 LED の電源は 3V3_MCU（最大 15 mA）']),
    ('IMU（秋月 AE-BNO055-BO を直接実装）', ['U2'],
     ['電源は 3V3_MCU（モジュール内の LDO で 2.8 V）。I2C はモジュール内のレベル変換で 3.3 V、プルアップ 10 kΩ 内蔵',
      'RESET（内部プルアップ）、INT、VOUT は未接続。基板上の向き（軸）を球の軸に合わせて置く']),
    ('ブザー', ['LS1', 'C3'], ['D6（GPIO43）で直接駆動する。起動ログで小さく鳴ることがある']),
    ('電源表示・テストピン', ['D1', 'R8', 'TP1', 'TP2'], []),
]


def lib_symbols_03():
    s = open(SRC03, encoding='utf-8').read()
    i = s.index('\t(lib_symbols')
    blocks = {}
    # lib_symbols の子要素（深さ 2）だけを取り出す
    body = s[i:]
    depth, start, k = 0, None, 0
    while k < len(body):
        c = body[k]
        if c == '"':
            k += 1
            while body[k] != '"':
                k += 2 if body[k] == '\\' else 1
        elif c == '(':
            depth += 1
            if depth == 2:
                start = k
        elif c == ')':
            if depth == 2:
                b = body[start:k + 1]
                blocks[re.match(r'\(symbol "([^"]+)"', b).group(1)] = b
            depth -= 1
            if depth == 0:
                break
        k += 1
    xiao = blocks['MOUDLE-SEEEDUINO-XIAO-ESP32S3:MOUDLE-SEEEDUINO-XIAO-ESP32S3']
    xiao = xiao.replace('MOUDLE-SEEEDUINO-XIAO-ESP32S3:MOUDLE-SEEEDUINO-XIAO-ESP32S3', f'{NAME}:XIAO-ESP32S3')
    xiao = xiao.replace('MOUDLE-SEEEDUINO-XIAO-ESP32S3', 'XIAO-ESP32S3')

    def rename(m):
        num = re.search(r'\(number "([^"]+)"', m.group(0)).group(1)
        return re.sub(r'\(name "[^"]*"', f'(name "{XIAO_PINS[num]}"', m.group(0), count=1)
    xiao = re.sub(r'\(pin \w+ \w+[\s\S]*?\(number "[^"]+"', rename, xiao)
    bz = blocks['Speaker:SMS-1308MS-2-R'].replace('Speaker:SMS-1308MS-2-R', f'{NAME}:BUZZER').replace('SMS-1308MS-2-R', 'BUZZER')
    return xiao, bz


# ------------------------------------------------------------------ 北極基板
# pillar の先、北極キャップの下に置く小さな基板。core-XIAO-04 の J3 とケーブル（5 本）でつなぐ
NORTH_PARTS = {
    'J1': ('Connector_Generic:Conn_01x05', 'CORE', H200.format(5), '', 'conn', NORTH_PINS),
    'U1': ('lcsc:DRV5032FCDBZR', 'DRV5032FCDBZR', 'lcsc:SOT-23-3_L2.9-W1.6-P1.90-LS2.8-BR', 'C527532', 'ic',
           {'1': '3V3_AON', '2': 'HALL_WAKE', '3': 'GND'}),
    'C1': ('Device:C_Small', '0.1uF', C0603, 'C14663', 'passive', {'1': '3V3_AON', '2': 'GND'}),
    # 動作確認用の表示：磁石を検出して OUT が Low になると点く（約 1.4 mA、3V3_AON = TPS70933 から）
    'D2': ('Device:LED_Small', 'RED', 'LED_SMD:LED_0603_1608Metric', 'C2286', 'ic', {'1': 'HALL_WAKE', '2': 'HALL_LED'}),
    'R1': ('Device:R_Small_US', '1kΩ', R0603, 'C21190', 'passive', {'1': '3V3_AON', '2': 'HALL_LED'}),
    'D1': ('lcsc:WS2812C-2020-V6', 'WS2812C-2020-V6', 'lcsc:LED-SMD_4P-L2.2-W2.0-P1.00_WS2815C-2020-4P', 'C55109522', 'ic',
           {'1': None, '2': 'GND', '3': 'LED_D6', '4': '3V3_MCU'}),
    'C2': ('Device:C_Small', '0.1uF', C0603, 'C14663', 'passive', {'1': '3V3_MCU', '2': 'GND'}),
}

NORTH_FRAMES = [
    ('core-XIAO-04 へ（J3 とケーブル 5 本）', ['J1'], ['並びは core-XIAO-04 の J3 と同じ']),
    ('起動用ホール（常時オン）', ['U1', 'C1', 'D2', 'R1'],
     ['DRV5032FC：全極性、オープンドレイン、20 Hz、平均 1.3 µA',
      'プルアップは付けない（基板A の LTC2954 PB の内部プルアップを使う。直列 5.1 kΩ と 0.1 µF は基板A 側）',
      'D2 / R1：磁石を検出している間だけ点く動作確認用（約 1.4 mA）。確認が済んだら R1 を外せば電流はゼロ',
      '磁石がないときは LED に 3.3 − 1.9 = 1.4 V しかかからず、ほぼ流れない（PB の内部プルアップは 1.9 V）']),
    ('北極 LED（6 本目のストリップ、1 個）', ['D1', 'C2'],
     ['WS2812C-2020-V6。DIN は XIAO の D5 から 33 Ω 経由。DOUT は未接続。電源は 3V3_MCU']),
]


# ------------------------------------------------------------------ 組み立て
def lcsc_symbols():
    text = open(os.path.join(HERE, 'lib', 'lcsc.kicad_sym'), encoding='utf-8').read()
    out = {}
    for b in K.top_blocks(text):
        m = re.match(r'\(symbol\s+"([^"]+)"', b)
        if m:
            out[f'lcsc:{m.group(1)}'] = re.sub(r'^\(symbol\s+"[^"]+"', f'(symbol "lcsc:{m.group(1)}"', b, count=1)
    return out


def make_parts(name, table, blocks):
    parts = {}
    for ref, (sym, value, fp, lcsc, kind, nets) in table.items():
        lib_id = sym if ':' in sym else f'{NAME}:{"XIAO-ESP32S3" if sym == "XIAO" else sym}'
        if lib_id not in blocks:
            lib, sname = lib_id.split(':')
            blocks[lib_id] = K.stock_symbol(lib, sname)
        p = K.Part(f'{name}-{ref}', value, lcsc, kind, lib_id, blocks[lib_id], fp, nets)
        p.new = ref
        p.x0, p.y0 = 0, -list(table).index(ref)       # 枠の中は表の順に並べる
        parts[ref] = p
    return parts


def build(name, table, frames, lib):
    K.PROJECT = name
    K.ROOT_UUID = det_uuid('root', name)
    parts = make_parts(name, table, lib)
    used = {p.lib_id for p in parts.values()}
    for paper, W, H in (('A4', 297, 210), ('A3', 420, 297)):
        x = y = 12.0
        row_h, sizes = 0.0, []
        for i, (title, refs, notes) in enumerate(frames):
            w, h = K.frame_layout({'title': title}, [parts[r] for r in refs], notes, Out(), 0, 0, f'm{i}')
            if x + w > W - 12 and x > 12:
                x, y, row_h = 12.0, y + row_h + 5, 0.0
            sizes.append((title, refs, notes, x, y))
            x += w + 5
            row_h = max(row_h, h)
        if y + row_h <= H - 10:
            break
    out = Out()
    for i, (title, refs, notes, x, y) in enumerate(sizes):
        K.frame_layout({'title': title}, [parts[r] for r in refs], notes, out, x, y, f'f{i}')
    blocks = {k: lib[k] for k in used}
    blocks['power:GND'] = K.stock_symbol('power', 'GND')
    a = ['(kicad_sch', '\t(version 20260306)\n\t(generator "make_sch.py")\n\t(generator_version "10.0")',
         f'\t(uuid "{K.ROOT_UUID}")', f'\t(paper "{paper}")',
         f'\t(title_block\n\t\t(title "{name}")\n\t\t(company "isolation-sphere-solo-xiao")\n\t)', '\t(lib_symbols']
    a += [blocks[k] for k in sorted(blocks)]
    a.append('\t)')
    a += out.lines
    a.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)')
    a.append(')')
    return '\n'.join(a) + '\n', paper


def write_libs(xiao, bz):
    lib = ['(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "make_sch.py")\n\t(generator_version "10.0")']
    for b in (xiao, bz):
        lib.append('\t' + re.sub(r'^\(symbol "[^"]+:', '(symbol "', b))
    open(os.path.join(HERE, f'{NAME}.kicad_sym'), 'w', encoding='utf-8').write('\n'.join(lib) + '\n)\n')
    rows = [(NAME, f'{NAME}.kicad_sym', f'{NAME}.pretty'), ('lcsc', 'lib/lcsc.kicad_sym', 'lib/lcsc.pretty')]
    for kind, idx in (('sym', 1), ('fp', 2)):
        body = ''.join(f'\t(lib (name "{r[0]}")(type "KiCad")(uri "${{KIPRJMOD}}/{r[idx]}")(options "")(descr ""))\n'
                       for r in rows)
        open(os.path.join(HERE, f'{kind}-lib-table'), 'w').write(f'({kind}_lib_table\n\t(version 7)\n{body})\n')


def write_project(name):
    pro_path = os.path.join(HERE, f'{name}.kicad_pro')
    if not os.path.exists(pro_path):                  # 設計ルールは基板B と同じ（既にあれば触らない）
        pro = json.load(open(BOARD_B_PRO))
        pro['meta']['filename'] = f'{name}.kicad_pro'
        pro['sheets'] = [[det_uuid('root', name), 'Root']]
        pro['boards'] = []
        pro['net_settings']['netclass_patterns'] = []
        pro['net_settings']['netclass_assignments'] = None
        json.dump(pro, open(pro_path, 'w'), indent=2, ensure_ascii=False)


def verify(name, sch, table):
    xml = os.path.join('/tmp', f'{name}.xml')
    subprocess.run([K.KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, sch],
                   capture_output=True, text=True, check=True)
    import xml.etree.ElementTree as ET
    got = {n.get('name').lstrip('/'): sorted(f"{x.get('ref')}.{x.get('pin')}" for x in n.iter('node'))
           for n in ET.parse(xml).getroot().iter('net')}
    want = {}
    for ref, (*_, nets) in table.items():
        for pin, net in nets.items():
            if net:
                want.setdefault(net, []).append(f'{ref}.{pin}')
    want = {k: sorted(v) for k, v in want.items()}
    got_named = {k: v for k, v in got.items() if not k.startswith('unconnected-')}
    bad = [(k, want.get(k), got_named.get(k)) for k in sorted(set(want) | set(got_named)) if want.get(k) != got_named.get(k)]
    return want, bad


if __name__ == '__main__':
    xiao, bz = lib_symbols_03()
    lib = {f'{NAME}:XIAO-ESP32S3': xiao, f'{NAME}:BUZZER': bz, **lcsc_symbols()}
    write_libs(xiao, bz)
    pick = sys.argv[1:] or [NAME, NORTH]
    for name, table, frames in ((NAME, PARTS, FRAMES), (NORTH, NORTH_PARTS, NORTH_FRAMES)):
        if name not in pick:
            continue
        if os.path.exists(os.path.join(HERE, f'~{name}.kicad_sch.lck')):
            print(f'{name}：KiCad で回路図が開いているので飛ばす')
            continue
        text, paper = build(name, table, frames, lib)
        sch = os.path.join(HERE, f'{name}.kicad_sch')
        open(sch, 'w', encoding='utf-8').write(text)
        write_project(name)
        want, bad = verify(name, sch, table)
        print(f'{name}：用紙 {paper}、部品 {len(table)}、ネット {len(want)}')
        for k, w, g in bad:
            print(f'  ⚠️ {k}: 予定 {w} / 回路図 {g}')
        print('  ✅ ネットリスト一致' if not bad else f'  ❌ 不一致 {len(bad)} 件')
