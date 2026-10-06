/**
 * @note 派生元 sastle-isolation-sphere の feat/ui-v2 (a2a2531) から移植。IMU ジャンプの原因と
 *       対策の経緯は同リポジトリ docs/HANDOFF_2026-09-09_imu_jump.md。solo 側では MQTT 結合を
 *       外し、診断は /api/imu と [RATE]/[IMU] ログで見る。
 * @file IMUManager.h
 * @brief IMUセンサー管理クラス (外部 BNO055)
 * @author sastle-com
 * @date 2025-12-01
 *
 * 公開 API (getQuaternion/getEuler/getAccel/getGyro) の戻り値型 imu::Quaternion / imu::Vector<3> は
 * imumaths.h (ヘッダオンリ)。
 */

#pragma once

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <utility/imumaths.h>
#include "ConfigManager.h"
#include "BoardConfig.h"
#include "imu/Quat.h"
#include "imu/QuatSmoother.h"
#include "imu/Bno055Codec.h"
#include "imu/AttitudeValidator.h"
#include "imu/ImuDiag.h"
#include "imu/I2cLock.h"
#include "imu/Bno055QuatReader.h"
#include "PeriodicTimer.h"

#include <Adafruit_BNO055.h>

namespace sastle {

/**
 * @class IMUManager
 * @brief IMUセンサーを管理するクラス
 *
 * クォータニオン、オイラー角、加速度、ジャイロデータの取得機能を提供します。
 * 100Hzでの高速データ更新に対応しています。
 * BNO055 のオンチップ融合 (IMUPLUS: 加速度+ジャイロ、磁気不使用) で姿勢を推定します。
 */
class IMUManager {
public:
    IMUManager();
    ~IMUManager();
    
    /**
     * @brief IMUセンサーを初期化
     * @param config 設定マネージャー参照
     * @param sda I2C SDAピン番号 (デフォルト: kImuI2cSda)
     * @param scl I2C SCLピン番号 (デフォルト: kImuI2cScl)
     * @return true 初期化成功, false 初期化失敗
     */
    bool begin(ConfigManager& config, uint8_t sda = kImuI2cSda, uint8_t scl = kImuI2cScl);
    
    /**
     * @brief センサーデータを更新
     * @return true 更新成功, false 更新失敗
     * @note 100Hz (10ms間隔) で呼び出すことを推奨
     */
    bool update();
    
    
    /**
     * @brief クォータニオンを個別変数で取得
     * @param w クォータニオンw成分 (出力)
     * @param x クォータニオンx成分 (出力)
     * @param y クォータニオンy成分 (出力)
     * @param z クォータニオンz成分 (出力)
     * @return true 取得成功, false 取得失敗
     */
    bool getQuaternion(float& w, float& x, float& y, float& z);
    
    /**
     * @brief オイラー角を取得
     * @return オイラー角ベクトル (heading, roll, pitch)
     */
    imu::Vector<3> getEuler();
    
    
    /**
     * @brief 加速度を取得
     * @return 加速度ベクトル (x, y, z) [m/s²]
     */
    imu::Vector<3> getAccel();
    
    /**
     * @brief 加速度を個別変数で取得
     * @param x X軸加速度 [m/s²] (出力)
     * @param y Y軸加速度 [m/s²] (出力)
     * @param z Z軸加速度 [m/s²] (出力)
     * @return true 取得成功, false 取得失敗
     */
    bool getAccel(float& x, float& y, float& z);
    
    
    /**
     * @brief ジャイロデータを個別変数で取得
     * @param x X軸角速度 [deg/s] (出力)
     * @param y Y軸角速度 [deg/s] (出力)
     * @param z Z軸角速度 [deg/s] (出力)
     * @return true 取得成功, false 取得失敗
     * @note deg/s で格納している。
     */
    bool getGyro(float& x, float& y, float& z);
    
