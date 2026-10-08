#!/usr/bin/env python3
"""EasyEDA の基板A / 基板B の回路図を、KiCad 10 の階層回路図に変換して検証する。

正本は EasyEDA。ここで作る KiCad 版はレビュー・版管理用のスナップショット（手で編集しない）。

  python3 tools/kicad/kicad_export.py            # 両方の基板
  python3 tools/kicad/kicad_export.py boardB     # 片方だけ

出力（kiban/EasyEDA/kicad/<board>/）：
  <board>.kicad_pro / <board>.kicad_sch（親シート）/ <board>_<PAGE>.kicad_sch（ページごと）
  dump_<PAGE>.json（EasyEDA から取り出した生データ）

変換の要点：
- EasyEDA の回路図は「ネット名を付けた線」で接続している（同じ名前の線はつながる）。
  KiCad は名前をラベルからしか取らないので、**つながった線の島ごとに 1 個ずつラベルを置く**
- 2 ページ以上に出てくるネットはグローバルラベル、1 ページだけのネットはローカルラベル
- ネット名を表すための文字（EasyEDA 側の text）は、ラベルと重複するので KiCad には移さない
- 検証は kicad-cli でネットリストを書き出し、EasyEDA のネットリストとピン集合で比べる
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import eda_bridge as e  # noqa: E402
from eda2kicad_core import (GND_SYMBOL, Transform, build_symbol, det_uuid, esc, fnum,  # noqa: E402
                            junctions, on_seg, segments, sym_name)

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(ROOT, 'kicad')
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
PROJECT = 'power-2s-xiao'

BOARDS = {
    'boardA': [('POWER', 'e671a2341d4b3a66'), ('LED_IO', 'a9ace616ca30334c')],
    'boardB': [('CHARGER', '94446b1a98d03840'), ('PROTECTION', '3c04743d7cb514cc')],
}

DUMP_JS = open(os.path.join(HERE, 'eda_dump.js'), encoding='utf-8').read()


# ------------------------------------------------------------------ EasyEDA から取り出す
def dump_page(page: str) -> dict:
    code = ("await eda.dmt_EditorControl.openDocument(%s);\n"
            "const _d = await eda.dmt_SelectControl.getCurrentDocumentInfo();\n"
            "if (!_d || _d.uuid !== %s) return {error: 'page switched'};\n"
            "await eda.sch_Document.save();\n") % (json.dumps(page), json.dumps(page))
    r = e.run(code + DUMP_JS)
    if 'error' in r:
        raise RuntimeError(r['error'])
    return r


# ------------------------------------------------------------------ 線の島とラベル
class UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def islands(segs):
    """つながった線分の集まり（島）。端点の一致と、端点が他の線分上に乗る T 字を接続とみなす。"""
    uf = UF()
    for _, a, b in segs:
        uf.union(a, b)
    pts = {p for _, a, b in segs for p in (a, b)}
    for p in pts:
        for _, a, b in segs:
            if p not in (a, b) and on_seg(p, a, b):
                uf.union(p, a)
    groups = {}
    for i, (net, a, b) in enumerate(segs):
        groups.setdefault(uf.find(a), []).append(i)
    return list(groups.values())


def label_anchor(segs, idx, pin_pts):
    """島のラベルを置く点と向き。部品ピンでない、線の行き止まりの端を優先する。"""
    deg = {}
    for i in idx:
        _, a, b = segs[i]
        for p in (a, b):
            deg[p] = deg.get(p, 0) + 1
    cands = [p for p, d in deg.items() if d == 1 and p not in pin_pts] or \
            [p for p, d in deg.items() if d == 1] or list(deg)
    p = sorted(cands)[0]
    # 向き：線の反対側の端から離れる向きに文字を出す
    for i in idx:
        _, a, b = segs[i]
        if p in (a, b):
            q = b if p == a else a
            if q[0] > p[0]:
                return p, 180
            if q[0] < p[0]:
                return p, 0
            return p, (270 if q[1] > p[1] else 90)
    return p, 0


# ------------------------------------------------------------------ 子シート
def instance(lib_id, ref, val, x, y, uid, props, path, in_bom=True):
    o = ['\t(symbol', f'\t\t(lib_id "{lib_id}")', f'\t\t(at {fnum(x)} {fnum(y)} 0)',
         '\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)',
         f'\t\t(in_bom {"yes" if in_bom else "no"})\n\t\t(on_board yes)\n\t\t(in_pos_files {"yes" if in_bom else "no"})\n\t\t(dnp no)',
         f'\t\t(uuid "{uid}")']
    dy = 0.0
    for name, v, hide in [("Reference", ref, False), ("Value", val, False)] + props:
        o.append(f'\t\t(property "{name}" "{esc(v)}"')
        o.append(f'\t\t\t(at {fnum(x)} {fnum(y - 6.0 - dy)} 0)')
        if hide:
            o.append('\t\t\t(hide yes)')
        o.append('\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)')
        o.append('\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)')
        o.append('\t\t)')
        dy += 0.0 if hide else 2.2
    o.append(f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "{path}"\n\t\t\t\t\t(reference "{esc(ref)}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)')
    o.append('\t)')
    return '\n'.join(o)


def child_sheet(board, page, dump, global_nets, root_uuid, sheet_uuid):
    tr = Transform(dump)
    path = f'/{root_uuid}/{sheet_uuid}'
    symbols = {}
    for p in dump['parts']:
        n = sym_name(p)
        if n not in symbols:
            pref = re.match(r'^[A-Za-z_]+', p['des'] or 'X').group(0)
            show = pref in ('U', 'Q', 'J') or len(p.get('pins') or []) > 2
            symbols[n] = build_symbol(n, p, show)[0]

    a = []
    a.append('(kicad_sch')
    a.append('\t(version 20260306)\n\t(generator "kicad_export.py")\n\t(generator_version "10.0")')
    a.append(f'\t(uuid "{det_uuid("sheetfile", board, page)}")')
    a.append(f'\t(paper "{"A3" if tr.w_mm <= 420 and tr.h_mm <= 297 else "A2"}")')
    a.append('\t(lib_symbols')
    for n in sorted(symbols):
        a.append(symbols[n])
    a.append(GND_SYMBOL)
    a.append('\t)')

    for i, r in enumerate(dump['rects']):
        a.append('\t(rectangle')
        a.append(f'\t\t(start {fnum(tr.x(r["x"]))} {fnum(tr.y(r["topY"]))})')
        a.append(f'\t\t(end {fnum(tr.x(r["x"] + r["w"]))} {fnum(tr.y(r["topY"] - r["h"]))})')
        a.append('\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type dash)\n\t\t)\n\t\t(fill\n\t\t\t(type none)\n\t\t)')
        a.append(f'\t\t(uuid "{det_uuid("rect", board, page, i)}")')
        a.append('\t)')

    segs = segments(dump)
    for i, (net, p1, p2) in enumerate(segs):
        a.append('\t(wire')
        a.append(f'\t\t(pts\n\t\t\t(xy {fnum(tr.x(p1[0]))} {fnum(tr.y(p1[1]))}) (xy {fnum(tr.x(p2[0]))} {fnum(tr.y(p2[1]))})\n\t\t)')
        a.append('\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)')
        a.append(f'\t\t(uuid "{det_uuid("wire", board, page, i, net, p1, p2)}")')
        a.append('\t)')
    for i, p in enumerate(junctions(segs)):
        a.append(f'\t(junction\n\t\t(at {fnum(tr.x(p[0]))} {fnum(tr.y(p[1]))})\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)')
        a.append(f'\t\t(uuid "{det_uuid("junc", board, page, i, p)}")\n\t)')

    pin_pts = {(q['x'], q['y']) for p in dump['parts'] for q in p.get('pins') or []}
    n_glob = n_loc = 0
    for k, idx in enumerate(islands(segs)):
        names = {segs[i][0] for i in idx if segs[i][0]}
        if not names:
            continue
        if len(names) > 1:
            print(f'  ⚠️ {board}/{page}: 1 つの島に複数のネット名 {sorted(names)}')
        net = sorted(names)[0]
        p, ang = label_anchor(segs, idx, pin_pts)
        just = {0: 'left bottom', 180: 'right bottom', 90: 'left bottom', 270: 'right bottom'}[ang]
        if net in global_nets:
            n_glob += 1
            a.append(f'\t(global_label "{esc(net)}"\n\t\t(shape passive)\n\t\t(at {fnum(tr.x(p[0]))} {fnum(tr.y(p[1]))} {ang})')
            a.append('\t\t(fields_autoplaced yes)')
            a.append(f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {"left" if ang in (0, 90) else "right"})\n\t\t)')
            a.append(f'\t\t(uuid "{det_uuid("glabel", board, page, k, net)}")\n\t)')
        else:
            n_loc += 1
            a.append(f'\t(label "{esc(net)}"\n\t\t(at {fnum(tr.x(p[0]))} {fnum(tr.y(p[1]))} {ang})')
            a.append('\t\t(fields_autoplaced yes)')
            a.append(f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {just})\n\t\t)')
            a.append(f'\t\t(uuid "{det_uuid("label", board, page, k, net)}")\n\t)')

    net_names = {s[0] for s in segs if s[0]}
    n_txt = 0
    for i, t in enumerate(dump['texts']):
        if (t.get('content') or '').strip() in net_names:
            continue          # ネット名の表示用の文字は、KiCad ではラベルが代わりになる
        n_txt += 1
        size = max(1.0, round((t.get('size') or 10) * 0.18, 3))
        bold = '\n\t\t\t\t(bold yes)' if t.get('bold') else ''
        a.append(f'\t(text "{esc(t["content"])}"\n\t\t(exclude_from_sim no)\n\t\t(at {fnum(tr.x(t["x"]))} {fnum(tr.y(t["y"]))} 0)')
        a.append(f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {fnum(size)} {fnum(size)}){bold}\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)')
        a.append(f'\t\t(uuid "{det_uuid("text", board, page, i, t["content"])}")\n\t)')

    for p in dump['parts']:
        props = [('Footprint', '', True), ('Datasheet', '', True), ('Description', p.get('mpn') or '', True),
                 ('LCSC', p.get('lcsc') or '', True), ('MPN', p.get('mpn') or '', True)]
        a.append(instance(f'gen:{sym_name(p)}', p['des'], p.get('value') or '', tr.x(p['x']), tr.y(p['y']),
                          det_uuid('part', board, p['des']), props, path))
    a.append(')')
    stats = dict(parts=len(dump['parts']), wires=len(segs), junctions=len(junctions(segs)),
                 global_labels=n_glob, labels=n_loc, texts=n_txt, rects=len(dump['rects']))
    return '\n'.join(a) + '\n', stats


def root_sheet(board, pages, root_uuid, sheet_uuids):
    a = ['(kicad_sch', '\t(version 20260306)\n\t(generator "kicad_export.py")\n\t(generator_version "10.0")',
         f'\t(uuid "{root_uuid}")', '\t(paper "A4")', '\t(lib_symbols)']
    a.append(f'\t(text "{board}（{PROJECT}）— EasyEDA から自動生成。編集は EasyEDA で行う"\n\t\t(exclude_from_sim no)\n\t\t(at 20 20 0)'
             '\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2 2)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)'
             f'\n\t\t(uuid "{det_uuid("roottext", board)}")\n\t)')
    for i, (page, _) in enumerate(pages):
        x = 25 + 130 * i
        su = sheet_uuids[page]
        a.append(f'\t(sheet\n\t\t(at {x} 40)\n\t\t(size 110 50)\n\t\t(fields_autoplaced yes)'
                 '\n\t\t(stroke\n\t\t\t(width 0.1524)\n\t\t\t(type solid)\n\t\t)\n\t\t(fill\n\t\t\t(color 0 0 0 0.0000)\n\t\t)'
                 f'\n\t\t(uuid "{su}")'
                 f'\n\t\t(property "Sheetname" "{page}"\n\t\t\t(at {x} 39.29 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left bottom)\n\t\t\t)\n\t\t)'
                 f'\n\t\t(property "Sheetfile" "{board}_{page}.kicad_sch"\n\t\t\t(at {x} 90.59 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left top)\n\t\t\t)\n\t\t)'
                 f'\n\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{root_uuid}"\n\t\t\t\t\t(page "{i + 2}")\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
    a.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)')
    a.append(')')
    return '\n'.join(a) + '\n'


# ------------------------------------------------------------------ 検証
def kicad_netlist(root_sch):
    net = root_sch.replace('.kicad_sch', '.net')
    r = subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', net, root_sch],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)
    text = open(net, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'\(net\s+\(code "?\d+"?\)\s+\(name "((?:[^"\\]|\\.)*)"\)(.*?)\)\s*(?=\(net\s|\)\s*\)\s*$)', text, re.S):
        name, body = m.group(1), m.group(2)
        pins = re.findall(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', body)
        out[name] = sorted(f'{r_}.{p}' for r_, p in pins)
    os.remove(net)
    return out


def compare(eda_nets, kic_nets):
    def groups(d, eda):
        g = set()
        for name, pins in d.items():
            ps = frozenset(re.sub(r'\(.*\)$', '', p) for p in pins) if eda else frozenset(pins)
            if (eda and name == '(未接続)') or (not eda and name.startswith('unconnected-')):
                continue
            if len(ps) >= 2 or not eda:
                g.add(ps)
        return {x for x in g if len(x) >= 2}
    ge, gk = groups(eda_nets, True), groups(kic_nets, False)
    return ge, gk, ge - gk, gk - ge


def export(board):
    pages = BOARDS[board]
    os.makedirs(os.path.join(OUT, board), exist_ok=True)
    dumps = {}
    for page, uuid_ in pages:
        d = dump_page(uuid_)
        dumps[page] = d
        json.dump(d, open(os.path.join(OUT, board, f'dump_{page}.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    # 2 ページ以上に出てくるネット → グローバルラベル
    seen = {}
    for page, d in dumps.items():
        for w in d['wires']:
            if w['net']:
                seen.setdefault(w['net'], set()).add(page)
    global_nets = {n for n, ps in seen.items() if len(ps) >= 2}

    root_uuid = det_uuid('root', board)
    sheet_uuids = {page: det_uuid('sheet', board, page) for page, _ in pages}
    print(f'== {board}：ページをまたぐネット {len(global_nets)} 個 {sorted(global_nets)}')
    for page, _ in pages:
        text, st = child_sheet(board, page, dumps[page], global_nets, root_uuid, sheet_uuids[page])
        open(os.path.join(OUT, board, f'{board}_{page}.kicad_sch'), 'w', encoding='utf-8').write(text)
        print(f'  {page}: {st}')
    root = os.path.join(OUT, board, f'{board}.kicad_sch')
    open(root, 'w', encoding='utf-8').write(root_sheet(board, pages, root_uuid, sheet_uuids))
    pro = {'meta': {'filename': f'{board}.kicad_pro', 'version': 3},
           'sheets': [[root_uuid, 'Root']] + [[sheet_uuids[p], p] for p, _ in pages]}
    json.dump(pro, open(os.path.join(OUT, board, f'{board}.kicad_pro'), 'w'), indent=2)

    eda_nets, _ = e.nets(pages[0][1])
    kic_nets = kicad_netlist(root)
    ge, gk, only_e, only_k = compare(eda_nets, kic_nets)
    print(f'  検証：EasyEDA {len(ge)} ネット / KiCad {len(gk)} ネット（2 ピン以上）')
    for g in sorted(only_e, key=sorted):
        print('   ⚠️ EasyEDA のみ:', sorted(g))
    for g in sorted(only_k, key=sorted):
        print('   ⚠️ KiCad のみ  :', sorted(g))
    ok = not only_e and not only_k
    print('  ✅ ネットリスト一致' if ok else f'  ❌ 不一致 {len(only_e) + len(only_k)} 件')
    return ok


if __name__ == '__main__':
    targets = sys.argv[1:] or list(BOARDS)
    results = {b: export(b) for b in targets}
    sys.exit(0 if all(results.values()) else 1)
