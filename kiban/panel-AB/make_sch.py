#!/usr/bin/env python3
"""面付けした PCB（panel-AB.kicad_pcb）に対応する回路図を作り、PCB とリンクする。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/panel-AB/make_sch.py

元の回路図（kicad/boardA、kicad/boardB-reverse）は書き換えない。出力（kiban/panel-AB/）：
- panel-AB.kicad_sch：ルート。boardA と boardB-reverse の 2 枚のシートを置くだけ
- boardA.kicad_sch、boardB-reverse.kicad_sch：元の回路図の写し。部品番号に A_ / B_ を付ける（電源シンボルは #A_PWR1 のように）
- B 側は、グローバルラベルと GND を B_ 付きにする（A と B の VSYS、I2C_SDA などを別のネットにする。PCB と同じ）
- PCB で BOM・部品位置ファイルから外している部品（スルーホールの手はんだ部品）は、回路図でも in_bom / in_pos_files を no にする
- sym-lib-table、fp-lib-table（lcsc ライブラリ）と、panel-AB.kicad_pro のルートシートの登録

続けて panel-AB.kicad_pcb を開き、配線はそのままで次のことをして保存する（link()）：
- 各フットプリントに、回路図のシンボルへのリンク（path、シート名）を入れる
- ネット名を回路図のネット名にそろえる（パッドの接続から対応を作り、1 対 1 でなければ止める）
これで「回路図から PCB を更新」と DRC の回路図照合が使える。make_panel.py で PCB を作り直したときも、最後に link() を呼ぶ。
panel-AB を KiCad で開いていないときに実行する。
"""
import collections
import json
import os
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
PROJECT = 'panel-AB'
ROOT_SCH = os.path.join(HERE, PROJECT + '.kicad_sch')
PCB = os.path.join(HERE, PROJECT + '.kicad_pcb')
PRO = os.path.join(HERE, PROJECT + '.kicad_pro')
NS = uuid.UUID('6b1f3c1e-0d6a-4c55-9a51-7a0c3d2f9e10')      # UUID を毎回同じにするための名前空間
ROOT_UUID = str(uuid.uuid5(NS, 'root'))
# (シート名, 元の回路図, 部品番号の接頭辞, ネット名の接頭辞, シートの位置)
SHEETS = [
    ('boardA', os.path.join(REPO, 'kiban', 'EasyEDA', 'kicad', 'boardA', 'boardA.kicad_sch'), 'A_', '', (25.4, 50.8)),
    ('boardB-reverse', os.path.join(REPO, 'kiban', 'EasyEDA', 'kicad', 'boardB-reverse', 'boardB-reverse.kicad_sch'),
     'B_', 'B_', (152.4, 50.8)),
]
LIB_URI = '${KIPRJMOD}/../EasyEDA/kicad/lib/lcsc'


def sheet_uuid(name):
    return str(uuid.uuid5(NS, 'sheet:' + name))


def new_ref(ref, prefix):
    return '#' + prefix + ref[1:] if ref.startswith('#') else prefix + ref


def top_items(text):
    """回路図の一番外の (kicad_sch ...) の直下の要素に分ける。[頭, 要素..., 末尾]"""
    starts = [m.start() + 1 for m in re.finditer(r'\n\t\(', text)]
    end = text.rstrip().rfind('\n)')
    cuts = [0] + starts + [end]
    return [text[a:b] for a, b in zip(cuts, cuts[1:])] + [text[end:]]


