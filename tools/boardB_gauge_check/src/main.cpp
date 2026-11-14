// 基板B (充電 IC BQ25792 = 0x6B、残量計・保護 IC BQ28Z620 = 0x55) を XIAO ESP32S3 から直接読む確認用スケッチ。
//
// 目的: 電池だけでは VSYS が出ない (保護 FET Q2 が開かない) 原因を、残量計の状態から切り分ける。
//   BQ28Z620 は ManufacturingStatus() の FET_EN が 0 の間、CHG / DSG の FET を駆動しない。
//   出荷時のデータフラッシュ (Mfg Status init, 0x43C0) の既定値は 0x0000 なので、設定するまで FET は開かない。
//   (TI SLUUCO9B §14.2.16, §14.2.38, §15 のデータフラッシュ表)
//   もう 1 つ: 残量計は PACK ピンが 2.05〜2.45 V を超えるまで SHUTDOWN のまま (データシート SLUSET3)。PACK は FET の先なので、
//   セルだけでは起きない。J11 (BAT_F) と J10 (PACK_P) を 8.2 kΩ でつなぐか、充電入力を入れて起こしてから使う。
//   SHUTDOWN 中の残量計は I2C の線を約 2 V に引き下げる (BNO055 も見えなくなる)。
//
// 配線 (基板A は外す。XIAO の 3.3 V / 5 V は基板B へ入れない):
//   B_J3 の 1 番 = SDA -> XIAO D10 (GPIO9)
//   B_J3 の 3 番 = SCL -> XIAO D9  (GPIO8)
//   B_J3 の 2 / 6 番 = GND -> XIAO GND
//   プルアップは 3.3 V へ (BNO055 モジュールのものを借りるか、4.7k〜10k を 2 本)。
//   セルは接続したまま。充電 IC (0x6B) も読むなら充電入力 (9 V) も入れる。
//
// シリアル (115200) のコマンド:
//   s : スキャンして状態を表示 (読むだけ)
//   v : SDA / SCL の電圧を測る (読むだけ。測ったあと再起動する)
//   p : I2C のピンの組み合わせを総当たりでスキャンする (読むだけ)
//   m : ManufacturingStatus / OperationStatus の MAC 応答をそのまま表示する (読むだけ)
//   F : FET 制御 (0x0022) を切り替える。確認に y を求める。電源を切ると元に戻る
//   W : データフラッシュの Mfg Status init に FET_EN を書く (電源を入れ直しても FET が有効になる)。確認に y を求める
#include <Arduino.h>
#include <Wire.h>

namespace {

constexpr uint8_t kSda = 9;   // D10 (本体ファームの BoardConfig.h と同じ)
constexpr uint8_t kScl = 8;   // D9
constexpr uint8_t kCharger = 0x6B;
constexpr uint8_t kGauge = 0x55;

// BQ28Z620 の標準コマンド (読み出しは 2 バイト、リトルエンディアン)
constexpr uint8_t kCmdTemperature = 0x06;    // 0.1 K
constexpr uint8_t kCmdVoltage = 0x08;        // mV (セル電圧の合計)
constexpr uint8_t kCmdBatteryStatus = 0x0A;
constexpr uint8_t kCmdCurrent = 0x0C;        // mA
constexpr uint8_t kCmdMacSubcmd = 0x3E;      // 0x3E/3F = サブコマンド、0x40〜0x5F = データ、0x60 = チェックサム、0x61 = 長さ

// MAC サブコマンド
constexpr uint16_t kMacFetControl = 0x0022;
constexpr uint16_t kMacSafetyAlert = 0x0050;
constexpr uint16_t kMacSafetyStatus = 0x0051;
constexpr uint16_t kMacPfStatus = 0x0053;
constexpr uint16_t kMacOperationStatus = 0x0054;
constexpr uint16_t kMacManufacturingStatus = 0x0057;
constexpr uint16_t kMacDaStatus1 = 0x0071;
constexpr uint16_t kMacOperationStatusDump = 0x0054;
constexpr uint16_t kDfMfgStatusInit = 0x43C0;   // データフラッシュ: Settings > Manufacturing > Mfg Status init (H2)

constexpr uint16_t kMfgFetEn = 1u << 4;

bool probe(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

bool readBytes(uint8_t addr, uint8_t reg, uint8_t* buf, size_t len) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) {
        return false;
    }
    if (Wire.requestFrom(addr, len) != len) {
        return false;
    }
    for (size_t i = 0; i < len; ++i) {
        buf[i] = Wire.read();
    }
    return true;
}

