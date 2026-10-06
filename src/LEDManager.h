/**
 * @file LEDManager.h
 * @brief LED制御マネージャー - デュアルコアレンダリング対応
 * 
 * ESP32-S3のデュアルコアを活用し、Core 1で800個のLEDへの描画を行います。
 * ImageManagerから画像データを取得し、3D座標からUV座標へ変換してLEDに出力します。
 */

#ifndef LED_MANAGER_H
#define LED_MANAGER_H

#include <Arduino.h>
#include "BoardConfig.h"   // kNumStrips (ストリップ配列サイズに使用)
#include "ConfigManager.h"
#include "ImageManager.h"
#include "IMUManager.h"
#include <FastLED.h>
#include "imu/AttitudeStepDiag.h"

namespace sastle {

/**
 * @brief LED座標構造体
 * 
 * LEDの3D空間座標を保持します。
 */
struct LEDCoord {
    uint16_t faceID;      ///< 面ID
    uint8_t strip;        ///< ストリップ番号 (0-3)
    uint16_t stripNum;    ///< ストリップ内インデックス
    float x;              ///< X座標 (正規化済み)
    float y;              ///< Y座標 (正規化済み)
    float z;              ///< Z座標 (正規化済み)
};

/**
 * @brief LED統計情報
 */
struct LEDStats {
    uint32_t frames_rendered;    ///< 描画フレーム数
    uint32_t frames_dropped;     ///< ドロップフレーム数
    float fps;                   ///< 描画FPS
    uint32_t render_time_us;     ///< 最後のレンダリング時間 (μs)
    uint32_t mapping_time_us;    ///< 座標マッピング時間 (μs)
    uint32_t output_time_us;     ///< LED出力時間 (μs)
    uint32_t imu_stale_frames;   ///< 前フレームと同じ姿勢で描いたフレーム数の累計
    float imu_ortho_err_max;     ///< 回転後3軸の直交誤差の最大 (0なら正規な回転)
    float imu_norm_err_max;      ///< 使用したquatの ||q|²-1| の最大
    float imu_step_deg_max;      ///< 1フレームあたり姿勢変化の最大 [deg]
};

/**
 * @brief LEDマネージャークラス
 * 
 * ESP32-S3のCore 1でLED描画タスクを実行します。
 * ImageManagerから画像データを取得し、LEDレイアウトに基づいて
 * 3D座標→UV座標変換を行い、WS2812BストリップへDMA出力します。
 * 
 * @note このクラスはCore 1で動作するタスクを管理します
 */
class LEDManager {
public:
    LEDManager();
    ~LEDManager();
    
    /**
     * @brief LEDマネージャーを初期化
     * 
     * @param config 設定マネージャー
     * @param imageManager 画像マネージャー
     * @param imuManager IMUマネージャー（姿勢補正用、nullptrで無効化）
     * @return 初期化成功時true
     */
    /**
     * @brief 起動直後の即時消灯。setup() の最初に呼ぶこと。
     *
     * WS2812 はデータ線がフロートする起動中にノイズを拾いランダム点灯
     * (白=フル電流もあり得る) し、begin() が走るのは WiFi 初期化後で数秒かかる。
     * その間の電流で電源が落ちる事象があるため、ゼロバッファで FastLED を
     * 即初期化して黒を送信する。begin() はコントローラのバッファを実バッファへ
     * 差し替えるだけにする (addLeds の二重登録を回避)。
     */
    static void earlyBlank();

    bool begin(ConfigManager& config, ImageManager& imageManager, IMUManager* imuManager = nullptr);
    
    /**
     * @brief レンダリングタスクを開始
     * 
     * @param core 実行するコア番号 (デフォルト: 1)
     * @param priority タスク優先度 (デフォルト: 2)
     * @param stackSize スタックサイズ (デフォルト: 8192)
     * @return タスク起動成功時true
     */
    bool startRenderTask(uint8_t core = 1, uint8_t priority = 2, uint32_t stackSize = 8192);
    
    /**
     * @brief レンダリングタスクを停止
     */
    void stopRenderTask();
    
    /**
     * @brief 初期化状態を取得
     * 
     * @return 初期化済みならtrue
     */
    bool isInitialized() const { return _initialized; }
    
    /**
     * @brief タスク実行状態を取得
     * 
     * @return タスク実行中ならtrue
     */
    bool isRunning() const { return _taskRunning; }
    
