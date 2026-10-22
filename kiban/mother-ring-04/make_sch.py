#!/usr/bin/env python3
"""mother-ring-04 の回路図を、旧 mother-ring の回路図から作る（文字列の加工）。

  python3 kiban/mother-ring-04/make_sch.py [出力先.kicad_sch]

旧 mother-ring の「外周」（ポゴ接点 J1〜J5、33 Ω の R1〜R5、旧の注記、ネットの書き方）は、そのまま残す。
変えるのは次の 3 つだけ。
  1. 中央（基板A / ESP32 / 電源まわり）の部品、ラベル、配線、枠を取り除く（J6〜J16、C10〜C12、FB1）
  2. 現行の基板との接続を置く：J6 / J7 = 基板A の J1 / J2（1×6）、J8 / J9 = core-XIAO-04 の J1 / J2（1×7）
  3. ネット名を現行に合わせる：+5V → 3V3_LED、GPIO01〜05 → LED_D1〜D5
"""
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
OLD = os.path.join(REPO, 'kiban', 'mother-ring-bk', 'mother-ring.kicad_sch')   # ポゴ接点が 7 パッド（貫通 THR、DIN は表、DOUT は裏）の版
sys.path.insert(0, os.path.join(REPO, 'kiban', 'EasyEDA', 'tools', 'kicad'))
import kicad_flat as K  # noqa: E402

NAME = 'mother-ring-04'
REMOVE_REFS = {f'J{i}' for i in range(6, 18)} | {'C10', 'C11', 'C12', 'FB1'} | {f'R{i}' for i in range(1, 6)}   # 33 Ω は core 側へ移した
RENAME_NETS = {'+5V': '3V3_LED', **{f'DIN0{i}': f'LED_D{i}' for i in range(1, 6)}}     # 33 Ω をなくすので、ポゴ接点の DIN は LED_D そのもの
X_RESISTOR = 150.0           # これより右（y が小さい側）は、旧の R1〜R5 と GPIO / DIN のラベル
Y_CENTRAL = 95.0            # これより下（y が大きい側）が、旧の中央部（POWER / ESP32 の枠）
SOCK6 = 'Connector_PinSocket_2.54mm:PinSocket_1x06_P2.54mm_Vertical'
SOCK7 = 'Connector_PinSocket_2.54mm:PinSocket_1x07_P2.54mm_Vertical'
# (部品番号, 記号, 値, 足型, 位置 x, y, {ピン: ネット})
NEW = [
    ('J6', 'Conn_01x06', 'A-LEFT', SOCK6, 63.5, 109.22,
     {'1': '3V3_LED', '2': 'GND', '3': '3V3_MCU', '4': 'I2C_SDA', '5': 'I2C_SCL', '6': '3V3_AON'}),
    ('J7', 'Conn_01x06', 'A-RIGHT', SOCK6, 107.95, 109.22,
     {'1': '3V3_LED', '2': 'GND', '3': 'GND', '4': 'HALL_WAKE', '5': 'PWR_KILL', '6': 'LED_EN'}),
    ('J8', 'Conn_01x07', 'CORE-J1', SOCK7, 63.5, 140.97,
     {'1': 'GND', '2': '3V3_MCU', '3': 'I2C_SDA', '4': 'I2C_SCL', '5': 'PWR_KILL', '6': 'LED_EN', '7': '3V3_AON'}),
    ('J9', 'Conn_01x07', 'CORE-J2', SOCK7, 107.95, 140.97,
     {'1': 'LED_D1', '2': 'LED_D2', '3': 'LED_D3', '4': 'LED_D4', '5': 'LED_D5', '6': 'GND', '7': 'HALL_WAKE'}),
]
NOTE = ('基板A / core との接続（中央）\n'
        'J6 / J7 = 基板A の J1 / J2（1×6、裏面）。J8 / J9 = core-XIAO-04 の J1 / J2（1×7、表面）。core は基板A に対して 90° 回して重ねる\n'
        '3V3_LED（旧 +5V）は、基板A の 3V3_LED をポゴ接点の 1・6 番へ。LED_D1〜D5 は core の 33 Ω を通った信号で、ポゴ接点の 3 番（DIN）へ直接つなぐ（旧の R1〜R5 は core へ移した）')


def block_end(s, i):
    """s[i] が '(' のブロックの終わり（閉じ括弧の次）。文字列中の括弧は無視する。"""
    d = 0
    j = i
    while True:
        c = s[j]
        if c == '"':
            j += 1
            while s[j] != '"':
                j += 2 if s[j] == '\\' else 1
        elif c == '(':
            d += 1
        elif c == ')':
            d -= 1
            if d == 0:
                return j + 1
        j += 1


def top_blocks(s, kinds):
    out = []
    for m in re.finditer(r'\n\t\((%s)[\s"]' % '|'.join(kinds), s):
        a = m.start() + 2
        out.append((m.group(1), a, block_end(s, a)))
    return out


def at_of(b):
    m = re.search(r'\((?:at|xy) ([-\d.]+) ([-\d.]+)', b)
    return float(m.group(1)), float(m.group(2))


def uid(*t):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, '/'.join((NAME,) + t)))


def pin_offsets(lib_block):
    """lib 記号の、ピン番号 → (x, y)（記号座標、y 上向き）。"""
    return {m.group(3): (float(m.group(1)), float(m.group(2)))
            for m in re.finditer(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) [-\d.]+\)\s*\(length [-\d.]+\)\s*'
                                 r'(?:\(hide \w+\)\s*)?\(name "[^"]*"[^)]*\([^)]*\)[^)]*\)\s*\(number "([^"]+)"', lib_block, re.S)}


