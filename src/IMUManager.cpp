#include "IMUManager.h"
#include <Arduino.h>
#include "Log.h"

namespace sastle {

// バックエンド共通部: 公開 getter、ポーリングタスク、診断スナップショットの受け渡し、
// imu_dump、平滑窓の設定。BNO055 固有は IMUManager_bno055.cpp。

IMUManager::~IMUManager() {
}

bool IMUManager::takeDiagReadFail(uint8_t out[8])            { return _slots.readFail.take(out); }
bool IMUManager::takeDiagDiscard(uint8_t out[8], float& n2)  { return _slots.discard.take(out, n2); }
bool IMUManager::takeDiagVecPartial(uint8_t& reg, uint8_t out[6]) { return _slots.vecPartial.take(reg, out); }
bool IMUManager::takeDiagReset(bool& ok, bool& auto_)        { return _slots.reset.take(ok, auto_); }
bool IMUManager::takeDiagClockChanged(uint32_t& hz) {
    if (!_slots.clockChanged.take()) return false;
    hz = _i2cHz;
    return true;
}
void IMUManager::taskFunction(void* parameter) {
    IMUManager* self = static_cast<IMUManager*>(parameter);
    Serial.printf("[IMU_Task] Started on core %d (%lu Hz)\n",
                  xPortGetCoreID(), 1000UL / self->UPDATE_INTERVAL);

    // vTaskDelayUntil で「前回起床時刻 + 10ms」に固定する。vTaskDelay(10) だと
    // 処理時間ぶん周期が伸びて位相がずれていくため、姿勢サンプル間隔を一定に
    // 保つにはこちらが必須。
    TickType_t lastWake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(self->UPDATE_INTERVAL);
    uint32_t prevWakeUs = micros();
    while (true) {
        const uint32_t tStart = micros();
        self->_updateOnce();
        const uint32_t tEnd = micros();
        self->debugAddTiming(tEnd - tStart, tStart - prevWakeUs, self->_lastQuatReadUs);
        prevWakeUs = tStart;
        // 周期を超過した場合 (I2C クロックを落とした / リトライが重なった) の保護。
        // vTaskDelayUntil は期限を過ぎていると即座に返るため、超過が続くと優先度 3 の
        // このタスクが core1 を独占し、同コアの loop (MQTT/OTA) と描画が飢餓する
        // (2026-09-09 実測: imu_i2c_khz=10 で MQTT が完全停止し、WiFi の ping だけ
        // 通る状態になり電源再投入が必要になった)。超過時は 1 tick 必ず譲り、
        // 位相を現在時刻に再同期する (遅れを取り戻そうとして連続実行しない)。
        // 実測 (2026-09-09): 1 周期の実時間はトランザクション数を減らしても ~10ms で
        // 変わらない = BNO055 が 100Hz の融合更新境界までクロックストレッチして
        // 読みを待たせている (センサー側がペースを決めている)。そのため「1 周期ぶん
        // 遅れたら譲る」だと毎周期 1 tick 譲ってしまい 90Hz に落ちた (1000/11ms)。
        // 譲るのは 2 周期以上遅れた慢性的な超過 (I2C クロックを落とした等) のときだけ
        // にし、lastWake は vTaskDelayUntil に period ずつ進めさせて追いつきを保つ。
        // 遅れが 5 周期を超えたら位相を捨てて再同期する。
        const TickType_t now = xTaskGetTickCount();
        const TickType_t late = now - lastWake;
        if (late >= 2 * period) {
            if (late >= 5 * period) lastWake = now - period;
            vTaskDelay(1);
        }
        vTaskDelayUntil(&lastWake, period);
    }
}
bool IMUManager::startTask(uint8_t core, uint8_t priority, uint32_t stackSize) {
    if (!_initialized) {
        Serial.println("[IMU_Task] Not initialized");
        return false;
    }
    if (_taskRunning) {
        return true;
    }
    // 先に立ててから生成する: タスクが動き出した直後に loop 側の update() が
    // 割り込んで I2C を触るのを防ぐ。
    _taskRunning = true;
    if (xTaskCreatePinnedToCore(taskFunction, "IMU_Poll", stackSize, this,
                                priority, &_taskHandle, core) != pdPASS) {
        _taskRunning = false;
        _taskHandle = nullptr;
        Serial.println("[IMU_Task] Failed to create task");
        return false;
    }
    return true;
}


bool IMUManager::startRawDump(uint16_t n) {
    if (_dump.armed()) return false;       // 記録中 (書き手が居る間はバッファを差し替えない)
    if (n < 10) n = 10;
    if (n > 2000) n = 2000;
    if (_dumpBuf) { _dump.disarm(); free(_dumpBuf); _dumpBuf = nullptr; }   // 前回の未回収分は捨てる
    const size_t bytes = (size_t)n * RawDumpRing::kRec;
    _dumpBuf = (uint8_t*)ps_malloc(bytes);
    if (!_dumpBuf) _dumpBuf = (uint8_t*)malloc(bytes);
    if (!_dumpBuf) return false;
    if (!_dump.arm(_dumpBuf, n)) { free(_dumpBuf); _dumpBuf = nullptr; return false; }
    return true;
}

bool IMUManager::takeRawDumpLine(char* out, size_t cap, uint16_t& idx0) {
    // RemoteLog の 1 行は 240 文字。RawDumpRing は 8 サンプル (192 hex) ずつ返す。
    if (_dump.exhausted()) {               // 出し終わり: バッファを解放してリングを手放す
        _dump.disarm();
        free(_dumpBuf); _dumpBuf = nullptr;
        return false;
    }
    return _dump.takeLine(out, cap, idx0);
}

void IMUManager::setSmoothFrames(uint8_t n) {
    // 実体は imu/QuatSmoother.h。窓の拡大・縮小は次のサンプルから即座に効く。
    _smoother.setWindow(n);
}

bool IMUManager::getQuaternion(float& w, float& x, float& y, float& z) {
    if (!_initialized) {
        return false;
    }

    // センサー→LED座標系の変換: BNO055 の quaternion は本システムの規約と
    // 回転の向きが逆 (実機テスト 2026-08-23: 生値では X/Y/Z 全軸で補正方向が逆)。
    // 完全共役 q → q* = (w,-x,-y,-z) で逆回転に変換する。
    // ここで変換することで LED描画・MQTT配信(ツイン)・ジェスチャすべてに
    // 一括適用される。読み出しはコア間排他の下でコピーする (torn read防止)。
    taskENTER_CRITICAL(&_quatMux);
    const float qw = (float)_quatOut.w(), qx = (float)_quatOut.x(),
                qy = (float)_quatOut.y(), qz = (float)_quatOut.z();
    taskEXIT_CRITICAL(&_quatMux);
    w = qw;
    x = -qx;
    y = -qy;
    z = -qz;

    return true;
}

// _euler は IMU タスク (core0) が書き、GestureManager は loop (core1) から読む。
// imu::Vector<3> は double×3 = 24byte でアトミックに読めないため、ジェスチャー
// 判定が引き裂かれた値 (別サンプルの成分の混合) を見ないよう排他する。
imu::Vector<3> IMUManager::getEuler() {
    taskENTER_CRITICAL(&_quatMux);
    const imu::Vector<3> e = _euler;
    taskEXIT_CRITICAL(&_quatMux);
    return e;
}

// _accel/_gyro も IMU タスク (core0) が書き loop (core1) が読むので排他する。
// これらは I2C を触らない (キャッシュ済みの値を返すだけ)。
imu::Vector<3> IMUManager::getAccel() {
    taskENTER_CRITICAL(&_quatMux);
    const imu::Vector<3> a = _accel;
    taskEXIT_CRITICAL(&_quatMux);
    return a;
}

bool IMUManager::getAccel(float& x, float& y, float& z) {
    if (!_initialized) {
        return false;
    }

    taskENTER_CRITICAL(&_quatMux);
    const float ax = (float)_accel.x(), ay = (float)_accel.y(), az = (float)_accel.z();
    taskEXIT_CRITICAL(&_quatMux);

    x = ax;
    y = ay;
    z = az;

    return true;
}

bool IMUManager::getGyro(float& x, float& y, float& z) {
    if (!_initialized) {
        return false;
    }

    taskENTER_CRITICAL(&_quatMux);
    const float gx = (float)_gyro.x(), gy = (float)_gyro.y(), gz = (float)_gyro.z();
    taskEXIT_CRITICAL(&_quatMux);

    x = gx;
    y = gy;
    z = gz;

    return true;
}


void IMUManager::printStatus() {
    Serial.println("\n=== IMU Status ===");
    
    if (!_initialized) {
        Serial.println("Status: Not initialized");
        Serial.println("==================");
        return;
    }
    
    Serial.println("Status: Initialized");
    Serial.printf("Temperature: %d°C\n", getTemperature());
    
    // キャリブレーション状態
    uint8_t system, gyro, accel, mag = 0;
    getCalibration(system, gyro, accel, mag);
    Serial.printf("Calibration - Sys:%d Gyro:%d Accel:%d Mag:%d\n", 
                  system, gyro, accel, mag);
    
    // クォータニオン
    Serial.printf("Quaternion - w:%.3f x:%.3f y:%.3f z:%.3f\n",
                  _quat.w(), _quat.x(), _quat.y(), _quat.z());
    
    // オイラー角
    Serial.printf("Euler - Heading:%.2f° Roll:%.2f° Pitch:%.2f°\n",
                  _euler.x(), _euler.y(), _euler.z());
    
    Serial.println("==================");
}

} // namespace sastle