    /**
     * @brief 統計情報を取得
     * 
     * @return LED統計情報
     */
    LEDStats getStats() const { return _stats; }

    /// 姿勢診断のピーク値をクリアする (周期ログ [QDIAG] が読み出した直後に呼ぶ)
    void resetImuDiag() {
        _stats.imu_ortho_err_max = 0.0f;
        _stats.imu_norm_err_max = 0.0f;
        _stats.imu_step_deg_max = 0.0f;
    }

    /**
     * @brief 全LEDを指定色に設定
     * 
     * @param r 赤成分 (0-255)
     * @param g 緑成分 (0-255)
     * @param b 青成分 (0-255)
     */
    void fillSolid(uint8_t r, uint8_t g, uint8_t b);

    /**
     * @brief 単一LEDの色をバッファに書き込む
     *
     * @param index LED通し番号 (0起点。レイアウトCSVの並び = ストリップ連結順)
     * @param r 赤成分 (0-255)
     * @param g 緑成分 (0-255)
     * @param b 青成分 (0-255)
     * @return true 書き込み成功, false バッファ未確保または index 範囲外
     *
     * @note バッファのみ更新する。出力は描画タスクが行うため、書き込みを保持
     *       させるには setOutputMode(OutputMode::Manual) が必要
     *       (Sphere のままだと updateLEDBuffer() が毎フレーム上書きする)。
     */
    bool setPixel(uint16_t index, uint8_t r, uint8_t g, uint8_t b);

    /**
     * @brief LEDバッファの更新元
     */
    enum class OutputMode : uint8_t {
        Sphere,  ///< 画像+IMU から updateLEDBuffer() が生成 (既定)
        Manual,  ///< 外部が setPixel()/fillSolid() で直接書く (pixels/off モード)
        Test,    ///< updateTestBuffer() が strip index から自前生成 (点灯/配線確認)
    };

    /**
     * @brief 点灯確認用テストパターン
     *
     * IMU/画像を一切通さず strip index だけで生成する。各LEDの点灯有無と
     * チェイン順序・配線strip の確認が目的 (mode:"test" コマンドで選択)。
     */
    enum class TestPattern : uint8_t {
        StripId,  ///< 各ストリップを識別色でベタ塗り (配線strip同定・全点灯確認)
        Chase,    ///< 各ストリップを識別色の width 連LEDが DIN 側から移動 (順序/方向確認)
    };

    /**
     * @brief バッファ更新元を切り替える
     *
     * @note 描画タスクは停止させずに切り替える。stopRenderTask() による停止と
     *       startRenderTask() での再生成は、vTaskDelete が FastLED.show() の
     *       実行中にタスクを破棄して RMT ドライバ状態を壊すため使わない
     *       (実測: 復帰後に出力時間が 15ms → 0.5ms に落ち LED が駆動されなくなる)。
     */
    void setOutputMode(OutputMode mode) { _outputMode = mode; }

    /**
     * @brief 現在のバッファ更新元を取得
     */
    OutputMode getOutputMode() const { return _outputMode; }

    /**
     * @brief テストパターンとブロック幅を設定する
     *
     * @param pattern StripId / Chase
     * @param width   Chase で連続点灯させるLED数 (1未満は1に丸め)。StripId では未使用
     *
     * @note 実際にテスト描画を始めるには setOutputMode(OutputMode::Test) が必要。
     */
    void setTestPattern(TestPattern pattern, uint8_t width);
    TestPattern getTestPattern() const { return _testPattern; }
    uint8_t getTestWidth() const { return _testWidth; }

    /**
     * @brief LEDを即座に更新
     *
     * @note 通常はタスクが自動更新するため、手動呼び出しは不要
     */
    void show();
    
    /**
     * @brief 輝度を設定
     * 
     * @param brightness 輝度 (0-255)
     */
    void setBrightness(uint8_t brightness);
    
    /**
     * @brief 起動オープニングパターンを再生 (ブロッキング)
     *
     * RGB3点の光点が北極→南極へ螺旋降下し、南極で合流後、3点が一斉に
     * 北極へ上昇、最後に全球が虹色に瞬いて消灯する。RGB各チャンネルと
     * 全LEDアドレッシングが機能していることを ~1秒で示す。
     * レンダリングタスク開始前 (setup内) に呼ぶこと。
     *
     * @param durationMs 総再生時間 (ミリ秒)
     */
    void playOpening(uint16_t durationMs);