def convert_sheet(src, prefix, net_prefix, path, no_bom):
    """元の回路図を、panel-AB のシートとして書き換えた文字列を返す。"""
    text = open(src, encoding='utf-8').read()
    out = []
    n_sym = 0
    for item in top_items(text):
        if item.startswith('\t(sheet_instances'):
            continue                                           # ルートにだけ置く
        if item.startswith('\t(symbol\n'):
            ref = re.search(r'\(property "Reference" "([^"]*)"', item).group(1)
            ref2 = new_ref(ref, prefix)
            item = item.replace(f'(property "Reference" "{ref}"', f'(property "Reference" "{ref2}"', 1)
            item, k = re.subn(
                r'\(instances\s*\(project "[^"]*"\s*\(path "[^"]*"\s*\(reference "[^"]*"\s*\)?\s*\(unit (\d+)\)\s*\)\s*\)\s*\)',
                lambda m: (f'(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "{path}"\n'
                           f'\t\t\t\t\t(reference "{ref2}")\n\t\t\t\t\t(unit {m.group(1)})\n\t\t\t\t)\n\t\t\t)\n\t\t)'),
                item)
            assert k == 1, f'{src}: {ref} の instances が {k} 個'
            if net_prefix and '(lib_id "power:' in item:
                item = re.sub(r'\(property "Value" "([^"]*)"', lambda m: f'(property "Value" "{net_prefix}{m.group(1)}"', item, 1)
            if ref2 in no_bom:
                item = item.replace('(in_bom yes)', '(in_bom no)', 1).replace('(in_pos_files yes)', '(in_pos_files no)', 1)
            n_sym += 1
        elif net_prefix and item.startswith('\t(global_label "'):
            item = item.replace('(global_label "', '(global_label "' + net_prefix, 1)
        out.append(item)
    return ''.join(out), n_sym


def root_sheet():
    parts = [f'(kicad_sch\n\t(version 20260306)\n\t(generator "eeschema")\n\t(generator_version "10.0")\n'
             f'\t(uuid "{ROOT_UUID}")\n\t(paper "A4")\n\t(lib_symbols)\n'
             f'\t(text "panel-AB: boardA + boardB-reverse (make_sch.py で生成)"\n\t\t(exclude_from_sim no)\n'
             f'\t\t(at 25.4 30.48 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2 2)\n\t\t\t)\n\t\t\t(justify left)\n\t\t)\n'
             f'\t\t(uuid "{uuid.uuid5(NS, "title")}")\n\t)\n']
    for page, (name, _, _, _, (x, y)) in enumerate(SHEETS, 2):
        parts.append(
            f'\t(sheet\n\t\t(at {x} {y})\n\t\t(size 101.6 63.5)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n'
            f'\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n'
            f'\t\t(stroke\n\t\t\t(width 0.1524)\n\t\t\t(type solid)\n\t\t)\n\t\t(fill\n\t\t\t(color 0 0 0 0.0000)\n\t\t)\n'
            f'\t\t(uuid "{sheet_uuid(name)}")\n'
            f'\t\t(property "Sheetname" "{name}"\n\t\t\t(at {x} {y - 0.7116} 0)\n\t\t\t(effects\n\t\t\t\t(font\n'
            f'\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left bottom)\n\t\t\t)\n\t\t)\n'
            f'\t\t(property "Sheetfile" "{name}.kicad_sch"\n\t\t\t(at {x} {y + 64.0884} 0)\n\t\t\t(effects\n\t\t\t\t(font\n'
            f'\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left top)\n\t\t\t)\n\t\t)\n'
            f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{ROOT_UUID}"\n\t\t\t\t\t(page "{page}")\n'
            f'\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
    parts.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n\t(embedded_fonts no)\n)\n')
    return ''.join(parts)


def write_tables():
    for kind, ext in (('sym', 'kicad_sym'), ('fp', 'pretty')):
        open(os.path.join(HERE, f'{kind}-lib-table'), 'w', encoding='utf-8').write(
            f'({kind}_lib_table\n\t(version 7)\n\t(lib (name "lcsc")(type "KiCad")(uri "{LIB_URI}.{ext}")(options "")'
            f'(descr "LCSC parts via easyeda2kicad"))\n)\n')


def fix_project():
    """panel-AB.kicad_pro のルートシートを panel-AB.kicad_sch にする（boardB-reverse の設定が残っていた）。"""
    pro = json.load(open(PRO, encoding='utf-8'))
    pro['schematic']['top_level_sheets'] = [{'filename': PROJECT + '.kicad_sch', 'name': PROJECT, 'uuid': ROOT_UUID}]
    pro['sheets'] = [[ROOT_UUID, 'Root']] + [[sheet_uuid(n), n] for n, *_ in SHEETS]
    open(PRO, 'w', encoding='utf-8').write(json.dumps(pro, indent=2, ensure_ascii=False) + '\n')


