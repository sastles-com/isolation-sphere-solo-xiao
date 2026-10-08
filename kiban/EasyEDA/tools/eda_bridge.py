"""EasyEDA ブリッジ（easyeda-api スキル）を呼ぶ小さな道具。標準ライブラリのみ。

- run(code)     : ブリッジの /execute にコードを送り、結果を返す
- place(specs)  : 部品を置き、ピンから短い線を出してネット名を付ける（LCSC 番号で指定）
- nets(page)    : ページが属するボードの回路図全体のネットリストを {ネット名: [部品.ピン(ピン名), ...]} で返す
- clear_page()  : 現在の回路図ページの部品と線を、シート以外すべて削除する（試験用）

spec の形式:
  {'id': 'C25804', 'ref': 'R1', 'x': 100, 'y': 300, 'val': '10k',
   'nets': {'1': 'NET_A', '2': 'GND'}}   # キーはピン番号またはピン名

使い方の例:
  python3 tools/eda_bridge.py nets
"""
import json
import subprocess
import sys

HELPER = r"""
const specs = SPECS;
const page = PAGE;
if (page) {
  await eda.dmt_EditorControl.openDocument(page);
  const doc = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  if (!doc || doc.uuid !== page) return [{ref: '*', err: 'active page is ' + (doc && doc.uuid) + ', expected ' + page}];
}
const ids = [...new Set(specs.map(s => s.id))];
const devs = await eda.lib_Device.getByLcscIds(ids);
const map = {};
for (const d of devs) map[d.supplierId] = d;
const log = [];
for (const s of specs) {
  const dev = map[s.id];
  if (!dev) { log.push({ref: s.ref, err: 'no device ' + s.id}); continue; }
  const comp = await eda.sch_PrimitiveComponent.create(dev, s.x, s.y);
  const pid = comp.getState_PrimitiveId();
  await eda.sch_PrimitiveComponent.modify(pid, { designator: s.ref, name: s.val || undefined, supplier: 'LCSC', supplierId: s.id });
  const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(pid);
  const rec = { ref: s.ref, pid, pins: [] };
  for (const p of pins) {
    const num = p.getState_PinNumber();
    const name = p.getState_PinName();
    const net = (s.nets || {})[num] || (s.nets || {})[name];
    const px = p.getState_X();
    const py = p.getState_Y();
    rec.pins.push({ num, name, x: px, y: py, net: net || null });
    if (net) {
      const dx = px < s.x ? -(s.stub || 20) : (s.stub || 20);
      await eda.sch_PrimitiveWire.create([px, py, px + dx, py], net);
    }
  }
  log.push(rec);
}
return log;
"""

NETLIST = r"""
const page = PAGE;
if (page) await eda.dmt_EditorControl.openDocument(page);
const f = await eda.sch_ManufactureData.getNetlistFile('n');
if (!f) return null;
return await f.text();
"""

CLEAR = r"""
const parts = await eda.sch_PrimitiveComponent.getAll();
let n = 0;
for (const c of parts) {
  if (c.getState_ComponentType() === 'sheet') continue;
  await eda.sch_PrimitiveComponent.delete(c);
  n++;
}
const wires = await eda.sch_PrimitiveWire.getAll();
for (const w of wires) { await eda.sch_PrimitiveWire.delete(w); n++; }
return n;
"""


def run(code, timeout=170):
    r = subprocess.run(['curl', '-s', '-m', str(timeout), '-X', 'POST', 'http://localhost:49620/execute',
                        '-H', 'Content-Type: application/json', '-d', json.dumps({'code': code})],
                       capture_output=True, text=True)
    out = json.loads(r.stdout)
    if not out.get('success'):
        raise RuntimeError(out.get('error'))
    return out['result']


def place(specs, page=None):
    """部品を置く。page（回路図ページの UUID）を渡すと、同じ処理の中で開いて確認してから置く。"""
    return run(HELPER.replace('SPECS', json.dumps(specs)).replace('PAGE', json.dumps(page)))


def nets(page=None):
    """ネットリストを {ネット名: [部品.ピン(ピン名), ...]} にして返す。ネットなしのピンは '(未接続)'。
    getNetlistFile() は、開いているページが属するボードの回路図全体（全ページ）を返す。
    page で、対象のボードのページを指定する（別のボードを見ないように）。"""
    data = json.loads(run(NETLIST.replace('PAGE', json.dumps(page))))
    result = {}
    for comp in data.get('components', {}).values():
        props = comp.get('props', {})
        des = props.get('Designator', '?')
        for pin in comp.get('pinInfoMap', {}).values():
            net = pin.get('net') or '(未接続)'
            result.setdefault(net, []).append(f"{des}.{pin.get('number')}({pin.get('name')})")
    return {k: sorted(v) for k, v in result.items()}, data


def clear_page(page=None):
    """ページ上の部品と線を、シート以外すべて削除する。page を渡すと、先に開いて確認する。"""
    pre = ''
    if page:
        pre = ("await eda.dmt_EditorControl.openDocument(%s);\n"
               "const doc = await eda.dmt_SelectControl.getCurrentDocumentInfo();\n"
               "if (!doc || doc.uuid !== %s) return 'wrong page';\n") % (json.dumps(page), json.dumps(page))
    return run(pre + CLEAR)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'nets':
        n, _ = nets()
        for k in sorted(n):
            print(k, n[k])