    /**
     * @brief キャリブレーション状態を表示
     */
    void displayCalibrationStatus();
    
    
    /**
     * @brief キャリブレーション状態を個別取得
     * @param sys システムキャリブレーション値 (0-3) (出力)
     * @param gyro ジャイロキャリブレーション値 (0-3) (出力)
     * @param accel 加速度計キャリブレーション値 (0-3) (出力)
     * @param mag 磁気計キャリブレーション値 (0-3) (出力)
     */
    void getCalibration(uint8_t& sys, uint8_t& gyro, uint8_t& accel, uint8_t& mag);

    /**
     * @brief 現在の動作モードレジスタ値 (BNO055: 8=IMUPLUS, 12=NDOF)
     */
    uint8_t getOperationMode();
    
    /**
     * @brief IMUステータスを表示
     */
    void printStatus();
    
    /**
     * @brief 初期化状態を取得
     * @return true 初期化済み, false 未初期化
     */
    bool isInitialized() { return _initialized; }

    /**
     * @brief 専用タスクで IMU をポーリングする (推奨)
     *
     * Arduino の loop() から update() を呼ぶ方式では、同じ core1 で動く
     * LED レンダリングタスク (優先度2) に押されて実効 43Hz まで落ち、かつ
     * サンプル間隔が 1ms〜22ms とばらついていた。描画は毎フレーム「最新の」
     * quat を読むため、間隔のばらつきがそのまま「同じ姿勢を保持 → 突然2ステップ
     * 分ジャンプ」というカクつきになる。専用タスク + vTaskDelayUntil で
     * 位相ゆらぎのない固定周期にすることが滑らかさの本質的な条件。
     *
     * @param core     実行コア (LEDレンダリングと分けるため 0 を推奨)
     * @param priority 優先度 (デコードタスク=1 より高い 3 を推奨)
     * @param stackSize スタックサイズ [byte]
     * @return true 起動成功
     */
    bool startTask(uint8_t core = 0, uint8_t priority = 3, uint32_t stackSize = 4096);

    /// 専用タスクのハンドル (スタック残量の監視用。未起動なら nullptr)
    TaskHandle_t taskHandle() const { return _taskHandle; }

    // 計装用カウンタ (main の周期ログでレート計算に使う)
    uint32_t debugReadTotal() const { return _cnt.readTotal; }
    uint32_t debugReadFails() const { return _cnt.readFails; }
    uint32_t debugDiscards()  const { return _cnt.discards; }
    uint32_t debugZeroReads() const { return _cnt.zeroReads; }
    /// 「末尾バイトだけゼロ」の部分読み (I2Cは成功を返す) を検出して再試行した回数
    uint32_t debugPartialReads() const { return _cnt.partialReads; }
    /// 4 ワード読みの途中で融合更新をまたいだ (w の再読みが不一致) と判定して読み直した回数
    uint32_t debugStraddles() const { return _cnt.straddles; }

    /// 診断: 1 周期の内訳 [us]。update = _updateOnce() の実時間、cycle = 起床間隔。
    /// 40/s しか出ない原因が I2C 待ち (update が長い) かスケジューリング (cycle だけ長い) かを切り分ける。
    uint32_t debugUpdateUsAvg() const { return _updSamples ? (uint32_t)(_updUsSum / _updSamples) : 0; }
    uint32_t debugUpdateUsMax() const { return _updUsMax; }
    uint32_t debugCycleUsAvg() const { return _updSamples ? (uint32_t)(_cycleUsSum / _updSamples) : 0; }
    uint32_t debugQuatUsAvg()  const { return _updSamples ? (uint32_t)(_quatUsSum / _updSamples) : 0; }
    uint32_t debugTimingSamples() const { return _updSamples; }
    bool debugTaskRunning() const { return _taskRunning && _taskHandle != nullptr; }
    void debugResetTiming() { _updUsSum = _cycleUsSum = _quatUsSum = 0; _updSamples = 0; _updUsMax = 0; }
    void debugAddTiming(uint32_t updUs, uint32_t cycleUs, uint32_t quatUs) {
        _updUsSum += updUs; _cycleUsSum += cycleUs; _quatUsSum += quatUs; _updSamples++;
        if (updUs > _updUsMax) _updUsMax = updUs;
    }
    /// 受理された姿勢更新の通番。描画側が「前回と同じ姿勢か」を判定できる。
    uint32_t quatSeq() const { return _quatSeq; }

