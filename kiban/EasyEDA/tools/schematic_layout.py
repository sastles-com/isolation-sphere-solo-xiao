"""人が読める回路図を EasyEDA に描くための道具（eda_bridge 経由）。

描き方の方針：
- IC の各ピンは、短い線（stub）の先にネット名の文字を付ける
- 周辺回路は機能ごとに枠で囲み、レール（横線）から部品を縦にぶら下げ、下を GND にする
- 接続はすべて「ネット名を付けた線」で作る。同じ名前の線は、ページをまたいでもつながる

注意（2026-10-08 実測）：API で作った GND 記号・電源記号（createNetFlag）とネットポート
（createNetPort）が 1 つでもあると、getNetlistFile() が null を返し、DRC に致命的エラーが出る。
そのため記号は使わず、線と文字だけで描く。

座標は回路図の単位（0.01 inch）。y は上が大きい。

使い方：
    s = Sheet(page_uuid)
    s.part('R1', 'C25804', '10k', 100, 200, rot=90)   # 部品を登録
    s.place()                                       # まとめて置き、ピン座標を読む
    s.hang('R1', rail_y=260, rail_net='VBUS')       # 上のピンをレールへ、下のピンを GND へ
    s.flush()                                       # 線・記号・文字をまとめて描く
"""
import json

import eda_bridge as e

PLACE_JS = r"""
const page = PAGE;
await eda.dmt_EditorControl.openDocument(page);
const doc = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!doc || doc.uuid !== page) return {error: 'active page is ' + (doc && doc.uuid)};
const specs = SPECS;
const devs = await eda.lib_Device.getByLcscIds([...new Set(specs.map(s => s.id))]);
const map = {};
for (const d of devs) map[d.supplierId] = d;
const out = {};
for (const s of specs) {
  const cur = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  if (!cur || cur.uuid !== page) {
    await eda.dmt_EditorControl.openDocument(page);
    const again = await eda.dmt_SelectControl.getCurrentDocumentInfo();
    if (!again || again.uuid !== page) return {error: 'page switched to ' + (again && again.uuid)};
  }
  if (!map[s.id]) { out[s.ref] = {error: 'no device ' + s.id}; continue; }
  const c = await eda.sch_PrimitiveComponent.create(map[s.id], s.x, s.y, '', s.rot, false, s.bom, true);
  const pid = c.getState_PrimitiveId();
  await eda.sch_PrimitiveComponent.modify(pid, {designator: s.ref, name: s.val || undefined, supplier: 'LCSC', supplierId: s.id});
  const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(pid);
  out[s.ref] = {pid, pins: pins.map(p => [p.getState_PinNumber(), p.getState_PinName(), p.getState_X(), p.getState_Y(), p.getState_Rotation()])};
}
return out;
"""

OPS_JS = r"""
const page = PAGE;
await eda.dmt_EditorControl.openDocument(page);
const doc = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!doc || doc.uuid !== page) return 'active page is ' + (doc && doc.uuid);
const ops = OPS;
let n = 0;
for (const o of ops) {
  const cur = await eda.dmt_SelectControl.getCurrentDocumentInfo();
  if (!cur || cur.uuid !== page) {
    await eda.dmt_EditorControl.openDocument(page);
    const again = await eda.dmt_SelectControl.getCurrentDocumentInfo();
    if (!again || again.uuid !== page) return 'page switched to ' + (again && again.uuid);
  }
  if (o.t === 'w') await eda.sch_PrimitiveWire.create(o.p, o.n);
  else if (o.t === 'x') await eda.sch_PrimitiveText.create(o.x, o.y, o.s, 0, null, null, o.z, o.b);
  else if (o.t === 'r') await eda.sch_PrimitiveRectangle.create(o.x, o.y, o.w, o.h, 0, 0, null, null, null, 1);
  n++;
}
return n;
"""

ROT = {'L': 180, 'R': 0, 'T': 90, 'B': 270}
STEP = {'L': (-1, 0), 'R': (1, 0), 'T': (0, 1), 'B': (0, -1)}