bool readWord(uint8_t reg, uint16_t& out) {
    uint8_t b[2];
    if (!readBytes(kGauge, reg, b, 2)) {
        return false;
    }
    out = static_cast<uint16_t>(b[0] | (b[1] << 8));
    return true;
}

bool writeBytes(uint8_t addr, uint8_t reg, const uint8_t* data, size_t len) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    Wire.write(data, len);
    return Wire.endTransmission() == 0;
}

// サブコマンドを送り、応答 (最大 32 バイト) を読む。応答の先頭 2 バイトが送ったサブコマンドと一致し、
// チェックサムが合うことを確かめる。戻り値はデータの長さ (失敗は -1)。
int macRead(uint16_t subcmd, uint8_t* data) {
    const uint8_t cmd[2] = {static_cast<uint8_t>(subcmd & 0xFF), static_cast<uint8_t>(subcmd >> 8)};
    if (!writeBytes(kGauge, kCmdMacSubcmd, cmd, 2)) {
        return -1;
    }
    delay(5);
    uint8_t blk[36];   // サブコマンド 2 + データ 32 + チェックサム 1 + 長さ 1
    if (!readBytes(kGauge, kCmdMacSubcmd, blk, sizeof(blk))) {
        return -1;
    }
    if (blk[0] != cmd[0] || blk[1] != cmd[1]) {
        return -1;
    }
    const int len = blk[35] - 4;   // 長さにはサブコマンド・チェックサム・長さの 4 バイトが含まれる
    if (len < 1 || len > 32) {
        return -1;
    }
    uint8_t sum = 0;
    for (int i = 0; i < len + 2; ++i) {
        sum += blk[i];
    }
    if (static_cast<uint8_t>(~sum) != blk[34]) {
        return -1;
    }
    memcpy(data, blk + 2, len);
    return len;
}

bool macRead16(uint16_t subcmd, uint16_t& out) {
    uint8_t d[32];
    if (macRead(subcmd, d) < 2) {
        return false;
    }
    out = static_cast<uint16_t>(d[0] | (d[1] << 8));
    return true;
}

bool macRead32(uint16_t subcmd, uint32_t& out) {
    uint8_t d[32];
    if (macRead(subcmd, d) < 4) {
        return false;
    }
    out = static_cast<uint32_t>(d[0]) | (static_cast<uint32_t>(d[1]) << 8) |
          (static_cast<uint32_t>(d[2]) << 16) | (static_cast<uint32_t>(d[3]) << 24);
    return true;
}

// データのないサブコマンドは、0x00 (ManufacturerAccess) へ書くだけで実行される。
bool macCommand(uint16_t subcmd) {
    const uint8_t cmd[2] = {static_cast<uint8_t>(subcmd & 0xFF), static_cast<uint8_t>(subcmd >> 8)};
    return writeBytes(kGauge, 0x00, cmd, 2);
}

// データフラッシュの 2 バイトを書く。0x3E へ「番地 + データ」、続けて 0x60 へ「チェックサム + 長さ」を書くと実行される。
bool dfWrite16(uint16_t addr, uint16_t value) {
    const uint8_t blk[4] = {static_cast<uint8_t>(addr & 0xFF), static_cast<uint8_t>(addr >> 8),
                            static_cast<uint8_t>(value & 0xFF), static_cast<uint8_t>(value >> 8)};
    if (!writeBytes(kGauge, kCmdMacSubcmd, blk, sizeof(blk))) {
        return false;
    }
    uint8_t sum = 0;
    for (uint8_t b : blk) {
        sum += b;
    }
    const uint8_t tail[2] = {static_cast<uint8_t>(~sum), static_cast<uint8_t>(sizeof(blk) + 2)};
    return writeBytes(kGauge, 0x60, tail, 2);
}