    /**
     * @brief IMU姿勢補正を有効化/無効化
     *
     * @param enabled true: 有効, false: 無効
     */
    void setIMUCompensation(bool enabled);

    /**
     * @brief XYZ軸インジケータ(オーバーレイ)の有効化/無効化
     *
     * +X=赤 / +Y=緑 / +Z=青 のマーカーを描画に重畳する(負方向は暗色)。
     * IMU姿勢補正と同じ座標系で描くため、球体を回しても軸はワールド空間に
     * 固定されて見える(IMU補正が有効な場合)。
     * @param enabled true: 表示, false: 非表示
     */
    void setAxisIndicator(bool enabled) { _axisIndicatorEnabled = enabled; }
    bool getAxisIndicator() const { return _axisIndicatorEnabled; }

    /**
     * @brief マルチサンプリング(中心+半径R円周上N点の画像空間平均)を設定する
     *
     * 設定変更時に円周オフセットを1回だけ前計算するため、ここで cos/sin を回す。
     * 毎フレームの描画ループでは前計算済みオフセットを使うので三角関数は増えない。
     * @param enabled  false で中心1点のみ(従来動作)
     * @param radiusPx サンプリング円の半径 [px] (0以下は中心のみ)
     * @param points   円周上の点数 (0..kMaxSamplePoints)。実機チューニング用に可変
     */
    void setMultisample(bool enabled, float radiusPx, uint8_t points);
    bool  getMultisampleEnabled() const { return _multisampleEnabled; }
    float getMultisampleRadius() const { return _sampleRadiusPx; }
    uint8_t getMultisamplePoints() const { return _sampleCount; }

    /**
     * @brief デバッグ情報を出力
     */
    void printStatus();

private:
    /**
     * @brief LEDレイアウトファイルを読み込み
     * 
     * @param path レイアウトファイルパス
     * @return 読み込み成功時true
     */
    bool loadLayout(const char* path);
    
    /**
     * @brief 3D座標をUV座標に変換
     * 
     * @param x X座標
     * @param y Y座標
     * @param z Z座標
     * @param u 出力U座標 (0.0-1.0)
     * @param v 出力V座標 (0.0-1.0)
     */
    void sphereToUV(float x, float y, float z, float& u, float& v);
    
    /**
     * @brief Quaternionで3D座標を回転
     * 
     * @param x X座標（入出力）
     * @param y Y座標（入出力）
     * @param z Z座標（入出力）
     * @param qw Quaternion w成分
     * @param qx Quaternion x成分
     * @param qy Quaternion y成分
     * @param qz Quaternion z成分
     */
    void rotateByQuaternion(float& x, float& y, float& z, float qw, float qx, float qy, float qz);
    
    /**
     * @brief レンダリングタスク関数 (static)
     * 
     * @param parameter LEDManagerインスタンスへのポインタ
     */
    static void renderTaskFunction(void* parameter);
    
    /**
     * @brief 1フレーム描画処理
     */
    void renderFrame();
    
    /**
     * @brief LEDバッファを更新
     */
    void updateLEDBuffer();

    /**
     * @brief テストパターンを _ledBuffer に生成する (OutputMode::Test 用)
     *
     * strip 境界 (_stripStartIndex / _ledsPerStrip) だけを使い、画像/IMUは
     * 参照しない。アニメーションは millis() ベースで fps に依存しない速度。
     */
    void updateTestBuffer();
    
    /**
     * @brief IMU補正OFF時用の静的UV→ピクセル座標を事前計算する
     */
    void precomputeStaticUV();
    
    /**
     * @brief 全ストリップのLED出力を並列実行 (DMA)
     * @note RMTハードウェアにより4ストリップが並列出力される
     */
    void showParallel();

    /**
     * @brief オープニング用: 3つの光点中心(単位ベクトル)で1フレーム描画して出力
     * @param dir [3][3] = 各光点(R/G/B)の中心方向 (単位ベクトル)
     * @note 各LEDと光点中心の角距離でガウス減衰させ、3色を加算合成する。
     */
    void renderOpeningDots(const float dir[3][3]);