    /**
     * @brief 補助データ (gyro/euler/accel) の I2C 読み出しを ON/OFF する
     *
     * OFF にすると毎サイクル quat 8 バイトだけを読む (トランザクション最短)。
     * 部分ゼロ読みの発生率がトランザクション長に依存するかを実機で切り分ける
     * ための実験スイッチ。OFF 中は gyro/euler/accel は最後の値のまま止まり、
     * 姿勢ジャンプ判定のしきい値は想定最大角速度ベースのフォールバックになる。
     * MQTT: sphere/<id>/command/led {"imu_aux": false}
     */
    void setAuxReads(bool on) { _auxReads = on; }
    bool auxReads() const { return _auxReads; }

    /**
     * @brief I2C クロックを実行時に変更する (次の IMU タスク周期で適用)
     *
     * 配線が限界的だと 400kHz で「w だけ有効で残りが化ける」症状が出た実績があり
     * (begin() のコメント参照)、100kHz でも回転中に同じ症状が出る個体 (sphere002)
     * があるため、50kHz 等に落として改善するかを実機で試すためのスイッチ。
     * MQTT: sphere/<id>/command/led {"imu_i2c_khz": 50}
     */
    void setI2cClock(uint32_t hz) { _i2cHzPending = hz; }
    uint32_t i2cClock() const { return _i2cHz; }

    /**
     * @brief quat を 8 バイト一括ではなく 2 バイト×4 トランザクションで読む
     *
     * sphere002 で「8 バイト読みの 3 バイト目以降が 0xFF」が静止中も 100% 出た
     * (2026-09-06)。スレーブが多バイト転送の途中で応答を止めている挙動なので、
     * 1 トランザクションを 2 バイトに縮めれば読めるかを試す実験スイッチ。
     * MQTT: sphere/<id>/command/led {"imu_wordread": true}
     */
    void setWordRead(bool on) { _wordRead = on; }
    bool wordRead() const { return _wordRead; }

    /**
     * @brief 姿勢の移動平均フレーム数を設定する (1 = 平滑なし、上限 kSmoothMax=50)
     *
     * 「特定の角度で姿勢が飛ぶ」現象の暫定対策。直近 N サンプルのクォータニオンを
     * 平均して出力する (getQuaternion が返す値だけを平滑化し、化け値ガードや
     * 凍結ウォッチドッグが参照する生値 _quat はそのまま保つ)。
     *
     * 平均前に符号を揃えることが必須: q と -q は同じ回転だが、BNO055 は姿勢が
     * w=0 の面を通過するとき符号を反転して返すことがあり、そのまま足すと
     * 打ち消し合って平均のノルムが 0 付近まで落ち、正規化で姿勢が暴れる。
     *
     * MQTT: sphere/<id>/command/led {"imu_smooth": 5}
     * 起動時の既定値は config.json の imu.smooth_frames。
     */
    void setSmoothFrames(uint8_t n);
    uint8_t smoothFrames() const { return _smoother.window(); }

    /// 移動平均の上限フレーム数 (WebUI のスライダー上限と揃える)
    static constexpr uint8_t kSmoothMax = QuatSmoother::kMax;

    /**
     * @brief BNO055 の再初期化を要求する (次の IMU タスク周期で実行)
     *
     * 2026-09-09 実測: 静止中に 85% のサンプルが化ける (w の符号反転 + 1 成分の
     * MSB が 0xFF) 状態に入り、OTA のソフト再起動では直らず電源再投入で解消した。
     * 電源を切らずに戻せるかを検証し、戻せるなら WebUI から叩ける復旧手段にする。
     * MQTT: sphere/<id>/command/led {"imu_reset": true}
     */
    void requestReset() { _resetPending = true; }