void printBits(uint32_t v, const char* const* names, const uint8_t* bits, size_t n) {
    bool any = false;
    for (size_t i = 0; i < n; ++i) {
        if (v & (1ul << bits[i])) {
            Serial.printf(" %s", names[i]);
            any = true;
        }
    }
    if (!any) {
        Serial.print(" (なし)");
    }
    Serial.println();
}

void showCharger() {
    if (!probe(kCharger)) {
        Serial.println("[0x6B] BQ25792: 応答なし (充電入力がないと応答しないことがある)");
        return;
    }
    uint8_t part = 0;
    uint8_t st[5] = {};
    readBytes(kCharger, 0x48, &part, 1);
    readBytes(kCharger, 0x1B, st, sizeof(st));
    // レジスタの意味はデータシートで読む (ここでは生の値だけを出す)
    Serial.printf("[0x6B] BQ25792: 応答あり  REG48=0x%02X  REG1B..1F=%02X %02X %02X %02X %02X\n",
                  part, st[0], st[1], st[2], st[3], st[4]);
}

void showGauge() {
    if (!probe(kGauge)) {
        Serial.println("[0x55] BQ28Z620: 応答なし -> 残量計の電源 (VC2 / PBI / PACK) と I2C の配線・プルアップを確認する");
        return;
    }
    Serial.println("[0x55] BQ28Z620: 応答あり");

    uint16_t w = 0;
    if (readWord(kCmdVoltage, w)) {
        Serial.printf("  Voltage()        %u mV (テスターの BAT_F と比べる)\n", w);
    }
    if (readWord(kCmdCurrent, w)) {
        Serial.printf("  Current()        %d mA\n", static_cast<int16_t>(w));
    }
    if (readWord(kCmdTemperature, w)) {
        Serial.printf("  Temperature()    %.1f C\n", w / 10.0 - 273.15);
    }
    // 残量。GAUGE_EN = 0 (Impedance Track が無効) の間や、学習前は正しくない
    if (readWord(0x2C, w)) {   // StateOfCharge() (BQ28Z610 系は 0x2C)
        Serial.printf("  RelativeStateOfCharge() %u %%\n", w);
    }
    if (readWord(0x10, w)) {
        uint16_t full = 0;
        readWord(0x12, full);
        Serial.printf("  RemainingCapacity() %u mAh / FullChargeCapacity() %u mAh\n", w, full);
    }
    if (readWord(kCmdBatteryStatus, w)) {
        Serial.printf("  BatteryStatus()  0x%04X\n", w);
    }

    uint8_t d[32];
    if (macRead(kMacDaStatus1, d) >= 12) {
        Serial.printf("  DAStatus1        cell1=%u mV  cell2=%u mV  BAT=%u mV  PACK=%u mV\n",
                      d[0] | (d[1] << 8), d[2] | (d[3] << 8), d[8] | (d[9] << 8), d[10] | (d[11] << 8));
    } else {
        Serial.println("  DAStatus1        読めない");
    }

    uint16_t mfg = 0;
    if (macRead16(kMacManufacturingStatus, mfg)) {
        Serial.printf("  ManufacturingStatus 0x%04X  FET_EN=%d GAUGE_EN=%d LF_EN=%d PF_EN=%d\n", mfg,
                      (mfg >> 4) & 1, (mfg >> 3) & 1, (mfg >> 5) & 1, (mfg >> 6) & 1);
        if (!(mfg & kMfgFetEn)) {
            Serial.println("    -> FET_EN = 0: 残量計は FET を駆動しない。これが FET が開かない原因。F で有効にできる");
        }
    } else {
        Serial.println("  ManufacturingStatus 読めない");
    }

    uint32_t v = 0;
    if (macRead32(kMacOperationStatus, v)) {
        static const char* const kNames[] = {"DSG(放電FET ON)", "CHG(充電FET ON)", "SDV", "SS(保護動作中)", "PF(永久故障)",
                                             "SLEEP", "INIT", "EMSHUT"};
        static const uint8_t kBits[] = {1, 2, 10, 11, 12, 15, 24, 29};
        Serial.printf("  OperationStatus  0x%08lX  SEC=%lu (1=FullAccess 2=Unsealed 3=Sealed) :", v, (v >> 8) & 3);
        printBits(v, kNames, kBits, sizeof(kBits));
    }
    static const char* const kSafetyNames[] = {"CUV", "COV", "OCC", "OCD", "AOLD", "ASCC", "ASCD",
                                               "OTC", "OTD", "PTO", "CTO", "UTC", "UTD"};
    static const uint8_t kSafetyBits[] = {0, 1, 2, 4, 6, 8, 10, 12, 13, 18, 20, 26, 27};
    if (macRead32(kMacSafetyAlert, v)) {
        Serial.printf("  SafetyAlert      0x%08lX :", v);
        printBits(v, kSafetyNames, kSafetyBits, sizeof(kSafetyBits));
    }
    if (macRead32(kMacSafetyStatus, v)) {
        Serial.printf("  SafetyStatus     0x%08lX :", v);
        printBits(v, kSafetyNames, kSafetyBits, sizeof(kSafetyBits));
    }
    if (macRead32(kMacPfStatus, v)) {
        Serial.printf("  PFStatus         0x%08lX%s\n", v, v ? "  <- 永久故障のフラグあり" : "");
    }
    if (macRead(kDfMfgStatusInit, d) >= 2) {
        Serial.printf("  DF Mfg Status init (0x43C0) 0x%04X\n", d[0] | (d[1] << 8));
    }
}

