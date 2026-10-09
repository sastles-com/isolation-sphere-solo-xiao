#!/usr/bin/env python3
"""PCB のフットプリントを、回路図のシンボルに結び付け直す（path を書き込む）。

  python3 tools/kicad/relink.py boardA boardB

KiCad の「回路図から基板を更新」は、フットプリントの path（シンボルの UUID）で対応を取る。
スクリプトで作った・入れ替えたフットプリントには path がないので、更新すると「対応なし」として消され、
新しく置き直される（配置が消える）。部品番号で対応を取り、path を書き込んでおけば、配置を保ったまま更新できる。
KiCad で PCB を開いていないときに実行する。
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def symbol_uuids(sch_text):
    out = {}
    for m in re.finditer(r'\n\t\(symbol\n\t\t\(lib_id "[^"]+"\)', sch_text):
        blk = sch_text[m.end():m.end() + 6000]
        u = re.search(r'\n\t\t\(uuid "([^"]+)"\)', blk)
        r = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if u and r and not r.group(1).startswith('#'):
            out[r.group(1)] = u.group(1)
    return out


def relink(board):
    d = os.path.join(ROOT, 'kicad', board)
    sch = open(os.path.join(d, f'{board}.kicad_sch'), encoding='utf-8').read()
    pcb_path = os.path.join(d, f'{board}.kicad_pcb')
    pcb = open(pcb_path, encoding='utf-8').read()
    uu = symbol_uuids(sch)
    parts = re.split(r'\n(?=\t\(footprint )', pcb)
    done, nosym = [], []
    for i, b in enumerate(parts[1:], 1):
        ref = re.search(r'\(property "Reference" "([^"]+)"', b)
        if not ref or '\n\t\t(path "/' in b:
            continue
        ref = ref.group(1)
        if ref not in uu:
            nosym.append(ref)
            continue
        k = min(x for x in (b.find('\n\t\t(units'), b.find('\n\t\t(attr')) if x > 0)
        add = f'\n\t\t(path "/{uu[ref]}")\n\t\t(sheetname "/")\n\t\t(sheetfile "{board}.kicad_sch")'
        parts[i] = b[:k] + add + b[k:]
        done.append(ref)
    open(pcb_path, 'w', encoding='utf-8').write('\n'.join(parts))
    print(f'{board}: 結び付けた {len(done)} 個 {done if len(done) < 10 else ""}、回路図にない {nosym}')


if __name__ == '__main__':
    for b in sys.argv[1:]:
        relink(b)
