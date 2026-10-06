#include "IMUManager.h"
#include <Arduino.h>
#include "Log.h"

// BNO055 (外部 9 軸、IMUPLUS モード) バックエンド。sphere001/002 の実装。
// 共通部 (getter / タスク / ダンプ / 平滑) は IMUManager.cpp。

namespace sastle {

IMUManager::IMUManager()
    : _initialized(false),
      _lastUpdate(0),
      _reader(Wire, 0x28, _i2c),
      _bno(55, 0x28) { // BNO055のI2Cアドレス: 0x28 (ADRピンがLOW)
}
bool IMUManager::begin(ConfigManager& config, uint8_t sda, uint8_t scl) {
    Serial.println("\n=== IMU Manager Initialization (BNO055) ===");

    // I2C 排他用ミューテックス。startTask() より前に必ず作る (作られる前に
    // I2cGuard が取られても no-op で安全だが、この時点ではまだ単一タスク)。
    if (!_i2c.begin()) {
        Serial.println("[IMU] I2C mutex creation failed");
        return false;
    }

    // I2C初期化（既に初期化されている場合はスキップ）
    // BNO055 は I2C クロックストレッチが長く、400kHz ではレジスタ読み出しが
    // 化ける (quat の w だけ動き x/y/z=0、ノルム≠1 の壊れた値を実機で確認)。
    // 100kHz (エラー検出+リトライ付き直接読みがあるため、失敗は検出・再試行される)。
    // ESP32 のソフト再起動 (OTA / ESP.restart) はスレーブの転送途中で起きるため、
    // BNO055 が SDA を握ったまま / バイト境界を見失ったまま次の起動を迎え得る。
    // Wire.begin の前に SCL を手で叩いて残りの転送を流し、STOP を打っておく。
    // 起動時の SDA レベルはログに出す (LOW ならバスが詰まっていた証拠)。
    // NOTE: 2026-09-09 にこれを有効にして OTA した直後の起動で BNO055 が検出されず
    // IMU 無しで起動した (imu_read=0/s)。USB シリアルが無く原因を切り分けられない
    // ため呼び出しを外している。有効化するときはシリアルで起動ログを見ながら行う。
    // _recoverI2cBus(sda, scl);

    if (!Wire.begin(sda, scl, _i2cHz)) {
        Serial.println("I2C bus initialization failed or already initialized");
    }
    // 1 トランザクションの上限。既定 50ms だと失敗の連鎖で IMU タスクが 200ms 止まる
    // (2026-09-09 dump: +206ms の空白)。BNO055 のクロックストレッチは 10ms 未満。
    // main.cpp の scanI2cBus() が先に Wire.begin 済みのため、ここで周波数を確実に適用する
    // (Wire.begin は 2 回目以降は何もしない。実機 2026-09-23 で 400kHz のまま動いていた)。
    Wire.setClock(_i2cHz);
    Wire.setTimeOut(20);
    delay(100);

    Serial.printf("I2C initialized (SDA: GPIO%d, SCL: GPIO%d)\n", sda, scl);

    // BNO055初期化
    if (!_bno.begin()) {
        Serial.println("BNO055 not detected! Check wiring.");
        return false;
    }

    Serial.println("BNO055 detected!");

    // センサー情報表示
    sensor_t sensor;
    _bno.getSensor(&sensor);
    Serial.println("------------------------------------");
    Serial.print("Sensor:       "); Serial.println(sensor.name);
    Serial.print("Driver Ver:   "); Serial.println(sensor.version);
    Serial.print("Unique ID:    "); Serial.println(sensor.sensor_id);
    Serial.print("Max Value:    "); Serial.print(sensor.max_value); Serial.println(" xxx");
    Serial.print("Min Value:    "); Serial.print(sensor.min_value); Serial.println(" xxx");
    Serial.print("Resolution:   "); Serial.print(sensor.resolution); Serial.println(" xxx");
    Serial.println("------------------------------------");

    delay(100);

    // 外部クリスタルは使用しない。
    // 注意: 外部水晶が実装されていないボードで true にすると、生センサー値
    // (gyro/accel) は読めるのに fusion 出力 (quat) が単位のまま固まる。
    // 実機で cal=0300 + quat恒久(1,0,0,0) の症状を確認したため false に変更。
    _bno.setExtCrystalUse(false);

    // 動作モードは IMUPLUS (加速度+ジャイロの6軸融合、磁気不使用)。
    // NDOF (9軸) は磁気キャリブレーション未完了時にヨーが「動かない→90°ジャンプ」
    // する上、本機はLED大電流・LiPoが磁気センサー近傍にあり磁気データが常に乱れる
    // ため不採用。IMUPLUS はヨーがジャイロ積分で滑らか (ドリフトは SET ZERO で解消)。
    // 注意: BNO055 は fusionモード間の直接切替を無視するため、必ず CONFIG を経由する
    // (begin() が NDOF にするので、直接 IMUPLUS を書いても効かない)。
    _bno.setMode(OPERATION_MODE_CONFIG);
    delay(25);
    _bno.setMode(OPERATION_MODE_IMUPLUS);
    delay(20);

    // 診断: モード/システム状態を起動ログに残す (mode=8 が IMUPLUS)
    {
        uint8_t sysStatus = 0, selfTest = 0, sysError = 0;
        _bno.getSystemStatus(&sysStatus, &selfTest, &sysError);
        Serial.printf("[IMU] boot diag: mode=%d sys_status=%u selftest=0x%X sys_error=%u\n",
                      (int)_bno.getMode(), sysStatus, selfTest, sysError);
    }

    _initialized = true;
    Serial.println("BNO055 initialized successfully!");

    // 初期キャリブレーション状態表示
    displayCalibrationStatus();

    return true;
}

bool IMUManager::update() {
    if (!_initialized) {
        return false;
    }
    // 専用タスク稼働中は I2C の二重アクセスになるため loop からの呼び出しは無視。
    if (_taskRunning) {
        return true;
    }

    unsigned long now = millis();
    if (now - _lastUpdate < UPDATE_INTERVAL) {
        return true; // まだ更新タイミングではない
    }

    _lastUpdate = now;
    return _updateOnce();
}


bool IMUManager::_updateOnce() {
    if (!_initialized) {
        return false;
    }
    const unsigned long now = millis();
    _lastUpdate = now;

    _applyPendingClock();
    // 再初期化要求 (MQTT led {"imu_reset": true})。I2C は IMU タスクからしか触らない。
    if (_resetPending) {
        _resetPending = false;
        return _reinitAndResync(false);
    }

    // 1) 読む: Adafruit の getQuat() は I2C 失敗を無視して古いバッファを返すので使わない。
    //    分割読み / MSB 欠落 / straddle の扱いは Bno055QuatReader に集約。
    const bool aux = _auxReads;
    uint8_t raw[8] = {0};
    Quat qRaw;
    uint8_t straddles = 0;
    const Quat prevQ = _currentQuat();
    // 前回受理からの経過時間で MSB 欠落判定の許容幅を伸ばす (読み失敗が続いたときの誤棄却防止)
    const uint32_t nowMsTol = millis();
    const uint32_t sinceAccept = _validator.lastAcceptMs() ? (nowMsTol - _validator.lastAcceptMs()) : 10;
    const int partialTol = bno055::partialToleranceLsb(sinceAccept);
    const uint32_t tQuat0 = micros();
    const bool readOk = _reader.readQuat(raw, qRaw, prevQ, _wordRead, partialTol, _cnt, straddles);
    _lastQuatReadUs = micros() - tQuat0;   // quat 読み (4 ワード + w 再読み) だけの実時間
    if (!readOk) {
        _cnt.readFails++;
        _slots.readFail.offer(raw);   // 生バイトを退避 (ログは loop 側 takeDiagReadFail)
    }
    _cnt.readTotal++;

    // 2) 判定: ノルム窓 → 正規化 → 連続性ガード → 10 連続棄却で強制受理 (AttitudeValidator)。
    //    読めなかった周期は前回値を「再受理」しない (seq は進まない)。
    const AttitudeVerdict v = _validator.evaluate(qRaw, readOk, prevQ, _gyroDegSum(), aux, now);
    if (v.ok) {
        _publishAccepted(v.q);
    } else if (readOk) {   // 読み失敗は fail に数えるので disc とは分ける
        _cnt.discards++;
        _slots.discard.offer(raw, v.n2);
    }

    // 3) 生サンプルダンプ (imu_dump): 判定結果まで含めて記録
    _dump.record(raw, (uint8_t)((readOk ? RawDumpRing::kFlagReadOk : 0) |
                                (v.ok ? RawDumpRing::kFlagAccepted : 0) |
                                (v.forced ? RawDumpRing::kFlagForced : 0)),
                 straddles, (uint32_t)now);

    // 4) 補助データ、5) ウォッチドッグ
    _readAuxIfDue(aux);
    _serviceWatchdog(now);
    return true;
}

Quat IMUManager::_currentQuat() const {
    // IMU タスクが唯一の書き手なので、タスク内の読みは排他不要
    return Quat{(float)_quat.w(), (float)_quat.x(), (float)_quat.y(), (float)_quat.z()};
}

float IMUManager::_gyroDegSum() const {
    return fabsf((float)_gyro.x()) + fabsf((float)_gyro.y()) + fabsf((float)_gyro.z());
}

void IMUManager::_applyPendingClock() {
    // I2C クロック変更要求 (MQTT led {"imu_i2c_khz"}) はトランザクションの隙間で
    // IMU タスク自身が適用する (他コアから setClock を叩いて読みと衝突させない)。
    if (!_i2cHzPending) return;
    const uint32_t hz = _i2cHzPending;
    _i2cHzPending = 0;
    _reader.setClock(hz);
    _i2cHz = hz;
    _slots.clockChanged.raise();   // ログは loop 側 (takeDiagClockChanged) で出す
}

bool IMUManager::_reinitAndResync(bool isAuto) {
    bool ok;
    {
        I2cGuard guard(_i2c);
        ok = _reinitSensor();
    }
    // リセット後は融合が起点から始まるので姿勢が不連続になる。連続性ガードが新しい姿勢を
    // 「化け」と誤判定して止まらないよう次のサンプルを即受理させ、旧姿勢を平均に混ぜない。
    _validator.forceNextAccept();
    _smoother.reset();
    _slots.reset.offer(ok, isAuto);
    return ok;
}

void IMUManager::_publishAccepted(const Quat& q) {
    // 移動平均はリング操作 + 最大 50 要素の加算なのでクリティカルセクションの外で計算する
    // (taskENTER_CRITICAL は割り込みを止めるため短く保つ)。リングは IMU タスク専用。
    const Quat out = _smoother.push(q);
    // render タスク (core1) が読む最中の引き裂かれ (torn read) を防ぐ
    taskENTER_CRITICAL(&_quatMux);
    _quat = imu::Quaternion(q.w, q.x, q.y, q.z);            // 生値: ガードの基準
    _quatOut = imu::Quaternion(out.w, out.x, out.y, out.z); // 平滑値: getQuaternion() が返す
    _quatSeq++;
    taskEXIT_CRITICAL(&_quatMux);
}

void IMUManager::_readAuxIfDue(bool aux) {
    // 補助データ (aux ON のときだけ)。1 周期に読むベクタは最大 1 本、2 周期に 1 本にして
    // I2C 時間を 10ms に収める (2B トランザクション 1 本 ~1.4ms: Wire のオーバーヘッド +
    // BNO055 のクロックストレッチ)。accel/gyro は 25Hz、euler は 10Hz。gyro は連続性ガードの
    // しきい値と凍結監視にしか使わないので十分。
    //   サブサイクル 2,6: gyro   4,8: accel   10: euler   (奇数: quat のみ)
    _auxCycle++;
    if (aux && (_auxCycle & 1) == 0) {
        imu::Vector<3> vec;
        if (_auxCycle >= 10) {
            if (_reader.readVector6(0x1A, 1.0f / 16.0f, vec, _wordRead, _slots.vecPartial)) {
                // _euler は loop タスク (GestureManager) が読むので排他して差し替える
                taskENTER_CRITICAL(&_quatMux);
                _euler = vec;
                taskEXIT_CRITICAL(&_quatMux);
            }
        } else if ((_auxCycle & 2) == 0) {           // 4, 8
            if (_reader.readVector6(0x08, 1.0f / 100.0f, vec, _wordRead, _slots.vecPartial)) {
                taskENTER_CRITICAL(&_quatMux);
                _accel = vec;
                taskEXIT_CRITICAL(&_quatMux);
            }
        } else {                                     // 2, 6
            if (_reader.readVector6(0x14, 1.0f / 16.0f, vec, _wordRead, _slots.vecPartial)) {
                taskENTER_CRITICAL(&_quatMux);
                _gyro = vec;
                taskEXIT_CRITICAL(&_quatMux);
            }
        }
    }
    if (_auxCycle >= 10) _auxCycle = 0;
}

void IMUManager::_serviceWatchdog(unsigned long now) {
    if (!_wdTimer.due((uint32_t)now)) return;
    // 持続的な読み化け状態の自動復旧 (2026-09-09 実測: 静止中に読みの 85% が
    // 「w 符号反転 + 1 成分の MSB 0xFF」で棄却され続け、OTA のソフト再起動では直らず
    // 電源再投入で解消した。その後 imu_reset (= _reinitSensor) が副作用なく通ることを
    // 確認済み)。健全なストリームは disc≈0 なので、2 秒窓で棄却率 50% 超が 2 窓続いたら
    // 再初期化する。以前の fusionDead 復旧が thrashing で無効化された教訓から、間隔は 15 秒以上。
    const uint32_t dr = _cnt.readTotal - _wdPrevReads;
    const uint32_t dd = _cnt.discards  - _wdPrevDisc;
    _wdPrevReads = _cnt.readTotal; _wdPrevDisc = _cnt.discards;
    const bool badStream = (dr >= 50) && (dd * 2 >= dr);   // 棄却率 ≥ 50%
    _wdBadWindows = badStream ? (uint8_t)(_wdBadWindows + 1) : 0;
    if (_wdBadWindows >= 2 && (now - _wdLastAutoResetMs) > 15000) {
        _wdLastAutoResetMs = now;
        _wdBadWindows = 0;
        _reinitAndResync(true);
    }
}

bool IMUManager::_reinitSensor() {
    // 手動 (imu_reset) / 自動 (棄却率監視) の両方から呼ばれる。begin() は SYS_TRIGGER で
    // チップリセットし chip ID を確認する。begin() は NDOF にするので CONFIG 経由で
    // IMUPLUS へ戻す (直接切替は BNO055 が無視する)。
    if (!_bno.begin()) {
        return false;
    }
    delay(50);
    _bno.setExtCrystalUse(false);   // 外部水晶なし (begin() のコメント参照)
    _bno.setMode(OPERATION_MODE_CONFIG);
    delay(25);
    _bno.setMode(OPERATION_MODE_IMUPLUS);
    delay(20);
    return true;
}
void IMUManager::_recoverI2cBus(uint8_t sda, uint8_t scl) {
    // 標準的な I2C バス回復: SDA を入力にして SCL を 9 回叩き、スレーブが途中まで
    // 出していたバイトを吐かせてから STOP (SCL=H で SDA L→H) を打つ。
    // バスが正常なら START の無いクロックはスレーブに無視されるので副作用は無い。
    pinMode(sda, INPUT_PULLUP);
    pinMode(scl, INPUT_PULLUP);
    delayMicroseconds(10);
    const int sdaBefore = digitalRead(sda);
    const int sclBefore = digitalRead(scl);

    pinMode(scl, OUTPUT_OPEN_DRAIN);
    digitalWrite(scl, HIGH);
    for (int i = 0; i < 9; i++) {
        digitalWrite(scl, LOW);  delayMicroseconds(5);
        digitalWrite(scl, HIGH); delayMicroseconds(5);
    }
    // STOP: SCL=H のまま SDA を L→H
    pinMode(sda, OUTPUT_OPEN_DRAIN);
    digitalWrite(sda, LOW);  delayMicroseconds(5);
    digitalWrite(sda, HIGH); delayMicroseconds(5);
    pinMode(sda, INPUT_PULLUP);
    pinMode(scl, INPUT_PULLUP);
    delayMicroseconds(10);

    Serial.printf("[IMU] I2C bus recover: before SDA=%d SCL=%d -> after SDA=%d SCL=%d%s\n",
                  sdaBefore, sclBefore, digitalRead(sda), digitalRead(scl),
                  sdaBefore == LOW ? "  (bus was STUCK)" : "");
}
void IMUManager::displayCalibrationStatus() {
    if (!_initialized) {
        Serial.println("IMU not initialized!");
        return;
    }

    uint8_t system, gyro, accel, mag = 0;
    {
        I2cGuard guard(_i2c);
        _bno.getCalibration(&system, &gyro, &accel, &mag);
    }

    Serial.println("\n=== Calibration Status ===");
    Serial.print("System: "); Serial.print(system, DEC);
    Serial.print(" Gyro: "); Serial.print(gyro, DEC);
    Serial.print(" Accel: "); Serial.print(accel, DEC);
    Serial.print(" Mag: "); Serial.println(mag, DEC);
    Serial.println("(0=uncalibrated, 3=fully calibrated)");
    Serial.println("==========================");
}

void IMUManager::getCalibration(uint8_t& sys, uint8_t& gyro, uint8_t& accel, uint8_t& mag) {
    if (_initialized) {
        I2cGuard guard(_i2c);   // loop タスクから呼ばれる: IMUタスクと排他する
        _bno.getCalibration(&sys, &gyro, &accel, &mag);
    } else {
        sys = gyro = accel = mag = 0;
    }
}

int8_t IMUManager::getTemperature() {
    if (!_initialized) {
        return 0;
    }
    I2cGuard guard(_i2c);
    return _bno.getTemp();
}


uint8_t IMUManager::getOperationMode() {
    if (!_initialized) return 0xFE;
    I2cGuard guard(_i2c);   // IMUタスクの読み出しシーケンスに割り込まない
    return (uint8_t)_bno.getMode();
}

} // namespace sastle