// I2C のピンが回路図と違う疑いがあるときの切り分け：候補の GPIO の組み合わせをすべて試して、応答するアドレスを探す。
// 候補は D4 / D5 (GPIO5 / 6、XIAO の標準)、D8 (7)、D9 (8)、D10 (9)。ブザー (43) と LED_EN (44) は使わない。
void sweepPins() {
    static const uint8_t pins[] = {5, 6, 7, 8, 9};
    Serial.println("\n===== ピンの総当たり (SDA, SCL) =====");
    for (uint8_t sda : pins) {
        for (uint8_t scl : pins) {
            if (sda == scl) continue;
            Wire.end();
            Wire.begin(sda, scl, 100000);
            Wire.setTimeOut(20);
            Serial.printf("SDA=GPIO%d SCL=GPIO%d idle=%d%d :", sda, scl, digitalRead(sda), digitalRead(scl));
            for (uint8_t addr = 0x08; addr <= 0x77; ++addr) {
                if (probe(addr)) Serial.printf(" 0x%02X", addr);
            }
            Serial.println();
        }
    }
    Wire.end();
    for (uint8_t p : pins) pinMode(p, INPUT);
    Wire.begin(kSda, kScl, 100000);
    Serial.println("(元のピンに戻した)");
}

// 線の実際の電圧 (ADC)。内蔵プルアップを切って測る。外付けのプルアップが生きていれば約 3.1 V 以上 (ADC の上限)。
// ADC に切り替えたピンは I2C に戻すとスキャンが止まるので、測ったら再起動する。
void showLineVoltage() {
    Wire.end();
    pinMode(kSda, INPUT);
    pinMode(kScl, INPUT);
    delay(20);
    Serial.printf("line voltage SDA=%lu mV SCL=%lu mV (内蔵プルアップなし)。再起動する\n",
                  (unsigned long)analogReadMilliVolts(kSda), (unsigned long)analogReadMilliVolts(kScl));
    Serial.flush();
    delay(100);
    ESP.restart();
}

void showAll() {
    Serial.println("\n===== 基板B I2C =====");
    // 通信していないときの線の電圧。プルアップが効いていれば両方 1。0 なら、プルアップの電源が無いか、線が Low に引かれている
    Serial.printf("idle SDA(GPIO%d)=%d SCL(GPIO%d)=%d\n", kSda, digitalRead(kSda), kScl, digitalRead(kScl));
    int found = 0;
    for (uint8_t addr = 0x08; addr <= 0x77; ++addr) {
        if (probe(addr)) {
            Serial.printf("found 0x%02X\n", addr);
            ++found;
        }
    }
    Serial.printf("%d device(s)\n", found);
    showCharger();
    showGauge();
    Serial.println("コマンド: s = 再表示, F = FET 制御の切り替え, W = FET_EN をデータフラッシュに保存");
}

