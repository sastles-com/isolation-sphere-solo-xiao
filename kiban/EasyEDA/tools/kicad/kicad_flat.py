#!/usr/bin/env python3
"""基板A の回路図を、基板B（手で統合した KiCad 版）と同じ書き方の 1 枚の回路図にする。

  python3 tools/kicad/kicad_flat.py boardA

元データ：kicad/boardA/dump_*.json（EasyEDA の部品・枠・文字）と outputs/schematic/boardA_nets.txt（ネット）。
出力　　：kicad/boardA/boardA.kicad_sch（階層なし 1 枚）、kicad/boardA/refmap.json（旧部品名 → 新部品名）。

書き方のルール（基板B に合わせたもの）：
- 階層なしの 1 枚。機能ごとに点線の枠と日本語の見出し（1.8 mm）、補足は 1.26 mm の文字
- 接続はすべて「ピンから 2.54 mm の短い線 + グローバルラベル（input）」。長い配線は引かない
- GND は部品ごとに GND 記号。未接続のピンは × 印
- 抵抗・コンデンサ・インダクタは KiCad 標準の記号（R_Small_US / C_Small / L_Small）を縦に置く。
  IC とコネクタは LCSC / 標準の記号
- 部品番号は C1、R1、… の通し番号（旧名は EasyEDA プロパティと refmap.json に残す）。
  フットプリントと LCSC Part は、lcsc.kicad_sym の LCSC 品番から入れる
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eda2kicad_core import det_uuid, esc, fnum  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
STOCK = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols'
PROJECT = 'power-2s-xiao'
STUB = 2.54


# ------------------------------------------------------------------ 記号ライブラリ
def top_blocks(text):
    out, depth, start, i, n = [], 0, None, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == '(':
            depth += 1
            if depth == 2:
                start = i
        elif c == ')':
            if depth == 2 and start is not None:
                out.append(text[start:i + 1])
                start = None
            depth -= 1
        i += 1
    return out


def stock_symbol(lib, name):
    text = open(os.path.join(STOCK, lib + '.kicad_sym'), encoding='utf-8').read()
    for b in top_blocks(text):
        if re.match(r'\(symbol\s+"%s"' % re.escape(name), b):
            return re.sub(r'^\(symbol\s+"[^"]+"', f'(symbol "{lib}:{name}"', b, count=1)
    raise KeyError(f'{lib}:{name}')


def pins_of(block):
    """{番号: (x, y, 角度)}（シンボル内の座標、y 上向き。角度はピンが本体へ向かう向き）"""
    out = {}
    for m in re.finditer(r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)', block):
        num = re.search(r'\(number\s+"([^"]+)"', block[m.end():m.end() + 800])
        if num:
            out[num.group(1)] = (float(m.group(1)), float(m.group(2)), int(m.group(3)))
    return out


def load_lcsc():
    text = open(os.path.join(ROOT, 'kicad', 'lib', 'lcsc.kicad_sym'), encoding='utf-8').read()
    lib = {}
    for b in top_blocks(text):
        m = re.match(r'\(symbol\s+"([^"]+)"', b)
        lc = re.search(r'\(property\s+"LCSC Part"\s+"(C\d+)"', b)
        fp = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', b)
        if m and lc:
            lib[lc.group(1)] = {'id': f'lcsc:{m.group(1)}',
                                'block': re.sub(r'^\(symbol\s+"[^"]+"', f'(symbol "lcsc:{m.group(1)}"', b, count=1),
                                'fp': fp.group(1) if fp else ''}
    return lib


# ------------------------------------------------------------------ 幾何
def rot(x, y, deg):
    c, s = round(math.cos(math.radians(deg))), round(math.sin(math.radians(deg)))
    return x * c - y * s, x * s + y * c


def label_len(net):
    return len(net) * 1.15 + 3.5


class Part:
    def __init__(self, old, value, lcsc, kind, lib_id, block, fp, nets):
        self.old, self.value, self.lcsc, self.kind = old, value, lcsc, kind
        self.lib_id, self.block, self.fp = lib_id, block, fp
        self.pins = pins_of(block)
        self.nets = nets                       # {ピン番号: ネット名 or None}
        self.new = None
        self.angle = 0
        self.x = self.y = 0.0

    def pin_point(self, num):
        lx, ly, _ = self.pins[num]
        X, Y = rot(lx, ly, self.angle)
        return self.x + X, self.y - Y

    def out_dir(self, num):
        return (self.pins[num][2] + 180 + self.angle) % 360


# ------------------------------------------------------------------ 出力部品
class Out:
    def __init__(self):
        self.lines = []
        self.pwr = 0

    def add(self, s):
        self.lines.append(s)

    def wire(self, a, b, tag):
        self.add(f'\t(wire\n\t\t(pts\n\t\t\t(xy {fnum(a[0])} {fnum(a[1])}) (xy {fnum(b[0])} {fnum(b[1])})\n\t\t)'
                 f'\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "{det_uuid("wire", tag, a, b)}")\n\t)')

    def glabel(self, net, p, ang, tag):
        just = 'left' if ang in (0, 90) else 'right'
        self.add(f'\t(global_label "{esc(net)}"\n\t\t(shape input)\n\t\t(at {fnum(p[0])} {fnum(p[1])} {ang})'
                 '\n\t\t(fields_autoplaced yes)'
                 f'\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {just})\n\t\t)'
                 f'\n\t\t(uuid "{det_uuid("gl", tag, net, p)}")\n\t)')

    def noconn(self, p, tag):
        self.add(f'\t(no_connect\n\t\t(at {fnum(p[0])} {fnum(p[1])})\n\t\t(uuid "{det_uuid("nc", tag, p)}")\n\t)')

    def text(self, s, x, y, size, bold=False, tag=''):
        b = '\n\t\t\t\t(bold yes)' if bold else ''
        self.add(f'\t(text "{esc(s)}"\n\t\t(exclude_from_sim no)\n\t\t(at {fnum(x)} {fnum(y)} 0)'
                 f'\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {size} {size}){b}\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)'
                 f'\n\t\t(uuid "{det_uuid("tx", tag, s, x, y)}")\n\t)')

    def rect(self, x0, y0, x1, y1, tag):
        self.add(f'\t(rectangle\n\t\t(start {fnum(x0)} {fnum(y0)})\n\t\t(end {fnum(x1)} {fnum(y1)})'
                 '\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type dash)\n\t\t)\n\t\t(fill\n\t\t\t(type none)\n\t\t)'
                 f'\n\t\t(uuid "{det_uuid("rc", tag)}")\n\t)')

    def gnd(self, p, ang, tag):
        self.pwr += 1
        ref = f'#PWR{self.pwr:02d}'
        self.add(f'\t(symbol\n\t\t(lib_id "power:GND")\n\t\t(at {fnum(p[0])} {fnum(p[1])} {ang})'
                 '\n\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom no)\n\t\t(on_board no)\n\t\t(in_pos_files no)\n\t\t(dnp no)'
                 f'\n\t\t(uuid "{det_uuid("gnd", tag, p)}")'
                 f'\n\t\t(property "Reference" "{ref}"\n\t\t\t(at {fnum(p[0])} {fnum(p[1] - 3)} 0)\n\t\t\t(hide yes)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)'
                 '\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)'
                 f'\n\t\t(property "Value" "GND"\n\t\t\t(at {fnum(p[0] + 1.5)} {fnum(p[1] + 2.5)} 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)'
                 '\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)\n\t\t)'
                 f'\n\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{ROOT_UUID}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')

    def part(self, p, ref_at, val_at):
        props = [('Footprint', p.fp, True, (p.x, p.y)), ('Datasheet', '', True, (p.x, p.y)),
                 ('LCSC Part', p.lcsc or '', True, (p.x, p.y)), ('EasyEDA', p.old, True, (p.x, p.y))]
        o = [f'\t(symbol\n\t\t(lib_id "{p.lib_id}")\n\t\t(at {fnum(p.x)} {fnum(p.y)} {p.angle})'
             '\n\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n\t\t(dnp no)'
             f'\n\t\t(uuid "{det_uuid("part", p.old)}")']
        for name, v, at in (('Reference', p.new, ref_at), ('Value', p.value, val_at)):
            o.append(f'\t\t(property "{name}" "{esc(v)}"\n\t\t\t(at {fnum(at[0])} {fnum(at[1])} 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)'
                     '\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)\n\t\t\t)\n\t\t)')
        for name, v, hide, at in props:
            o.append(f'\t\t(property "{name}" "{esc(v)}"\n\t\t\t(at {fnum(at[0])} {fnum(at[1])} 0)\n\t\t\t(hide yes)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)'
                     '\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)')
        o.append(f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{ROOT_UUID}"\n\t\t\t\t\t(reference "{esc(p.new)}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
        self.add('\n'.join(o))

    def connect(self, p, num, tag):
        """ピンに短い線とラベル（GND なら GND 記号、未接続なら × 印）を付ける。"""
        net = p.nets.get(num)
        pt = p.pin_point(num)
        if not net:
            self.noconn(pt, tag)
            return
        d = p.out_dir(num)
        end = (pt[0] + STUB * round(math.cos(math.radians(d))), pt[1] - STUB * round(math.sin(math.radians(d))))
        self.wire(pt, end, tag)
        if net == 'GND':
            self.gnd(end, (d - 270) % 360, tag)
        else:
            self.glabel(net, end, d, tag)


ROOT_UUID = det_uuid('root', 'boardA')


# ------------------------------------------------------------------ 読み込み
def read_nets():
    pin_net = {}
    for line in open(os.path.join(ROOT, 'outputs', 'schematic', 'boardA_nets.txt'), encoding='utf-8'):
        if ':' not in line:
            continue
        net, rest = line.split(':', 1)
        for m in re.finditer(r'([A-Za-z_0-9]+)\.([A-Za-z0-9]+)\(', rest):
            pin_net[(m.group(1), m.group(2))] = None if net.strip() == '(未接続)' else net.strip()
    return pin_net


def load_parts(dumps, pin_net, lcsc_lib):
    parts = []
    stock = {k: stock_symbol(*k.split(':')) for k in ('Device:C_Small', 'Device:R_Small_US', 'Device:L_Small',
                                                      'Connector_Generic:Conn_01x06')}
    for d in dumps:
        for q in d['parts']:
            des = q['des']
            nets = {p['num']: pin_net.get((des, p['num'])) for p in q['pins']}
            lc = lcsc_lib.get(q.get('lcsc') or '', {})
            fp = lc.get('fp', '')
            if des[0] in 'CRL' and len(q['pins']) == 2:
                lid = {'C': 'Device:C_Small', 'R': 'Device:R_Small_US', 'L': 'Device:L_Small'}[des[0]]
                part = Part(des, q.get('value') or '', q.get('lcsc'), 'passive', lid, stock[lid], fp, nets)
            elif des[0] == 'J':
                n = len(q['pins'])
                if n != 6:
                    raise SystemExit(f'{des}: {n} ピンのコネクタは未対応')
                lid = 'Connector_Generic:Conn_01x06'
                part = Part(des, q.get('value') or '', q.get('lcsc'), 'conn', lid, stock[lid], fp, nets)
            else:
                if not lc:
                    raise SystemExit(f'{des}: LCSC 記号がない（{q.get("lcsc")}）。lcsc_lib.py で取得する')
                part = Part(des, q.get('value') or '', q.get('lcsc'), 'ic', lc['id'], lc['block'], fp, nets)
            part.x0, part.y0, part.page = q['x'], q['y'], d['_page']
            if set(part.pins) != set(nets):
                raise SystemExit(f'{des}: ピン番号が記号と合わない {sorted(set(part.pins) ^ set(nets))}')
            parts.append(part)
    return parts


# ------------------------------------------------------------------ 枠ごとの配置
def frame_layout(frame, parts, notes, out, ox, oy, tag):
    """枠の中身を (ox, oy) を左上として描く。枠の幅と高さを返す。"""
    m = 5.0
    ics = sorted([p for p in parts if p.kind in ('ic', 'conn')], key=lambda p: (-p.y0, p.x0))
    pas = [p for p in parts if p.kind == 'passive']
    for p in pas:
        sig = [n for n in (p.nets.get('1'), p.nets.get('2')) if n and n != 'GND']
        p.sig = sig[0] if sig else ''
    pas.sort(key=lambda p: (p.sig, p.old))

    y = oy + 9 + 3.2 * len(notes) + 5
    x_right = ox + m
    # --- IC / コネクタ（縦に積む）
    if ics:
        lw = rw = 0.0
        for p in ics:
            for n in p.pins:
                net = p.nets.get(n)
                if not net or net == 'GND':
                    continue
                side = p.out_dir(n)
                if side == 180:
                    lw = max(lw, label_len(net))
                elif side == 0:
                    rw = max(rw, label_len(net))
        col_w = 0.0
        for p in ics:
            xs = [v[0] for v in p.pins.values()]
            ys = [v[1] for v in p.pins.values()]
            up = max([label_len(p.nets[n]) for n in p.pins if p.nets.get(n) and p.nets[n] != 'GND'
                      and p.out_dir(n) == 90] or [0]) + STUB
            down = max([label_len(p.nets[n]) for n in p.pins if p.nets.get(n) and p.nets[n] != 'GND'
                        and p.out_dir(n) == 270] or [0]) + STUB
            top = y + up + 4
            p.x = ox + m + lw + STUB - min(xs)
            p.y = top + max(ys)
            out.part(p, (p.x + min(xs), top - 7.0), (p.x + min(xs), top - 4.5))
            for n in p.pins:
                out.connect(p, n, tag)
            col_w = max(col_w, (max(xs) - min(xs)) + lw + rw + 2 * STUB)
            y = top + (max(ys) - min(ys)) + down + 6
        x_right = ox + m + col_w + 8
    ics_bottom = y
    # --- 受動部品（縦に並べ、1 行 6 個）
    pitch, per_row = 14.5, 5
    py = oy + 9 + 3.2 * len(notes) + 5
    right = x_right
    for r0 in range(0, len(pas), per_row):
        row = pas[r0:r0 + per_row]
        # 上側ラベルの長さ（GND でない側。両方が信号ならどちらも）
        for p in row:
            p.angle = 180 if p.nets.get('1') == 'GND' else 0
        top_l = max([label_len(p.nets[('1' if p.angle == 0 else '2')]) for p in row
                     if p.nets.get('1' if p.angle == 0 else '2') not in (None, 'GND')] or [0])
        bot_l = max([label_len(p.nets[('2' if p.angle == 0 else '1')]) for p in row
                     if p.nets.get('2' if p.angle == 0 else '1') not in (None, 'GND')] or [3.0])
        cy = py + top_l + STUB + 2.54
        for i, p in enumerate(row):
            p.x = x_right + 6 + i * pitch
            p.y = cy
            out.part(p, (p.x + 2.2, p.y - 1.3), (p.x + 2.2, p.y + 1.3))
            for n in p.pins:
                out.connect(p, n, tag)
            right = max(right, p.x + pitch - 4)
        py = cy + 2.54 + STUB + bot_l + 7
    bottom = max(ics_bottom, py) if (ics or pas) else oy + 20
    # --- 見出しと補足
    def tw(t, size):
        return sum((2.0 if ord(c) > 255 else 1.0) * size * 0.95 for c in t)
    w = max(right - ox + m, tw(frame.get('title', ''), 1.8) + 2 * m,
            max([tw(t, 1.26) for t in notes] or [0]) + 2 * m, 40)
    h = bottom - oy
    out.rect(ox, oy, ox + w, oy + h, tag)
    if frame.get('title'):
        out.text(frame['title'], ox + m, oy + 6, 1.8, bold=False, tag=tag)
    for i, t in enumerate(notes):
        out.text(t, ox + m, oy + 10.5 + 3.2 * i, 1.26, tag=tag)
    return w, h


def find_frames(dumps, net_names):
    frames = []
    for d in dumps:
        for r in d['rects']:
            f = {'page': d['_page'], 'x0': r['x'], 'x1': r['x'] + r['w'], 'y1': r['topY'], 'y0': r['topY'] - r['h'],
                 'title': '', 'notes': []}
            texts = [t for t in d['texts'] if f['x0'] <= t['x'] <= f['x1'] and f['y0'] <= t['y'] <= f['y1']]
            titled = [t for t in texts if t.get('bold')]
            if titled:
                f['title'] = ' '.join(re.sub(r'\s+', ' ', t['content']).strip() for t in sorted(titled, key=lambda t: -t['y']))
            for t in sorted((t for t in texts if not t.get('bold')), key=lambda t: (-t['y'], t['x'])):
                c = (t['content'] or '').strip()
                if c and c not in net_names and c != 'NC':
                    f['notes'].append(c)
            frames.append(f)
    frames.sort(key=lambda f: (('POWER', 'LED_IO').index(f['page']), -f['y1'], f['x0']))
    return frames


# ------------------------------------------------------------------ 組み立て
def build():
    dumps = []
    for page in ('POWER', 'LED_IO'):
        d = json.load(open(os.path.join(ROOT, 'kicad', 'boardA', f'dump_{page}.json'), encoding='utf-8'))
        d['_page'] = page
        dumps.append(d)
    pin_net = read_nets()
    lcsc_lib = load_lcsc()
    parts = load_parts(dumps, pin_net, lcsc_lib)
    net_names = {n for n in pin_net.values() if n}
    frames = find_frames(dumps, net_names)
    for p in parts:
        for f in frames:
            if f['page'] == p.page and f['x0'] <= p.x0 <= f['x1'] and f['y0'] <= p.y0 <= f['y1']:
                f.setdefault('parts', []).append(p)
                break
        else:
            raise SystemExit(f'{p.old}: どの枠にも入らない')

    # 部品番号は、配置の順（枠の順 → IC → 受動部品の並び）で通し番号にする
    counters, refmap = {}, {}
    order = []
    for f in frames:
        ps = f.get('parts', [])
        ics = sorted([p for p in ps if p.kind in ('ic', 'conn')], key=lambda p: (-p.y0, p.x0))
        pas = sorted([p for p in ps if p.kind == 'passive'], key=lambda p: p.old)
        order += ics
    for p in order:
        pass

    out = Out()
    sizes = []
    for pages in (('A3', 420, 297), ('A2', 594, 420)):
        out = Out()
        paper, W, H = pages
        x = y = 12.0
        row_h = 0.0
        sizes = []
        ok = True
        for i, f in enumerate(frames):
            sub = Out()
            # 仮配置で大きさを測る
            w, h = frame_layout(f, f.get('parts', []), f['notes'], sub, 0, 0, f'm{i}')
            if x + w > W - 12 and x > 12:
                x, y, row_h = 12.0, y + row_h + 5, 0.0
            sizes.append((f, x, y, w, h))
            x += w + 5
            row_h = max(row_h, h)
        if y + row_h > H - 10:
            continue
        break
    # 部品番号を振る（ここで確定。配置の座標はあとで描き直す）
    for f, *_ in sizes:
        ps = f.get('parts', [])
        ics = sorted([p for p in ps if p.kind in ('ic', 'conn')], key=lambda p: (-p.y0, p.x0))
        pas = [p for p in ps if p.kind == 'passive']
        for p in pas:
            sig = [n for n in (p.nets.get('1'), p.nets.get('2')) if n and n != 'GND']
            p.sig = sig[0] if sig else ''
        pas.sort(key=lambda p: (p.sig, p.old))
        for p in ics + pas:
            pref = 'U' if p.kind == 'ic' else p.old[0]
            counters[pref] = counters.get(pref, 0) + 1
            p.new = f'{pref}{counters[pref]}'
            refmap[p.old] = p.new
    def rename(t):
        return re.sub(r'(?<![A-Za-z0-9_])(%s)(?![A-Za-z0-9_])' % '|'.join(sorted(map(re.escape, refmap), key=len, reverse=True)),
                      lambda m: refmap[m.group(1)], t)
    out = Out()
    for i, (f, x, y, w, h) in enumerate(sizes):
        f2 = dict(f, title=rename(f['title']))
        frame_layout(f2, f.get('parts', []), [rename(n) for n in f['notes']], out, x, y, f'f{i}')

    syms = {}
    for p in parts:
        syms[p.lib_id] = p.block
    syms['power:GND'] = stock_symbol('power', 'GND')
    a = ['(kicad_sch', '\t(version 20260306)\n\t(generator "kicad_flat.py")\n\t(generator_version "10.0")',
         f'\t(uuid "{ROOT_UUID}")', f'\t(paper "{paper}")', '\t(lib_symbols']
    a += [syms[k] for k in sorted(syms)]
    a.append('\t)')
    a += out.lines
    a.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)')
    a.append(')')
    return '\n'.join(a) + '\n', refmap, paper


def kicad_nets(sch):
    xml = '/tmp/boardA_flat.xml'
    r = subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, sch],
                       capture_output=True, text=True)
    import xml.etree.ElementTree as ET
    t = ET.parse(xml).getroot()
    return {n.get('name').lstrip('/'): sorted(f"{x.get('ref')}.{x.get('pin')}" for x in n.iter('node'))
            for n in t.iter('net')}


def verify(sch, refmap):
    new2old = {v: k for k, v in refmap.items()}
    got = {frozenset(f"{new2old.get(p.split('.')[0], p.split('.')[0])}.{p.split('.')[1]}" for p in pins)
           for name, pins in kicad_nets(sch).items() if not name.startswith('unconnected-') and len(pins) >= 2}
    want = {}
    for line in open(os.path.join(ROOT, 'outputs', 'schematic', 'boardA_nets.txt'), encoding='utf-8'):
        net, rest = line.split(':', 1)
        if net.strip() == '(未接続)':
            continue
        pins = frozenset(f'{m.group(1)}.{m.group(2)}' for m in re.finditer(r'([A-Za-z_0-9]+)\.([A-Za-z0-9]+)\(', rest))
        if len(pins) >= 2:
            want[net.strip()] = pins
    want_s = set(want.values())
    return want_s - got, got - want_s, len(want_s), len(got)


if __name__ == '__main__':
    text, refmap, paper = build()
    sch = os.path.join(ROOT, 'kicad', 'boardA', 'boardA.kicad_sch')
    open(sch, 'w', encoding='utf-8').write(text)
    json.dump(refmap, open(os.path.join(ROOT, 'kicad', 'boardA', 'refmap.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    pro = {'meta': {'filename': 'boardA.kicad_pro', 'version': 3}, 'sheets': [[ROOT_UUID, 'Root']]}
    json.dump(pro, open(os.path.join(ROOT, 'kicad', 'boardA', 'boardA.kicad_pro'), 'w'), indent=2)
    miss, extra, nw, ng = verify(sch, refmap)
    print(f'用紙 {paper}、部品 {len(refmap)}、ネット EasyEDA {nw} / KiCad {ng}')
    for g in sorted(miss, key=sorted):
        print('  ⚠️ EasyEDA のみ:', sorted(g))
    for g in sorted(extra, key=sorted):
        print('  ⚠️ KiCad のみ  :', sorted(g))
    print('✅ ネットリスト一致' if not miss and not extra else f'❌ 不一致 {len(miss) + len(extra)} 件')