    /**
     * @brief XYZ軸マーカーを1LEDに重畳する (updateStripBuffer から呼ぶ)
     * @param led 対象LED色 (入出力、内容色に軸色をブレンド)
     * @param x,y,z そのLEDのワールド系方向 (IMU補正後の単位ベクトル)
     */
    void overlayAxisIndicator(CRGB& led, float x, float y, float z);

    /**
     * @brief 画像空間で 7点(中心+六角形6点)を平均サンプリングする
     *
     * 球面→画像の座標変換は呼び出し側で1回だけ行い (中心 px,py)、本関数はその周囲を
     * 画像空間で平滑化する。三角関数を増やさずエイリアシング(ちらつき)を低減する狙い。
     * x(経度)方向はラップ、y(緯度)方向はクランプして継ぎ目/極での破綻を防ぐ。
     * @param cx,cy 中心ピクセル座標 (sphereToUV 由来)
     * @param r,g,b 平均後の色 (出力)
     */
    void sampleAveraged(uint16_t cx, uint16_t cy, uint8_t& r, uint8_t& g, uint8_t& b);

    // メンバー変数
    bool _initialized;               ///< 初期化フラグ
    bool _taskRunning;               ///< タスク実行フラグ
    volatile bool _stopRequested = false;  ///< 協調停止の要求 (show() の途中で殺さないため)
    
    ConfigManager* _config;          ///< 設定マネージャーへのポインタ
    ImageManager* _imageManager;     ///< 画像マネージャーへのポインタ
    IMUManager* _imuManager;         ///< IMUマネージャーへのポインタ（姿勢補正用）
    
    bool _imuCompensationEnabled;    ///< IMU姿勢補正の有効化フラグ
    bool _axisIndicatorEnabled = false;  ///< XYZ軸インジケータ表示フラグ
    OutputMode _outputMode = OutputMode::Sphere;  ///< バッファ更新元 (Manual時はマッピングを飛ばす)
    TestPattern _testPattern = TestPattern::Chase;  ///< OutputMode::Test 時のパターン
    uint8_t _testWidth = 5;                         ///< Chase の連続点灯LED数

    // --- マルチサンプリング (中心 + 半径R円周上のN点を画像空間で平均) ---
    // 座標変換(三角関数)は中心1点のみ。円周オフセットは設定変更時に1回だけ前計算し、
    // 毎フレームは整数オフセット加算 + getPixel + 平均のみ (毎フレームの三角関数ゼロ)。
    static constexpr uint8_t kMaxSamplePoints = 12;  ///< 円周上サンプル点の上限
    bool _multisampleEnabled = true;     ///< マルチサンプル有効化
    float _sampleRadiusPx = 2.0f;        ///< サンプリング円の半径 [px]
    uint8_t _sampleCount = 6;            ///< 円周上のサンプル点数 (中心を除く)
    int16_t _sampleOff[kMaxSamplePoints][2] = {{0, 0}};  ///< 前計算した円周オフセット[dx,dy]

    TaskHandle_t _renderTaskHandle;  ///< レンダリングタスクハンドル
    
    CRGB* _ledBuffer;                ///< LEDバッファ (SRAM)
    LEDCoord* _ledLayout;            ///< LEDレイアウト (SRAM)
    uint16_t _numLEDs;               ///< LED総数
    uint16_t* _pxLUT = nullptr;      ///< 静的UV→ピクセルX (IMU補正OFF時, 事前計算)
    uint16_t* _pyLUT = nullptr;      ///< 静的UV→ピクセルY (IMU補正OFF時, 事前計算)
    
    uint16_t _ledsPerStrip[kNumStrips];    ///< ストリップ毎のLED数
    uint16_t _stripStartIndex[kNumStrips]; ///< ストリップ開始インデックス
    CRGB* _stripBuffers[kNumStrips];       ///< ストリップ毎のバッファポインタ
    
    LEDStats _stats;                 ///< 統計情報
    unsigned long _lastFPSUpdate;    ///< 最後のFPS更新時刻
    uint32_t _frameCount;            ///< フレームカウント
    uint32_t _lastQuatSeq = 0;       ///< 前フレームで使った姿勢の通番 (鮮度計測用)
    AttitudeStepDiag _stepDiag;      ///< 毎フレームの姿勢健全性診断 (imu/AttitudeStepDiag.h)

    static LEDManager* _instance;    ///< 静的インスタンスポインタ (コールバック用)
};

} // namespace sastle

#endif // LED_MANAGER_H
