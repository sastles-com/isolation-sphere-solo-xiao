#!/usr/bin/env python3
"""goldberg の LED（WS2812B 記号 + neon:WS2812C-2020-nocut 足型）を、LCSC C55109522（WS2812C-2020-V6）に置き換える。

  python3 kiban/goldberg/swap_led_v6.py sch [フォルダ]      # 回路図（普通の Python）。先にこちら
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/goldberg/swap_led_v6.py pcb [フォルダ] [--pads goldberg|lcsc]   # PCB（KiCad 付属の Python）

KiCad で goldberg の回路図・PCB を開いていないときに実行する。フォルダを省くと、このファイルのあるフォルダ。

やること
- 足型：LCSC の足型（easyeda2kicad で取得）を使う。lcsc.pretty/WS2812C-2020-V6.kicad_mod。
  ピン番号は LCSC のまま：1 DO、2 GND、3 DI、4 VDD。attr だけ through_hole → smd に直す。
  パッドの寸法は --pads で選ぶ。lcsc = LCSC の寸法そのまま（0.8 × 0.8、内側の間隔 0.94 mm。配線の引き直しが必要）、
  goldberg = 今の足型と同じ位置と寸法（0.5 × 0.5 / 0.5 × 0.6、x ±1.0、y ±0.6。配線はそのまま使える）
  LCSC の足型は、データシートの上から見た図を 180° 回した向きで作られている（1 番 = DO が左上）。
  そのため、PCB 上の位置は変えずに、向きだけ +180° する
- 記号：見た目とピンの位置は WS2812B のまま、ピン番号と名前を LCSC に合わせた goldberg:WS2812C-2020-V6 を使う
  （VDD 1→4、DOUT 2→1、VSS 3→2 GND、DIN 4→3）。配線は切れない。Value、Footprint、Datasheet、LCSC Part も入れる
- PCB のパッドのネットは、旧番号から新番号へ移す（同じ物理位置のピンが同じネットのまま）
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
# --pads goldberg のときのパッド（LCSC の番号。今の足型の位置と寸法を 180° 回したもの）
GOLDBERG_PADS = {'1': ('-1 -0.6', '0.5 0.5'), '2': ('-1 0.6', '0.5 0.6'), '3': ('1 0.6', '0.5 0.5'), '4': ('1 -0.6', '0.5 0.6')}

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_SYM = 'LED:WS2812B'
NEW_NAME = 'WS2812C-2020-V6'
NEW_SYM = f'goldberg:{NEW_NAME}'
OLD_FP = 'WS2812C-2020-nocut'
NEW_FP = f'lcsc:{NEW_NAME}'
LCSC = 'C55109522'
DATASHEET = 'https://www.lcsc.com/datasheet/C55109522.pdf'
# 旧ピン（名前、番号）→ 新ピン（名前、番号）
SYM_MAP = {'VDD': ('VDD', '4'), 'DOUT': ('DO', '1'), 'VSS': ('GND', '2'), 'DIN': ('DI', '3')}
PAD_MAP = {'1': '4', '2': '1', '3': '2', '4': '3'}      # 旧パッド番号 → 新パッド番号
LCSC_FP_SRC = os.path.join(HERE, 'lcsc.pretty', f'{NEW_NAME}.kicad_mod')


def block_end(s, i):
    """s[i] の '(' に対応する ')' の次の位置（文字列中の括弧は無視）。"""
    d, k = 0, i
    while k < len(s):
        c = s[k]
        if c == '"':
            k += 1
            while s[k] != '"':
                k += 2 if s[k] == '\\' else 1
        elif c == '(':
            d += 1
        elif c == ')':
            d -= 1
            if d == 0:
                return k + 1
        k += 1
    raise ValueError('括弧が閉じていない')


def prop(name, value, at, hide=True):
    h = '\n\t\t\t(hide yes)' if hide else ''
    return (f'(property "{name}" "{value}"\n\t\t\t(at {at})\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no){h}'
            '\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)')


# ------------------------------------------------------------------ 回路図
def new_symbol(old):
    s = old.replace(f'(symbol "{OLD_SYM}"', f'(symbol "{NEW_SYM}"', 1)
    s = s.replace('WS2812B_', f'{NEW_NAME}_')
    s = re.sub(r'(\(property "Value" )"[^"]*"', rf'\1"{NEW_NAME}"', s, count=1)
    s = re.sub(r'(\(property "Footprint" )"[^"]*"', rf'\1"{NEW_FP}"', s, count=1)
    s = re.sub(r'(\(property "Datasheet" )"[^"]*"', rf'\1"{DATASHEET}"', s, count=1)
    s = re.sub(r'(\(property "Description" )"[^"]*"', r'\1"RGB LED with integrated controller (WS2812C-2020-V6, LCSC C55109522)"', s, count=1)
    i = s.find('(property "ki_fp_filters"')
    if i >= 0:                                   # 旧足型の絞り込み条件は不要
        j = block_end(s, i)
        s = s[:i].rstrip('\t\n') + '\n\t\t\t' + s[j:].lstrip()
    out, k = [], 0
    for m in re.finditer(r'\(pin \w+ \w+', s):   # ピンの名前と番号を付け替える
        if m.start() < k:
            continue
        e = block_end(s, m.start())
        pin = s[m.start():e]
        nm = re.search(r'\(name "([^"]*)"', pin).group(1)
        new_name, new_num = SYM_MAP[nm]
        pin = re.sub(r'(\(name )"[^"]*"', rf'\1"{new_name}"', pin, count=1)
        pin = re.sub(r'(\(number )"[^"]*"', rf'\1"{new_num}"', pin, count=1)
        out.append(s[k:m.start()] + pin)
        k = e
    out.append(s[k:])
    s = ''.join(out)
    i = s.find('(property "Datasheet"')
    j = block_end(s, i)
    return s[:j] + '\n\t\t\t' + prop('LCSC Part', LCSC, '0 0 0') + s[j:]


def sch(d):
    path = os.path.join(d, 'goldberg.kicad_sch')
    s = open(path, encoding='utf-8').read()
    i = s.index(f'(symbol "{OLD_SYM}"')
    j = block_end(s, i)
    new = new_symbol(s[i:j])
    s = s[:i] + new + s[j:]
    # 部品（80 個）：記号・値・足型・LCSC Part・ピン番号
    marker = f'(lib_id "{OLD_SYM}")'
    out, k, n = [], 0, 0
    while True:
        m = s.find(marker, k)
        if m < 0:
            break
        st = s.rfind('\n\t(symbol\n', 0, m) + 1
        e = block_end(s, st + 1)
        b = s[st:e]
        b = b.replace(marker, f'(lib_id "{NEW_SYM}")', 1)
        b = re.sub(r'(\(property "Value" )"[^"]*"', rf'\1"{NEW_NAME}"', b, count=1)
        b = re.sub(r'(\(property "Footprint" )"[^"]*"', rf'\1"{NEW_FP}"', b, count=1)
        b = re.sub(r'(\(property "Datasheet" )"[^"]*"', rf'\1"{DATASHEET}"', b, count=1)
        fp = re.search(r'\(property "Footprint" "[^"]*"\s*\(at ([-\d. ]+)\)', b)
        fi = b.index('(property "Footprint"')
        fe = block_end(b, fi)
        b = b[:fe] + '\n\t\t' + prop('LCSC Part', LCSC, fp.group(1)).replace('\n\t\t\t', '\n\t\t\t').replace('\n\t\t)', '\n\t\t)') + b[fe:]
        b = re.sub(r'\(pin "(\d)"', lambda mm: f'(pin "{PAD_MAP[mm.group(1)]}"', b)
        out.append(s[k:st] + b)
        k = e
        n += 1
    out.append(s[k:])
    s = ''.join(out)
    open(path, 'w', encoding='utf-8').write(s)
    # 記号ライブラリ（プロジェクト用）
    lib = ['(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "swap_led_v6.py")\n\t(generator_version "10.0")',
           '\t' + new.replace(f'(symbol "{NEW_SYM}"', f'(symbol "{NEW_NAME}"', 1) + '\n)']
    open(os.path.join(d, 'goldberg.kicad_sym'), 'w', encoding='utf-8').write('\n'.join(lib) + '\n')
    tables(d)
    print(f'回路図：{n} 個を {NEW_SYM}（{NEW_FP}、LCSC {LCSC}）に置き換えた')


def tables(d):
    for kind, fn, rows in (('sym', 'sym-lib-table', [('goldberg', 'goldberg.kicad_sym')]),
                           ('fp', 'fp-lib-table', [('lcsc', 'lcsc.pretty')])):
        p = os.path.join(d, fn)
        old = open(p, encoding='utf-8').read() if os.path.exists(p) else f'({kind}_lib_table\n\t(version 7)\n)\n'
        for nick, f in rows:
            if f'(name "{nick}")' not in old:
                row = f'\t(lib (name "{nick}")(type "KiCad")(uri "${{KIPRJMOD}}/{f}")(options "")(descr ""))\n'
                old = old.rstrip()[:-1] + row + ')\n'
        open(p, 'w', encoding='utf-8').write(old)


# ------------------------------------------------------------------ PCB
def rename_nets(b, d):
    """回路図の自動ネット名（Net-(D7-DOUT) など）は、ピン名が変わると変わる。PCB のネット名を回路図に合わせる。"""
    import pcbnew  # noqa: F401
    xml = '/tmp/goldberg_swap_netlist.xml'
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml,
                    os.path.join(d, 'goldberg.kicad_sch')], capture_output=True, text=True, check=True)
    want = {frozenset((x.get('ref'), x.get('pin')) for x in n.iter('node')): n.get('name')
            for n in ET.parse(xml).getroot().iter('net')}
    members = {}
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname():
                members.setdefault(p.GetNetname(), set()).add((f.GetReferenceAsString(), p.GetNumber()))
    ren = {nm: want[frozenset(s)] for nm, s in members.items()
           if nm.startswith('Net-(') and frozenset(s) in want and want[frozenset(s)] != nm}
    for nm, new in ren.items():
        b.FindNet(nm).SetNetname(new)
    return len(ren)


def pcb(d):
    import pcbnew
    path = os.path.join(d, 'goldberg.kicad_pcb')
    # LoadBoard のあとでは FootprintLoad が使えない（KiCad 10 の Python）ので、先に足型を読む
    newfp = pcbnew.FootprintLoad(os.path.join(d, 'lcsc.pretty'), NEW_NAME)
    if newfp is None:
        raise SystemExit('lcsc.pretty の足型が読めない')
    pro = os.path.join(d, 'goldberg.kicad_pro')
    keep = open(pro, encoding='utf-8').read() if os.path.exists(pro) else None   # 保存で書き換えられるので戻す
    b = pcbnew.LoadBoard(path)
    info = []
    for f in b.GetFootprints():                  # 部品を消す前に、必要な値をすべて普通の値で控える
        if str(f.GetFPID().GetLibItemName()) != OLD_FP:
            continue
        if f.IsFlipped():
            raise SystemExit(f'{f.GetReferenceAsString()} は裏面。この道具は表面だけ')
        r = f.Reference()
        info.append({
            'ref': f.GetReferenceAsString(), 'x': f.GetPosition().x, 'y': f.GetPosition().y,
            'rot': f.GetOrientationDegrees(), 'path': f.GetPath().AsString(),
            'sheetname': f.GetSheetname(), 'sheetfile': f.GetSheetfile(),
            'nets': {p.GetNumber(): p.GetNetname() for p in f.Pads()},
            'rx': r.GetPosition().x, 'ry': r.GetPosition().y, 'rang': r.GetTextAngleDegrees(),
            'rw': r.GetTextSize().x, 'rh': r.GetTextSize().y, 'rt': r.GetTextThickness(),
            'rvis': r.IsVisible(), 'rlayer': r.GetLayer(), 'rmirror': r.IsMirrored(),
        })
    n = 0
    for it in info:
        old = b.FindFootprintByReference(it['ref'])   # 消すたびに探し直す（古い参照は使えなくなる）
        b.Remove(old)
        nf = pcbnew.FOOTPRINT(newfp)
        nf.SetReference(it['ref'])
        nf.SetFPID(pcbnew.LIB_ID('lcsc', NEW_NAME))
        nf.SetValue(NEW_NAME)
        nf.SetPosition(pcbnew.VECTOR2I(it['x'], it['y']))
        nf.SetOrientationDegrees(it['rot'] + 180.0)   # 位置は同じ。LCSC の足型は 180° 回った向きなので回す
        if it['path']:
            nf.SetPath(pcbnew.KIID_PATH(it['path']))
        nf.SetSheetname(it['sheetname'])
        nf.SetSheetfile(it['sheetfile'])
        fld = pcbnew.PCB_FIELD(nf, nf.GetNextFieldOrdinal(), 'LCSC Part')
        fld.SetText(LCSC)
        fld.SetVisible(False)
        fld.SetLayer(pcbnew.F_Fab)
        nf.Add(fld)
        for pad in nf.Pads():
            inv = [o for o, nw in PAD_MAP.items() if nw == pad.GetNumber()][0]
            net = it['nets'].get(inv)
            pad.SetNet(b.FindNet(net) if net else b.FindNet(''))
        r = nf.Reference()
        r.SetLayer(it['rlayer'])
        r.SetTextSize(pcbnew.VECTOR2I(it['rw'], it['rh']))
        r.SetTextThickness(it['rt'])
        r.SetMirrored(it['rmirror'])
        r.SetTextAngleDegrees(it['rang'])
        r.SetPosition(pcbnew.VECTOR2I(it['rx'], it['ry']))
        r.SetVisible(it['rvis'])
        nf.Value().SetVisible(False)
        b.Add(nf)
        n += 1
    renamed = rename_nets(b, d)
    if b.Zones():
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    if keep is not None:
        open(pro, 'w', encoding='utf-8').write(keep)
    print(f'PCB：{n} 個の足型を {NEW_FP} に入れ替えた（位置はそのまま、向き +180°、パッドのネットは番号を移して引き継ぎ、自動ネット名 {renamed} 個を回路図に合わせた）')


def prepare_footprint(d, pads='goldberg'):
    """LCSC の足型を、このフォルダの lcsc.pretty に置く（attr だけ直す）。"""
    src = os.path.join(HERE, '..', 'core-XIAO-04', 'lib', 'lcsc.pretty',
                       'LED-SMD_4P-L2.2-W2.0-P1.00_WS2815C-2020-4P.kicad_mod')
    dst = os.path.join(d, 'lcsc.pretty', f'{NEW_NAME}.kicad_mod')
    if os.path.exists(dst):
        return
    s = open(src, encoding='utf-8').read()
    s = s.replace('(footprint "LED-SMD_4P-L2.2-W2.0-P1.00_WS2815C-2020-4P"', f'(footprint "{NEW_NAME}"', 1)
    s = s.replace('(attr through_hole)', '(attr smd)', 1)
    s = re.sub(r'(\(property "Value" )"[^"]*"', rf'\1"{NEW_NAME}"', s, count=1)
    s = re.sub(r'(\(property "Datasheet" )"[^"]*"', rf'\1"{DATASHEET}"', s, count=1)
    if pads == 'goldberg':
        for num, (at, size) in GOLDBERG_PADS.items():
            s = re.sub(rf'(\(pad "{num}" smd rect\s*\(at )[-\d. ]+(\)\s*\(size )[\d. ]+(\))', rf'\g<1>{at}\g<2>{size}\g<3>', s, count=1)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, 'w', encoding='utf-8').write(s)


if __name__ == '__main__':
    mode = sys.argv[1]
    d = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else HERE
    locks = [f for f in os.listdir(d) if f.endswith('.lck') and (mode in f or 'kicad_pro' in f)]
    if [f for f in locks if mode in f]:
        raise SystemExit(f'KiCad で開いている（{locks}）。閉じてから実行する')
    if mode == 'sch':
        sch(d)
    elif mode == 'pcb':
        prepare_footprint(d, sys.argv[sys.argv.index('--pads') + 1] if '--pads' in sys.argv else 'goldberg')
        tables(d)
        pcb(d)