def make_sch(board):
    no_bom = {f.GetReferenceAsString() for f in board.GetFootprints()
              if f.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM and not f.GetAttributes() & pcbnew.FP_BOARD_ONLY}
    for name, src, prefix, net_prefix, _ in SHEETS:
        text, n = convert_sheet(src, prefix, net_prefix, f'/{ROOT_UUID}/{sheet_uuid(name)}', no_bom)
        open(os.path.join(HERE, name + '.kicad_sch'), 'w', encoding='utf-8').write(text)
        print(f'{name}.kicad_sch：シンボル {n}')
    open(ROOT_SCH, 'w', encoding='utf-8').write(root_sheet())
    write_tables()
    fix_project()


def sch_netlist():
    """回路図のネットリスト：部品番号 → (path, シート名, シートのファイル)、(部品番号, ピン) → ネット名"""
    xml = '/tmp/panel_AB_sch.xml'
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, ROOT_SCH],
                   capture_output=True, text=True, check=True)
    root = ET.parse(xml).getroot()
    comps = {}
    for c in root.iter('comp'):
        sp = c.find('sheetpath')
        comps[c.get('ref')] = (sp.get('tstamps') + c.findtext('tstamps'), sp.get('names'),
                               next((p.get('value') for p in c.iter('property') if p.get('name') == 'Sheetfile'), ''))
    pins = {}
    for n in root.iter('net'):
        for nd in n.iter('node'):
            pins[(nd.get('ref'), nd.get('pin'))] = n.get('name')
    return comps, pins


def link(board):
    """board の各フットプリントを回路図のシンボルにリンクし、ネット名を回路図にそろえる。配線は触らない。"""
    comps, pins = sch_netlist()
    missing = []
    for f in board.GetFootprints():
        ref = f.GetReferenceAsString()
        if ref not in comps:
            if not f.GetAttributes() & pcbnew.FP_BOARD_ONLY:
                missing.append(ref)
            continue
        path, sheetname, sheetfile = comps[ref]
        f.SetPath(pcbnew.KIID_PATH(path))
        f.SetSheetname(sheetname)
        f.SetSheetfile(sheetfile)
    assert not missing, f'回路図に無い部品：{missing}'
    linked = {f.GetReferenceAsString() for f in board.GetFootprints()}
    assert set(comps) <= linked, f'PCB に無い部品：{sorted(set(comps) - linked)}'
    # PCB のネット → 回路図のネット（パッドごとに見る）
    rename = collections.defaultdict(set)
    for f in board.GetFootprints():
        for p in f.Pads():
            key = (f.GetReferenceAsString(), p.GetNumber())
            if p.GetNetname() and key in pins:
                rename[p.GetNetname()].add(pins[key])
            elif key in pins and not pins[key].startswith('unconnected-'):
                raise AssertionError(f'{key}：PCB では未接続、回路図では {pins[key]}')
    bad = {k: v for k, v in rename.items() if len(v) != 1}
    assert not bad, f'1 つの PCB ネットが、回路図の複数のネットに対応している：{bad}'
    rename = {k: v.pop() for k, v in rename.items()}
    dup = [n for n, c in collections.Counter(rename.values()).items() if c > 1]
    assert not dup, f'回路図の 1 つのネットが、PCB の複数のネットに対応している：{dup}'
    unused = [str(n) for n in board.GetNetsByName().keys() if str(n) and str(n) not in rename]
    assert not unused, f'パッドの無い PCB ネット：{unused}'
    nets = board.GetNetsByName()
    changed = 0
    for old, new in rename.items():
        if old != new:
            nets[old].SetNetname(new)
            changed += 1
    print(f'リンクした部品 {len(comps)}、名前を変えたネット {changed}')
    return rename


def track_stats(board):
    c = collections.Counter()
    for t in board.GetTracks():
        c[(t.GetClass(), t.GetLayer(), t.GetWidth(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y)] += 1
    for z in board.Zones():
        c[('ZONE', z.GetFirstLayer(), z.GetNumCorners())] += 1
    return c


def main():
    board = pcbnew.LoadBoard(PCB)
    before = track_stats(board)
    make_sch(board)
    keep = open(PRO, encoding='utf-8').read()          # SaveBoard が既定値で書き直すので、fix_project() のあとの内容を戻す
    link(board)
    pcbnew.SaveBoard(PCB, board)
    open(PRO, 'w', encoding='utf-8').write(keep)
    assert track_stats(pcbnew.LoadBoard(PCB)) == before, '配線・ビア・ゾーンが変わった'
    print(PCB)


if __name__ == '__main__':
    main()
