#!/usr/bin/env python3
"""回路図にテストパッド（KiCad 標準の TestPoint、直径 1.0 mm のパッド）を追加する。

  python3 tools/kicad/testpoints.py boardA     # 基板A
  python3 tools/kicad/testpoints.py boardB     # 基板B

すでに同じ部品番号（TP1…）があれば何もしない。KiCad で回路図を開いていないときに実行する。
PCB には、KiCad の「回路図から基板を更新」で取り込む。

選んだネット（コネクタのピンで測れないものだけ）：
- 基板A：MCU_EN（LTC2954 → MCU 用降圧の EN）、PWR_INT（LTC2954 の INT）。3V3 の 3 系統と VSYS は J1 / J3 のピンで測れる
- 基板B：PACK_P（保護 FET のあと）、BAT_F（ヒューズのあと）、REGN（充電 IC の内部電源）、TS（NTC の電圧）。
  VBUS、VSYS、セルの電圧は J1、J2、J4、J5 のピンで測れる
"""
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
STOCK = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/Connector.kicad_sym'
FOOTPRINT = 'TestPoint:TestPoint_Pad_D1.0mm'
NS = uuid.UUID('6f1b2d40-0000-4000-8000-746573747074')

POINTS = {
    'boardA': [('TP1', 'MCU_EN'), ('TP2', 'PWR_INT')],
    'boardB': [('TP1', 'PACK_P'), ('TP2', 'BAT_F'), ('TP3', 'REGN'), ('TP4', 'TS')],
}


def uid(*a):
    return str(uuid.uuid5(NS, '|'.join(map(str, a))))


def stock_symbol():
    s = open(STOCK, encoding='utf-8').read()
    i = s.index('(symbol "TestPoint"\n')
    j = s.index('\n\t(symbol "', i + 10)
    return '\t' + s[i:j].replace('(symbol "TestPoint"', '(symbol "Connector:TestPoint"', 1).rstrip()


def free_y(text):
    """回路図で使われている y の最大値（この下に置く）。"""
    ys = [float(m.group(1)) for m in re.finditer(r'\(at [-\d.]+ ([-\d.]+)', text)]
    ys += [float(m.group(1)) for m in re.finditer(r'\(xy [-\d.]+ ([-\d.]+)\)', text)]
    return max(ys)


def snap(v, g=1.27):
    return round(round(v / g) * g, 4)


def insert(board):
    path = os.path.join(ROOT, 'kicad', board, f'{board}.kicad_sch')
    s = open(path, encoding='utf-8').read()
    if re.search(r'\(property "Reference" "TP\d+"', s):
        print(f'{board}: テストパッドはすでにある。何もしない')
        return
    root = re.search(r'^\t\(uuid "([^"]+)"\)', s, re.M).group(1)
    project = re.search(r'\(project "([^"]+)"', s).group(1)
    if '(symbol "Connector:TestPoint"' not in s:
        k = s.index('\t(lib_symbols\n') + len('\t(lib_symbols\n')
        s = s[:k] + stock_symbol() + '\n' + s[k:]
    y0 = snap(free_y(s) + 12.7)
    x0 = 25.4
    out = []
    w = 20.32 * len(POINTS[board]) + 10
    out.append(f'\t(rectangle\n\t\t(start {x0 - 5:.2f} {y0 - 10:.2f})\n\t\t(end {x0 - 5 + w:.2f} {y0 + 22:.2f})'
               '\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type dash)\n\t\t)\n\t\t(fill\n\t\t\t(type none)\n\t\t)'
               f'\n\t\t(uuid "{uid(board, "frame")}")\n\t)')
    out.append(f'\t(text "テストパッド（直径 1.0 mm、部品なし。コネクタのピンで測れないネットだけ）"\n\t\t(exclude_from_sim no)'
               f'\n\t\t(at {x0 - 3:.2f} {y0 - 5:.2f} 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.8 1.8)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)'
               f'\n\t\t(uuid "{uid(board, "title")}")\n\t)')
    for i, (ref, net) in enumerate(POINTS[board]):
        x, y = snap(x0 + 20.32 * i), y0
        out.append(f'''\t(symbol
\t\t(lib_id "Connector:TestPoint")
\t\t(at {x} {y} 0)
\t\t(unit 1)
\t\t(body_style 1)
\t\t(exclude_from_sim no)
\t\t(in_bom no)
\t\t(on_board yes)
\t\t(in_pos_files no)
\t\t(dnp no)
\t\t(uuid "{uid(board, ref)}")
\t\t(property "Reference" "{ref}"
\t\t\t(at {x + 2.54} {y - 3.81} 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t)
\t\t(property "Value" "{net}"
\t\t\t(at {x + 2.54} {y - 1.27} 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t)
\t\t(property "Footprint" "{FOOTPRINT}"
\t\t\t(at {x} {y} 0)
\t\t\t(hide yes)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Datasheet" ""
\t\t\t(at {x} {y} 0)
\t\t\t(hide yes)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(pin "1"
\t\t\t(uuid "{uid(board, ref, "pin")}")
\t\t)
\t\t(instances
\t\t\t(project "{project}"
\t\t\t\t(path "/{root}"
\t\t\t\t\t(reference "{ref}")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)''')
        out.append(f'\t(wire\n\t\t(pts\n\t\t\t(xy {x} {y}) (xy {x} {snap(y + 2.54)})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)'
                   f'\n\t\t(uuid "{uid(board, ref, "wire")}")\n\t)')
        out.append(f'\t(global_label "{net}"\n\t\t(shape input)\n\t\t(at {x} {snap(y + 2.54)} 270)\n\t\t(fields_autoplaced yes)'
                   '\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify right)\n\t\t)'
                   f'\n\t\t(uuid "{uid(board, ref, "label")}")\n\t)')
    k = s.rindex('\t(sheet_instances') if '\t(sheet_instances' in s else s.rindex('\n)')
    s = s[:k] + '\n'.join(out) + '\n' + s[k:]
    open(path, 'w', encoding='utf-8').write(s)
    print(f'{board}: テストパッド {len(POINTS[board])} 個を追加（y = {y0}）')


if __name__ == '__main__':
    for b in sys.argv[1:] or POINTS:
        insert(b)