class Sheet:
    def __init__(self, page):
        self.page = page
        self.specs = []
        self.ops = []
        self.P = {}

    # ---- 部品
    def part(self, ref, lcsc, val, x, y, rot=0, bom=True):
        self.specs.append({'id': lcsc, 'ref': ref, 'val': val, 'x': x, 'y': y, 'rot': rot, 'bom': bom})

    def place(self, batch=8):
        for k in range(0, len(self.specs), batch):
            chunk = self.specs[k:k + batch]
            code = PLACE_JS.replace('PAGE', json.dumps(self.page)).replace('SPECS', json.dumps(chunk))
            res = e.run(code)
            if 'error' in res:
                raise RuntimeError(res['error'])
            for s in chunk:
                r = res[s['ref']]
                if 'error' in r:
                    raise RuntimeError(f"{s['ref']}: {r['error']}")
                pins, rots = {}, {}
                for num, name, x, y, rot in r['pins']:
                    pins.setdefault(num, (x, y))
                    pins.setdefault(name, (x, y))
                    rots.setdefault(num, rot)
                    rots.setdefault(name, rot)
                self.P[s['ref']] = {'x': s['x'], 'y': s['y'], 'pins': pins, 'rots': rots, 'raw': r['pins']}

    def pin(self, ref, key):
        return self.P[ref]['pins'][key]

    def side(self, ref, key):
        """ピンが外へ向く方向。ピンの回転（180=左、0=右、90=上、270=下）で決める。"""
        rot = self.P[ref]['rots'].get(key)
        if rot is not None:
            return {180: 'L', 0: 'R', 90: 'T', 270: 'B'}[int(rot) % 360]
        x, y = self.pin(ref, key)
        dx, dy = x - self.P[ref]['x'], y - self.P[ref]['y']
        if abs(dx) >= abs(dy):
            return 'R' if dx > 0 else 'L'
        return 'T' if dy > 0 else 'B'

    def top(self, ref):
        """縦に置いた 2 端子部品の、上のピン番号。"""
        return max(('1', '2'), key=lambda k: self.pin(ref, k)[1])

    def bottom(self, ref):
        return min(('1', '2'), key=lambda k: self.pin(ref, k)[1])

    # ---- 線・記号・文字
    def w(self, a, b, net):
        """a から b へ。斜めなら、横 → 縦の L 字にする。"""
        (x1, y1), (x2, y2) = a, b
        if x1 != x2 and y1 != y2:
            self.ops.append({'t': 'w', 'p': [x1, y1, x2, y1], 'n': net})
            self.ops.append({'t': 'w', 'p': [x2, y1, x2, y2], 'n': net})
        elif (x1, y1) != (x2, y2):
            self.ops.append({'t': 'w', 'p': [x1, y1, x2, y2], 'n': net})

    def wv(self, a, b, net):
        """a から b へ。斜めなら、縦 → 横の L 字にする。"""
        (x1, y1), (x2, y2) = a, b
        if x1 != x2 and y1 != y2:
            self.ops.append({'t': 'w', 'p': [x1, y1, x1, y2], 'n': net})
            self.ops.append({'t': 'w', 'p': [x1, y2, x2, y2], 'n': net})
        else:
            self.w(a, b, net)

    def port(self, at, net, d):
        """at にネット名の文字を置く（線は呼び出し側で引く）。d は線が伸びてきた向き。"""
        x, y = at
        w = int(4.2 * len(net)) + 3
        pos = {'L': (x - w, y - 3), 'R': (x + 3, y - 3), 'T': (x - w // 2, y + 3), 'B': (x - w // 2, y - 11)}[d]
        self.text(pos[0], pos[1], net, size=7)

    def gnd(self, at, net='GND'):
        """at（ピンや線の端）から下へ 10 の線を引き、GND の文字を付ける。"""
        x, y = at
        self.w(at, (x, y - 10), net)
        self.text(x - 8, y - 20, net, size=7)

    def pwr(self, at, net):
        """at から上へ 10 の線を引き、ネット名の文字を付ける。"""
        x, y = at
        self.w(at, (x, y + 10), net)
        self.text(x - int(2.1 * len(net)), y + 13, net, size=7)

    def text(self, x, y, s, size=8, bold=False):
        self.ops.append({'t': 'x', 'x': x, 'y': y, 's': s, 'z': size, 'b': bold})

    def frame(self, x, y_top, w, h, title):
        self.ops.append({'t': 'r', 'x': x, 'y': y_top, 'w': w, 'h': h})
        self.text(x + 5, y_top - 12, title, size=10, bold=True)

    # ---- よく使う組み合わせ
    def label(self, ref, key, net, stub=30, kind='port'):
        """ピンから外側へ stub だけ線を出し、先にラベル（port / gnd / pwr）を付ける。"""
        p = self.pin(ref, key)
        d = self.side(ref, key)
        sx, sy = STEP[d]
        end = (p[0] + sx * stub, p[1] + sy * stub)
        self.w(p, end, net)
        if net == 'GND':
            self.text(end[0] + (3 if d != 'L' else -21), end[1] - 3, 'GND', size=7)
        else:
            self.port(end, net, d)
        return end

    def rail(self, net, y, x0, x1, flag_at=None):
        self.w((x0, y), (x1, y), net)
        if flag_at is not None:
            self.pwr((flag_at, y), net)

    def hang(self, ref, rail_y, rail_net, bottom='GND', bottom_kind='gnd'):
        """縦の 2 端子部品：上のピンを縦線でレールへ、下のピンを GND（またはラベル）へ。"""
        t, b = self.pin(ref, self.top(ref)), self.pin(ref, self.bottom(ref))
        self.w(t, (t[0], rail_y), rail_net)
        if bottom_kind == 'gnd':
            self.gnd(b, bottom)
        else:
            self.end_label(b, bottom, 'B')

    def end_label(self, at, net, d, stub=10):
        """at から d の向きへ stub だけ線を出し、先にネット名の文字を付ける。"""
        if net == 'GND' and d == 'B':
            self.gnd(at)
            return
        sx, sy = STEP[d]
        end = (at[0] + sx * stub, at[1] + sy * stub)
        self.w(at, end, net)
        self.port(end, net, d)

    def flush(self, batch=40):
        total = 0
        for k in range(0, len(self.ops), batch):
            code = OPS_JS.replace('PAGE', json.dumps(self.page)).replace('OPS', json.dumps(self.ops[k:k + batch]))
            r = e.run(code)
            if not isinstance(r, int):
                raise RuntimeError(r)
            total += r
        self.ops = []
        return total
