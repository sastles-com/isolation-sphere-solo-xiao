"""基板B 保護部（BQ28Z620、保護 FET、ヒューズ、シャント、電池・基板A コネクタ）を、
EasyEDA の BoardB 回路図の PROTECTION ページに置く。

回路は BQ28Z620 データシート Figure 10-1（2 直列）に従う。詳細は docs/boardB_schematic_notes.md §3〜§6。
- GND（= PACK−）はシステムのグラウンド。BAT_N はセルの−（BQ28Z620 の VSS）。間にシャント RSNS
- 保護 FET Q1（FS8205A、共通ドレイン）：FET1 = 充電用（電池側、G1/S1）、FET2 = 放電用（パック側、G2/S2）
- データシート図の 2N7002K（パック−の逆接続対策）は、電池を外さない構成なので入れない
再実行すると部品が二重になる。SKIP に入れた部品は置かない。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_bridge as e

PAGE = '3c04743d7cb514cc'   # BoardB 回路図の PROTECTION ページ
SKIP = set(sys.argv[1:])

U2 = ('U2', 'C20345237', 'BQ28Z620', {
    '1': 'BAT_N', '2': 'SRN_F', '3': 'SRP_F', '4': 'TS1', '5': 'G_SCL', '6': 'G_SDA', '7': 'DSG_O',
    '8': 'PACK_S', '9': 'CHG_O', '10': 'PBI', '11': 'VC2_F', '12': 'VC1_F', '13': 'BAT_N'})
Q1 = ('Q1', 'C908265', 'FS8205A', {
    '1': 'BAT_F', '6': 'CHG_G',            # FET1：充電用（電池側）
    '3': 'PACK_P', '4': 'DSG_G',           # FET2：放電用（パック側）
    '2': 'FET_D', '5': 'FET_D'})           # 共通ドレイン

P = [
    # 電池コネクタとヒューズ
    ('J_CELL1', 'C158012', 'XH 2P CELL1', {'1': 'BAT_N', '2': 'BAT_MID'}),
    ('J_CELL2', 'C158012', 'XH 2P CELL2', {'1': 'BAT_MID', '2': 'BAT_TOP'}),
    ('F1', 'C108585', 'PTC 5A', {'1': 'BAT_TOP', '2': 'BAT_F'}),
    # 保護 FET のゲートとバイアス、FET 間のコンデンサ
    ('RCHG', 'C23186', '5.1k', {'1': 'CHG_O', '2': 'CHG_G'}),
    ('RDSG', 'C23186', '5.1k', {'1': 'DSG_O', '2': 'DSG_G'}),
    ('RGC', 'C7250', '10M', {'1': 'CHG_G', '2': 'BAT_F'}),
    ('RGD', 'C7250', '10M', {'1': 'DSG_G', '2': 'PACK_P'}),
    ('CFX1', 'C1591', '0.1uF', {'1': 'PACK_P', '2': 'CFX_M'}),
    ('CFX2', 'C1591', '0.1uF', {'1': 'CFX_M', '2': 'BAT_F'}),
    # パック端子の ESD 用コンデンサ（直列 2 個）と PACK 検出
    ('CPK1', 'C1591', '0.1uF', {'1': 'PACK_P', '2': 'CPK_M'}),
    ('CPK2', 'C1591', '0.1uF', {'1': 'CPK_M', '2': 'GND'}),
    ('RPK', 'C22859', '10', {'1': 'PACK_P', '2': 'PACK_S'}),
    # セル電圧の検出
    ('RVC2', 'C25197', '5.1', {'1': 'BAT_TOP', '2': 'VC2_F'}),
    ('RVC1', 'C22775', '100', {'1': 'BAT_MID', '2': 'VC1_F'}),
    ('CVC', 'C15849', '1uF', {'1': 'VC1_F', '2': 'VC2_F'}),
    ('CVC1', 'C1591', '0.1uF', {'1': 'VC1_F', '2': 'BAT_N'}),
    ('CPBI', 'C23630', '2.2uF', {'1': 'PBI', '2': 'BAT_N'}),
    # 電流シャントと SRN / SRP フィルタ（ケルビン接続）
    ('RSNS', 'C154630', '2m', {'1': 'GND', '2': 'BAT_N'}),
    ('RSRN', 'C22775', '100', {'1': 'GND', '2': 'SRN_F'}),
    ('RSRP', 'C22775', '100', {'1': 'BAT_N', '2': 'SRP_F'}),
    ('CSRN', 'C1591', '0.1uF', {'1': 'SRN_F', '2': 'BAT_N'}),
    ('CSRP', 'C1591', '0.1uF', {'1': 'SRP_F', '2': 'BAT_N'}),
    ('CSRD', 'C1591', '0.1uF', {'1': 'SRN_F', '2': 'SRP_F'}),
    # 温度
    ('RT2', 'C13564', '10k NTC', {'1': 'TS1', '2': 'BAT_N'}),
    # I2C の保護（100 Ω + 5.6 V ツェナー + 100 Ω）
    ('RSCL1', 'C22775', '100', {'1': 'I2C_SCL', '2': 'G_SCLP'}),
    ('RSCL2', 'C22775', '100', {'1': 'G_SCLP', '2': 'G_SCL'}),
    ('DZ1', 'C22612', '5.6V', {'1': 'G_SCLP', '2': 'GND'}),
    ('RSDA1', 'C22775', '100', {'1': 'I2C_SDA', '2': 'G_SDAP'}),
    ('RSDA2', 'C22775', '100', {'1': 'G_SDAP', '2': 'G_SDA'}),
    ('DZ2', 'C22612', '5.6V', {'1': 'G_SDAP', '2': 'GND'}),
    # 基板A との接続（ピンヘッダ 1x6 × 2。easyeda_workflow.md §4.3）
    ('J_AB1', 'C492405', 'TO BOARD A PWR', {'1': 'VSYS', '2': 'VSYS', '3': 'VSYS', '4': 'GND', '5': 'GND', '6': 'GND'}),
    ('J_AB2', 'C492405', 'TO BOARD A SIG', {'1': 'I2C_SDA', '2': 'GND', '3': 'I2C_SCL', '4': 'CHG_INT', '6': 'GND'}),
]

specs = []
if 'U2' not in SKIP:
    specs.append({'id': U2[1], 'ref': U2[0], 'x': 300, 'y': 520, 'val': U2[2], 'nets': U2[3]})
if 'Q1' not in SKIP:
    specs.append({'id': Q1[1], 'ref': Q1[0], 'x': 800, 'y': 650, 'val': Q1[2], 'nets': Q1[3]})
for i, (ref, lc, val, nets) in enumerate(P):
    col, row = i % 10, i // 10
    specs.append({'id': lc, 'ref': ref, 'x': 100 + 105 * col, 'y': 380 - 75 * row, 'val': val, 'nets': nets})

for k in range(0, len(specs), 8):
    t = time.time()
    r = e.place(specs[k:k + 8], PAGE)
    print('batch', k // 8, round(time.time() - t, 1), 's', [x.get('err') or x['ref'] for x in r])
