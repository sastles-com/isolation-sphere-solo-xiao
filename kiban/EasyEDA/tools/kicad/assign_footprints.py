#!/usr/bin/env python3
"""boardB.kicad_sch の部品に、LCSC 品番とフットプリントを割り当てる（値と部品番号から決める）。

  python3 tools/kicad/assign_footprints.py [回路図ファイル]

フットプリントは kicad/lib/lcsc.kicad_sym に入っている LCSC 部品の Footprint から引く。
ライブラリに無い品番（L2 の C87572 など）は、フットプリントを空のままにして報告する。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.abspath(os.path.join(HERE, '..', '..', 'kicad'))
SCH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KICAD, 'boardB', 'boardB.kicad_sch')

BY_VALUE = {  # 値 → LCSC 品番
    '10uF': 'C15850', '0.1uF': 'C1591', '1nF': 'C1588', '47nF': 'C1622', '4.7uF': 'C19666',
    '1uF': 'C15849', '2.2uF': 'C23630',
    '100kΩ': 'C25803', '127kΩ': 'C22869', '6.04kΩ': 'C25977', '5.23kΩ': 'C23068', '30.1kΩ': 'C23000',
    '10kΩ': 'C25804', '100Ω': 'C22775', '10Ω': 'C22859', '5.1Ω': 'C25197', '5.1kΩ': 'C23186', '10MΩ': 'C7250',
}
BY_REF = {'D1': 'C2900732', 'D2': 'C2286', 'F2': 'C108585', 'J1': 'C492401', 'J2': 'C492405', 'J3': 'C492405',
          'J4': 'C492401', 'J5': 'C492401', 'L2': 'C87572', 'R6': 'C13564', 'R13': 'C13564', 'R18': 'C154630',
          'Q2': 'C908265', 'U1': 'C20345237', 'U3': 'C2862876'}


def lib_footprints():
    s = open(os.path.join(KICAD, 'lib', 'lcsc.kicad_sym'), encoding='utf-8').read()
    out = {}
    for blk in re.split(r'\n\t\(symbol "', s)[1:]:
        l = re.search(r'"LCSC Part"\s*"(C\d+)"', blk)
        f = re.search(r'"Footprint"\s*"([^"]*)"', blk)
        if l and f:
            out[l.group(1)] = f.group(1)
    return out


def block_end(s, start):
    depth, i, q = 0, start, False
    while True:
        c = s[i]
        if c == '"' and s[i - 1] != '\\':
            q = not q
        elif not q:
            depth += (c == '(') - (c == ')')
            if depth == 0:
                return i + 1
        i += 1


def prop(name, value, at, hide=True):
    return (f'\n\t\t(property "{name}" "{value}"\n\t\t\t(at {at} 0)\n' + ('\t\t\t(hide yes)\n' if hide else '') +
            '\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)')


def main():
    fps = lib_footprints()
    s = open(SCH, encoding='utf-8').read()
    done, nofp = 0, []
    for m in list(re.finditer(r'\(property "Reference" "([A-Z]+\d+)"', s)):
        pass
    refs = re.findall(r'\(property "Reference" "([A-Z]+\d+)"', s)
    for ref in refs:
        m = re.search(r'\(property "Reference" "%s"' % re.escape(ref), s)
        end_inst = s.index('(instances', m.end())
        val = re.search(r'\(property "Value" "([^"]*)"', s[m.end():end_inst]).group(1)
        lcsc = BY_REF.get(ref) or BY_VALUE.get(val)
        if not lcsc:
            nofp.append(f'{ref}（{val}）：品番の対応なし')
            continue
        fp = fps.get(lcsc, '')
        if not fp:
            nofp.append(f'{ref}（{val}、{lcsc}）：ライブラリにフットプリントなし')
        a = m.end()
        fm = re.search(r'\(property "Footprint" "[^"]*"', s[a:end_inst])
        fs = a + fm.start()
        fe = block_end(s, fs)
        blk = s[fs:fe]
        at = re.search(r'\(at ([\d.\- ]+?) 0\)', blk).group(1)
        new = re.sub(r'(\(property "Footprint" )"[^"]*"', lambda x: x.group(1) + f'"{fp}"', blk, count=1)
        s = s[:fs] + new + s[fe:]
        end_inst = s.index('(instances', m.end())
        lm = re.search(r'\(property "LCSC Part" "[^"]*"', s[m.end():end_inst])
        if lm:
            ls = m.end() + lm.start()
            s = s[:ls] + re.sub(r'"[^"]*"$', f'"{lcsc}"', s[ls:m.end() + lm.end()]) + s[m.end() + lm.end():]
        else:
            fe = fs + len(new)
            s = s[:fe] + prop('LCSC Part', lcsc, at) + s[fe:]
        done += 1
    open(SCH, 'w', encoding='utf-8').write(s)
    print(f'{done} 部品に割り当て')
    for n in nofp:
        print('⚠️', n)


if __name__ == '__main__':
    main()