    /**
     * @brief 生サンプルダンプ: 次の n サンプル (100Hz) の生 8B + 判定を記録する
     *
     * ジャンプの原因切り分け用。IMU タスクが 1 サンプル 12B (raw8 + flags + straddles
     * + dt_ms) を PSRAM に溜め、完了後に loop 側が takeRawDumpLine() で hex 行として
     * MQTT ログへ吐き出す ([DUMP] <idx0> <hex>)。flags: bit0=readOk bit1=accepted bit2=forced
     * MQTT: sphere/<id>/command/led {"imu_dump": 500}
     */
    bool startRawDump(uint16_t n);
    /// 完了したダンプを 1 行ぶん hex 化して取り出す (無ければ false)
    bool takeRawDumpLine(char* out, size_t cap, uint16_t& idx0);

    // --- 診断スナップショット (IMU タスクが書き、loop タスクが取り出して MQTT へ) ---
    // sastle::Log は単一行バッファ + 同期 publish で排他が無いため、IMU タスク
    // (core0) から呼ぶと loop (core1) の出力と混ざり、PubSubClient が詰まって
    // core0 が十数秒停止した (2026-09-06 実測: imu_read=0/s の窓)。IMU タスク側は
    // 生バイトを置くだけにし、ログ出力は必ず loop 側 (main.cpp の周期ログ) で行う。
    bool takeDiagReadFail(uint8_t out[8]);              ///< 直近の読み失敗 (生 8B)
    bool takeDiagDiscard(uint8_t out[8], float& n2);    ///< 直近の棄却 quat (生 8B + ノルム²)
    bool takeDiagVecPartial(uint8_t& reg, uint8_t out[6]); ///< 直近の補助データ部分読み
    bool takeDiagClockChanged(uint32_t& hz);            ///< I2C クロック変更が適用された
    bool takeDiagReset(bool& ok, bool& auto_);          ///< 再初期化が実行された (結果, 自動か)
    
    /**
     * @brief センサー温度を取得
     * @return 温度 (℃)
     */
    int8_t getTemperature();
    
private:
    bool _initialized;             ///< 初期化状態フラグ

    imu::Quaternion _quat;         ///< 最新クォータニオン
    imu::Quaternion _quatOut;      ///< 平滑後の出力 (getQuaternion が返す値)
    QuatSmoother _smoother;        ///< 符号合わせ付き移動平均 (imu/QuatSmoother.h、IMU タスク専用)
    AttitudeValidator _validator;  ///< ノルム窓 + 連続性ガード + 強制受理 (imu/AttitudeValidator.h)
    imu::Vector<3> _euler;         ///< 最新オイラー角 (x=heading, y=roll, z=pitch)
    imu::Vector<3> _accel;         ///< 最新加速度 [m/s²]
    imu::Vector<3> _gyro;          ///< 最新ジャイロ [deg/s]

    unsigned long _lastUpdate;     ///< 最終更新時刻 (ms)
    const unsigned long UPDATE_INTERVAL = 10; ///< 更新間隔 10ms = 100Hz

