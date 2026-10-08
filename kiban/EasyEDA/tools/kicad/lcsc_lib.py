#!/usr/bin/env python3
"""回路図に出てくる LCSC 部品のシンボル・フットプリント・3D モデルを easyeda2kicad で取得し、
KiCad のプロジェクト（kicad/boardA、kicad/boardB）から使えるように整える。

  python3 tools/kicad/lcsc_lib.py          # 取得していない部品だけ取得して整える
  python3 tools/kicad/lcsc_lib.py --fix    # 取得はせず、整える処理だけ

前提：easyeda2kicad（pipx install --backend pip easyeda2kicad）。
出力：kicad/lib/lcsc.kicad_sym、lcsc.pretty/、lcsc.3dshapes/（3D は Git に入れない）。

注意（2026-10-08 実測）：
- 続けて 30 部品ほど取得すると、EasyEDA の API が 403 を返すようになる（一時的なブロック）。
  そのため 1 部品ごとに間隔を空け、取得済みの部品は飛ばす。403 が出たら時間を置いて再実行する
- --project-relative と相対パスの出力先を一緒に使うとエラーになるので、出力先は絶対パスで渡す
- 3D モデルのパスは ${KIPRJMOD}/kicad/lib/... で書かれる。KiCad のプロジェクトは kicad/boardX/ に
  あるので ${KIPRJMOD}/../lib/... に書き換える
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
LIB = os.path.join(ROOT, 'kicad', 'lib')
E2K = os.path.expanduser('~/.local/bin/easyeda2kicad')
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
SYM = os.path.join(LIB, 'lcsc.kicad_sym')
PRETTY = os.path.join(LIB, 'lcsc.pretty')


def wanted_ids():
    ids = set()
    for f in glob.glob(os.path.join(ROOT, 'kicad', 'board*', 'dump_*.json')):
        for p in json.load(open(f, encoding='utf-8'))['parts']:
            if p.get('lcsc'):
                ids.add(p['lcsc'])
    return sorted(ids)


def have_ids():
    if not os.path.exists(SYM):
        return set()
    return set(re.findall(r'"LCSC Part"\s*"(C\d+)"', open(SYM, encoding='utf-8').read()))


def fetch(ids, wait=6):
    os.makedirs(LIB, exist_ok=True)
    out = os.path.join(LIB, 'lcsc')
    failed = []
    for i in ids:
        r = subprocess.run([E2K, '--full', '--overwrite', '--lcsc_id', i, '--output', out, '--project-relative'],
                           capture_output=True, text=True)
        log = r.stdout + r.stderr
        if 'Created Kicad symbol' not in log or 'Created Kicad footprint' not in log:
            failed.append(i)
        time.sleep(wait)
    return failed


def fix():
    # 3D モデルのパスを、kicad/boardX/ のプロジェクトから見た相対パスへ
    n = 0
    for f in glob.glob(os.path.join(PRETTY, '*.kicad_mod')):
        s = open(f, encoding='utf-8').read()
        t = s.replace('${KIPRJMOD}/kicad/lib/', '${KIPRJMOD}/../lib/')
        if t != s:
            open(f, 'w', encoding='utf-8').write(t)
            n += 1
    # KiCad 10 の形式へ更新
    for cmd in (['sym', 'upgrade', '--force', SYM], ['fp', 'upgrade', '--force', PRETTY]):
        r = subprocess.run([KICAD_CLI] + cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print('⚠️', ' '.join(cmd[:2]), r.stderr.strip()[:200])
    # 各プロジェクトにライブラリを登録
    for board in ('boardA', 'boardB'):
        d = os.path.join(ROOT, 'kicad', board)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'sym-lib-table'), 'w').write(
            '(sym_lib_table\n\t(version 7)\n\t(lib (name "lcsc")(type "KiCad")(uri "${KIPRJMOD}/../lib/lcsc.kicad_sym")'
            '(options "")(descr "LCSC parts via easyeda2kicad"))\n)\n')
        open(os.path.join(d, 'fp-lib-table'), 'w').write(
            '(fp_lib_table\n\t(version 7)\n\t(lib (name "lcsc")(type "KiCad")(uri "${KIPRJMOD}/../lib/lcsc.pretty")'
            '(options "")(descr "LCSC parts via easyeda2kicad"))\n)\n')
    print(f'3D パスを直したフットプリント {n} 個、ライブラリを形式更新、boardA / boardB に登録')


if __name__ == '__main__':
    if '--fix' not in sys.argv:
        todo = [i for i in wanted_ids() if i not in have_ids()]
        print(f'必要 {len(wanted_ids())} 種類、取得済み {len(have_ids())}、これから取得 {len(todo)}')
        failed = fetch(todo) if todo else []
        if failed:
            print(f'⚠️ 取得できなかった {len(failed)} 種類：{" ".join(failed)}（403 なら時間を置いて再実行）')
    fix()
    missing = [i for i in wanted_ids() if i not in have_ids()]
    print(f'取得済み {len(wanted_ids()) - len(missing)} / {len(wanted_ids())}' + (f'、未取得 {missing}' if missing else ''))