def main(out):
    s = open(OLD, encoding='utf-8').read()
    cut = []
    for kind, a, b in top_blocks(s, ('symbol', 'global_label', 'wire', 'junction', 'text_box')):
        blk = s[a:b]
        if kind == 'symbol' and not blk.startswith('(symbol\n\t\t(lib_id'):
            continue                                   # lib_symbols の中身ではなく、配置された記号だけ
        x, y = at_of(blk)
        if kind == 'symbol':
            ref = re.search(r'\(property "Reference" "([^"]+)"', blk).group(1)
            if ref in REMOVE_REFS or (y >= Y_CENTRAL and ref.startswith('#PWR')) or ref in ('#FLG03',) \
                    or (ref.startswith('#PWR') and 118 <= x <= 126 and 70 <= y <= 80):
                cut.append((a, b))
                continue
            if ref == '#PWR048':                       # +3V3（旧の中央）
                cut.append((a, b))
                continue
        elif kind == 'text_box':
            if y >= Y_CENTRAL:
                cut.append((a, b))
        elif y >= Y_CENTRAL or kind == 'junction' or x >= X_RESISTOR or (118 <= x <= 126 and 70 <= y <= 80):   # 後者は J17（最後の DOUT05 の取り出し口）のラベルと電源記号
            cut.append((a, b))
    for a, b in sorted(cut, reverse=True):
        # 前の改行とタブごと消す
        a0 = s.rindex('\n', 0, a)
        s = s[:a0] + s[b:]
    # +5V の記号の値、ラベル名を新しい名前にする
    for old, new in RENAME_NETS.items():
        s = s.replace(f'(property "Value" "{old}"', f'(property "Value" "{new}"')
        s = s.replace(f'(global_label "{old}"', f'(global_label "{new}"')
    s = s.replace('(project "mother-ring"', f'(project "{NAME}"')
    # 新しいコネクタ
    root = re.search(r'^\t\(uuid "([^"]+)"\)', s, re.M).group(1)
    libs = ''
    have = {m.group(1) for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', s)}
    for lib in ('Conn_01x06', 'Conn_01x07'):
        if f'Connector_Generic:{lib}' not in have:
            libs += K.stock_symbol('Connector_Generic', lib) + '\n'
    if libs:
        k = s.index('\t(lib_symbols\n') + len('\t(lib_symbols\n')
        s = s[:k] + libs + s[k:]
    items = []
    for ref, lib, val, fp, x, y, nets in NEW:
        n = int(lib[-2:])
        top = -(n - 1) * 2.54 / 2 if n == 7 else -5.08          # 1 番ピンの位置（記号の中心から。Conn_01x06 は −5.08、Conn_01x07 は −7.62）
        if n == 7:
            top = -7.62
        props = ''
        for name, v, hide, dy in (('Reference', ref, False, 0.0), ('Value', val, False, 2.54), ('Footprint', fp, True, 0),
                                  ('Datasheet', '', True, 0), ('Description', f'Generic connector, single row, 01x{n:02d}', True, 0)):
            props += (f'\n\t\t(property "{name}" "{v}"\n\t\t\t(at {x + 2.54 if not hide else x} {round(y + dy, 4) if not hide else y} 0)'
                      + ('\n\t\t\t(hide yes)' if hide else '') + '\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)'
                      '\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)'
                      + ('' if hide else '\n\t\t\t\t(justify left)') + '\n\t\t\t)\n\t\t)')
        pins = ''.join(f'\n\t\t(pin "{p}"\n\t\t\t(uuid "{uid(ref, "pin", p)}")\n\t\t)' for p in nets)
        items.append(f'\t(symbol\n\t\t(lib_id "Connector_Generic:{lib}")\n\t\t(at {x} {y} 0)\n\t\t(unit 1)\n\t\t(body_style 1)'
                     f'\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n\t\t(dnp no)'
                     f'\n\t\t(uuid "{uid(ref)}"){props}{pins}'
                     f'\n\t\t(instances\n\t\t\t(project "{NAME}"\n\t\t\t\t(path "/{root}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
        for p, net in nets.items():
            py = round(y + top + 2.54 * (int(p) - 1), 4)
            lx = round(x - 5.08, 4)
            items.append(f'\t(global_label "{net}"\n\t\t(shape input)\n\t\t(at {lx} {py} 180)\n\t\t(fields_autoplaced yes)'
                         f'\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify right)\n\t\t)'
                         f'\n\t\t(uuid "{uid(ref, "lbl", p)}")\n\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}"\n\t\t\t(at {round(lx - 6.5, 4)} {py} 0)'
                         f'\n\t\t\t(hide yes)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)'
                         f'\n\t\t\t\t(justify right)\n\t\t\t)\n\t\t)\n\t)')
    note = NOTE.replace('\n', '\\n')
    items.append(f'\t(text_box "{note}"\n\t\t(exclude_from_sim no)\n\t\t(at 41.91 95.25 0)\n\t\t(size 132.08 66.04)'
                 f'\n\t\t(margins 0.9525 0.9525 0.9525 0.9525)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type dash)\n\t\t)'
                 f'\n\t\t(fill\n\t\t\t(type none)\n\t\t)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.778 1.778)\n\t\t\t)'
                 f'\n\t\t\t(justify left top)\n\t\t)\n\t\t(uuid "{uid("frame")}")\n\t)')
    k = s.rindex('\t(sheet_instances')
    s = s[:k] + '\n'.join(items) + '\n' + s[k:]
    open(out, 'w', encoding='utf-8').write(s)
    print(f'{out}：除去 {len(cut)} 件、追加 {len(NEW)} コネクタ')


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, f'{NAME}.kicad_sch')
    main(out)