    // 2 秒周期ウォッチドッグ (_serviceWatchdog): 棄却率 50% 超が 2 窓続いたら自動再初期化
    PeriodicTimer _wdTimer{2000};         ///< ウォッチドッグの 2 秒ゲート
    uint32_t _wdPrevReads = 0;            ///< 前回窓時点の readTotal
    uint32_t _wdPrevDisc = 0;             ///< 前回窓時点の discards
    uint8_t  _wdBadWindows = 0;           ///< 棄却率 50% 超が続いた窓数
    unsigned long _wdLastAutoResetMs = 0; ///< 最後の自動再初期化時刻 (クールダウン 15 秒)
    uint8_t _auxCycle = 0;                ///< 補助データ読みのサブサイクル (1..10)
    portMUX_TYPE _quatMux = portMUX_INITIALIZER_UNLOCKED; ///< _quat のコア間排他
    ImuCounters _cnt;              ///< 累計カウンタ (imu/ImuDiag.h。IMU タスクが ++、loop が読む)
    volatile bool _auxReads = true;///< gyro/euler/accel も読むか (false = quat 8B のみ)
    // 既定 ON: sphere002 で「起動 ~1 分後から 3 バイト以上の連続転送が 0xFF 化」を実測、
    // 2B 転送は同時刻でも 100% 成功した (2026-09-06)。OFF は比較実験用。
    volatile bool _wordRead = true;  ///< quat/補助データを 2B 単位のトランザクションで読む
    uint32_t _i2cHz = 100000;      ///< 現在の I2C クロック [Hz]
    // 診断スナップショット (フラグは volatile、配列は診断用途なので torn read 許容)
    ImuDiagSlots _slots;           ///< 直近 1 件のスナップショット (IMU タスク offer → loop take)
    volatile uint32_t _i2cHzPending = 0; ///< 変更要求 (0 = なし)。IMU タスクが適用する
    volatile bool _resetPending = false; ///< 再初期化要求。IMU タスクが実行する
    // 生サンプルダンプ (IMU タスクが書き、完了後に loop が読む)
    RawDumpRing _dump;             ///< imu_dump のリング (imu/ImuDiag.h)。バッファは下を借りる
    uint8_t* _dumpBuf = nullptr;   ///< loop 側で ps_malloc/free する (IMU タスクは armed 中だけ書く)
    volatile uint32_t _quatSeq = 0;///< 姿勢を受理するたびに +1 (描画側の鮮度判定用)
    // 周期の内訳計測 (IMU タスクが加算、loop/httpd が読む。多少のズレは許容)
    volatile uint64_t _updUsSum = 0, _cycleUsSum = 0, _quatUsSum = 0;
    volatile uint32_t _updSamples = 0, _updUsMax = 0;
    volatile uint32_t _lastQuatReadUs = 0;  ///< 直近の quat 読みの実時間 [us]
    TaskHandle_t _taskHandle = nullptr; ///< 専用ポーリングタスク
    volatile bool _taskRunning = false;
    static void taskFunction(void* parameter); ///< 固定周期ポーリングループ
    bool _updateOnce();            ///< 時間ゲートなしの1回分の取得 (タスクから呼ぶ)
    // --- _updateOnce の各フェーズ (すべて IMU タスクから呼ぶ) ---
    void _applyPendingClock();                 ///< imu_i2c_khz の適用
    bool _reinitAndResync(bool isAuto);        ///< センサー再初期化 + 平滑/ガードの再同期
    void _publishAccepted(const Quat& q);      ///< 平滑して _quat/_quatOut/_quatSeq を公開
    void _readAuxIfDue(bool aux);              ///< accel/gyro/euler を周期分散して読む
    void _serviceWatchdog(unsigned long now);  ///< 2 秒ごと: 棄却率監視 → 自動再初期化
    Quat _currentQuat() const;                 ///< _quat の float コピー (IMU タスク内、排他不要)
    float _gyroDegSum() const;                 ///< |gx|+|gy|+|gz| [deg/s] (ガードのしきい値用)
    /// BNO055 をリセットして IMUPLUS まで再設定する (I2C ロック下で呼ぶ)
    bool _reinitSensor();
    /// Wire.begin 前に SCL を手動で叩いてスレーブの途中転送を流す (バス回復)
    static void _recoverI2cBus(uint8_t sda, uint8_t scl);

    // I2C バスの排他は imu/I2cLock.h (再帰ミューテックス + RAII ガード)。IMU タスクの読みと
    // loop タスクの診断 getter が同じ Wire を使うため、複数トランザクションの並びを 1 単位で守る。
    I2cLock _i2c;
    Bno055QuatReader _reader;      ///< BNO055 のレジスタ読み (分割読み・MSB 欠落・straddle 検出)

    Adafruit_BNO055 _bno;          ///< BNO055センサーオブジェクト
};

} // namespace sastle
