#!/usr/bin/env python3
"""面付けした PCB から、JLCPCB 向けの製造用ファイル（Gerber、ドリル、BOM、部品位置）を作る。KiCad 付属の Python で動かす。

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      kiban/panel-AB/make_production.py

KiCad の「製造用ファイル（Fabrication Toolkit）」プラグインと同じ処理（BOM、部品位置の回転補正を含む）を呼ぶ。
出力：kiban/panel-AB/production/（panel-AB.zip、bom.csv、positions.csv、designators.csv、netlist.ipc）
panel-AB.kicad_pcb を開いていないときに実行する。make_panel.py で作り直したあとは、これも実行し直す。
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.expanduser('~/Documents/KiCad/10.0/3rdparty/plugins')
PKG = 'com_github_bennymeg_JLC-Plugin-for-KiCad'

sys.path.insert(0, PLUGINS)
thread = importlib.import_module(f'{PKG}.thread')
options = importlib.import_module(f'{PKG}.options')

opts = {
    options.AUTO_TRANSLATE_OPT: True,        # 部品ごとの位置・回転の補正（transformations.csv）を適用する
    options.AUTO_FILL_OPT: True,             # ゾーンを塗り直してから出力する
    options.EXCLUDE_DNP_OPT: True,
    options.EXTEND_EDGE_CUT_OPT: False,
    options.ALTERNATIVE_EDGE_CUT_OPT: False,
    options.ALL_ACTIVE_LAYERS_OPT: False,
    options.ARCHIVE_NAME: None,              # 空なら、ファイル名（panel-AB）で zip と CSV を作る
    options.EXTRA_LAYERS: None,
    options.BACKUP_OPT: True,                # プラグインの仕様で、True のときはバックアップを作らない
}
thread.ProcessThread(wx=None, cli=os.path.join(HERE, 'panel-AB.kicad_pcb'), options=opts, openBrowser=False, nonInteractive=True)