bool confirm(const char* what) {
    Serial.printf("%s 実行するなら y を送る (10 秒以内): ", what);
    const uint32_t t0 = millis();
    while (millis() - t0 < 10000) {
        if (Serial.available()) {
            const int c = Serial.read();
            if (c == '\r' || c == '\n') {
                continue;
            }
            Serial.println(static_cast<char>(c));
            return c == 'y';
        }
        delay(10);
    }
    Serial.println("(時間切れ)");
    return false;
}

// MAC サブコマンドの応答を、そのまま 16 進で表示する (読むだけ)。macRead が失敗する理由を見るため
void dumpMac(uint16_t subcmd) {
    const uint8_t cmd[2] = {static_cast<uint8_t>(subcmd & 0xFF), static_cast<uint8_t>(subcmd >> 8)};
    if (!writeBytes(kGauge, kCmdMacSubcmd, cmd, 2)) {
        Serial.printf("MAC 0x%04X: サブコマンドを書けない\n", subcmd);
        return;
    }
    delay(5);
    uint8_t blk[36];
    if (!readBytes(kGauge, kCmdMacSubcmd, blk, sizeof(blk))) {
        Serial.printf("MAC 0x%04X: 読めない\n", subcmd);
        return;
    }
    Serial.printf("MAC 0x%04X:", subcmd);
    for (uint8_t b : blk) Serial.printf(" %02X", b);
    Serial.println();
}

void toggleFet() {
    uint16_t before = 0;
    if (macRead16(kMacManufacturingStatus, before)) {
        Serial.printf("今の FET_EN = %d。0x0022 を送ると %d になる。\n", (before >> 4) & 1, ((before >> 4) & 1) ^ 1);
    } else {
        // BQ28Z620 で ManufacturingStatus (0x0057) が読めないことがある。0x0022 は FET_EN を反転するだけなので、
        // 送ったあと OperationStatus の CHG / DSG (FET が開いているか) で結果を確かめる
        dumpMac(kMacManufacturingStatus);
        Serial.println("ManufacturingStatus が読めない。DF の Mfg Status init が 0x0000 なら、今の FET_EN は 0 のはず (送ると 1 になる)");
    }
    if (!confirm("FET 制御を切り替える。")) {
        return;
    }
    if (!macCommand(kMacFetControl)) {
        Serial.println("送信に失敗");
        return;
    }
    delay(1500);   // 残量計が FET を動かすのを待つ
    showGauge();
    Serial.println("テスターで PACK_P (BAT_F とほぼ同じ電圧になるはず) と VSYS を測る");
}

void saveFetEn() {
    uint8_t d[32];
    if (macRead(kDfMfgStatusInit, d) < 2) {
        Serial.println("データフラッシュが読めないので中止 (Sealed では読めない)");
        return;
    }
    const uint16_t cur = static_cast<uint16_t>(d[0] | (d[1] << 8));
    const uint16_t want = cur | kMfgFetEn;
    Serial.printf("Mfg Status init: 今 0x%04X -> 0x%04X (FET_EN を立てる。ほかのビットは変えない)\n", cur, want);
    if (cur == want) {
        Serial.println("すでに立っている");
        return;
    }
    if (!confirm("データフラッシュに書く。")) {
        return;
    }
    if (!dfWrite16(kDfMfgStatusInit, want)) {
        Serial.println("書き込みに失敗");
        return;
    }
    delay(200);
    if (macRead(kDfMfgStatusInit, d) >= 2) {
        const uint16_t now = static_cast<uint16_t>(d[0] | (d[1] << 8));
        Serial.printf("読み直し: 0x%04X %s\n", now, now == want ? "OK" : "NG (書けていない)");
    }
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(1500);
    // 100 kHz。プルアップが弱くても読めるようにする
    Wire.begin(kSda, kScl, 100000);
    Wire.setTimeOut(50);
    showAll();
}

void loop() {
    if (!Serial.available()) {
        delay(10);
        return;
    }
    switch (Serial.read()) {
        case 's':
            showAll();
            break;
        case 'm':
            dumpMac(kMacManufacturingStatus);
            dumpMac(kMacOperationStatusDump);
            break;
        case 'p':
            sweepPins();
            break;
        case 'v':
            showLineVoltage();
            break;
        case 'F':
            toggleFet();
            break;
        case 'W':
            saveFetEn();
            break;
        default:
            break;
    }
}
