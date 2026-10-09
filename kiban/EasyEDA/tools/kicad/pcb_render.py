#!/usr/bin/env python3
"""pcb_boardB.py が出す *.layout.json から、配置図（上面・下面）の PNG を作る。

  python3 tools/kicad/pcb_render.py b.layout.json out_prefix
"""
import json
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle

d = json.load(open(sys.argv[1], encoding='utf-8'))
for side, name in ((False, 'top'), (True, 'bottom')):
    fig, ax = plt.subplots(figsize=(13, 11))
    ax.add_patch(Polygon(d['outline'], closed=True, fill=False, ec='k', lw=1.5))
    for p in d['parts']:
        on = p['back'] == side
        tht = any(q[6] for q in p['pads'])
        if not on and not tht:
            continue
        x0, y0, x1, y1 = p['rect']
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec='#2a6' if on else '#aaa', lw=0.8, ls='-' if on else ':'))
        for q in p['pads']:
            ax.add_patch(Rectangle((q[0], q[1]), q[2] - q[0], q[3] - q[1], fc='#c33' if on else '#999', ec='none', alpha=0.85))
        ax.text((x0 + x1) / 2, y0 - 0.2, p['ref'], fontsize=7, ha='center', va='bottom', color='#036')
    xs = [p[0] for p in d['outline']]
    ys = [p[1] for p in d['outline']]
    ax.set_xlim(min(xs) - 2, max(xs) + 2)
    ax.set_ylim(max(ys) + 2, min(ys) - 2)
    ax.set_aspect('equal')
    ax.set_title(f'{sys.argv[2].split("/")[-1]} {name} (top view, mm)')
    ax.grid(True, lw=0.2)
    fig.savefig(f'{sys.argv[2]}_{name}.png', dpi=90, bbox_inches='tight')
