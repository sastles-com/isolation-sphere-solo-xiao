#include <unity.h>
#include <math.h>
uint32_t g_fakeMillis = 0;
void setUp(void) {}
void tearDown(void) {}
#include "GestureLogic.h"
using namespace sastle;
using namespace sastle::gesture_logic;

static const float kDeg = (float)M_PI / 180.0f;

/// 表示ワールド系の軸 (ax,ay,az) まわりに deg 回した回転を表すクォータニオン
static Quat axisAngle(float ax, float ay, float az, float deg) {
    const float h = deg * kDeg / 2.0f;
    return Quat(cosf(h), ax * sinf(h), ay * sinf(h), az * sinf(h));
}

/// base の姿勢から、表示ワールド系で rot だけ回した後の getQuaternion() の値。
/// 描画は rot(conj(q)) なので conj(now) = rot ⊗ conj(base) → now = base ⊗ conj(rot)
static Quat rotatedInWorld(const Quat& base, const Quat& rot) {
    return quatMul(base, quatConj(rot));
}

/// 適当な傾きの基準姿勢 (メニューに入った時の持ち方)
static Quat someBase() {
    return quatMul(axisAngle(1, 0, 0, 30), axisAngle(0, 1, 0, -20));
}

// ---------------------------------------------------------------------------
// 回転ベクトル
// ---------------------------------------------------------------------------

void test_relative_rotation_world_z(void) {
    const Quat base = someBase();
    float rv[3];
    relativeRotationDeg(base, rotatedInWorld(base, axisAngle(0, 0, 1, 60)), rv);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, rv[0]);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, rv[1]);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 60.0f, rv[2]);

    relativeRotationDeg(base, rotatedInWorld(base, axisAngle(0, 0, 1, -50)), rv);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, -50.0f, rv[2]);
}

void test_relative_rotation_world_x(void) {
    const Quat base = someBase();
    float rv[3];
    relativeRotationDeg(base, rotatedInWorld(base, axisAngle(1, 0, 0, 70)), rv);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 70.0f, rv[0]);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, rv[2]);
}

void test_relative_rotation_ignores_quat_sign(void) {
    // BNO055 は同じ姿勢を -q で返すことがある
    const Quat base = someBase();
    const Quat now = quatNegated(rotatedInWorld(base, axisAngle(0, 0, 1, 60)));
    float rv[3];
    relativeRotationDeg(base, now, rv);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 60.0f, rv[2]);
}

void test_relative_rotation_matches_render_mapping(void) {
    // 描画と同じ写像 (rot(conj(q)) で機体→表示ワールド) で、LED 位置の動きが
    // 表示ワールド +Z まわり反時計回りになっていることを直接確かめる
    const Quat base = someBase();
    const Quat now = rotatedInWorld(base, axisAngle(0, 0, 1, 90));
    // 基準姿勢で表示ワールドの +X に見える LED の機体座標 p = rot(base) · (1,0,0)
    const Quat p = quatMul(quatMul(base, Quat(0, 1, 0, 0)), quatConj(base));
    // 今の姿勢での表示ワールド座標 = rot(conj(now)) · p
    const Quat w = quatMul(quatMul(quatConj(now), p), now);
    TEST_ASSERT_FLOAT_WITHIN(1e-4f, 0.0f, w.x);
    TEST_ASSERT_FLOAT_WITHIN(1e-4f, 1.0f, w.y);   // +X → +Y = +Z から見て反時計回り
    TEST_ASSERT_FLOAT_WITHIN(1e-4f, 0.0f, w.z);
}

void test_z_selection_needs_dominant_z(void) {
    const float a[3] = {0, 0, 50};
    const float b[3] = {0, 0, -50};
    const float c[3] = {0, 0, 40};
    const float d[3] = {60, 0, 50};
    TEST_ASSERT_EQUAL_INT8(1, GestureFsm::zSelection(a));
    TEST_ASSERT_EQUAL_INT8(-1, GestureFsm::zSelection(b));
    TEST_ASSERT_EQUAL_INT8(0, GestureFsm::zSelection(c));
    TEST_ASSERT_EQUAL_INT8(0, GestureFsm::zSelection(d));
}

// ---------------------------------------------------------------------------
// シェイク
// ---------------------------------------------------------------------------

/// 1 回振る: 強い加速 (30) → 静止 (9.8)。上がりと戻りは 200 ms 以内なので 1 回と数える
static ShakeDetector::Result shakeOnce(ShakeDetector& d, uint32_t t) {
    ShakeDetector::Result a = d.feed(t, 30.0f);
    ShakeDetector::Result b = d.feed(t + 50, 9.8f);
    TEST_ASSERT_FALSE(b.shake);
    return a;
}

void test_shake_first_sample_is_not_shake(void) {
    ShakeDetector d;
    TEST_ASSERT_FALSE(d.feed(0, 30.0f).shake);
}

void test_triple_shake_in_window(void) {
    ShakeDetector d;
    d.feed(0, 9.8f);
    TEST_ASSERT_TRUE(shakeOnce(d, 100).shake);
    TEST_ASSERT_FALSE(shakeOnce(d, 500).triple);
    const ShakeDetector::Result r = shakeOnce(d, 900);
    TEST_ASSERT_TRUE(r.shake);
    TEST_ASSERT_TRUE(r.triple);
}

void test_triple_shake_too_slow(void) {
    ShakeDetector d;
    d.feed(0, 9.8f);
    shakeOnce(d, 100);
    shakeOnce(d, 1200);
    TEST_ASSERT_FALSE(shakeOnce(d, 2300).triple);   // 3 回が 2.2 秒に広がっている
}

void test_shake_min_interval(void) {
    ShakeDetector d;
    d.feed(0, 9.8f);
    TEST_ASSERT_TRUE(d.feed(1000, 30.0f).shake);
    TEST_ASSERT_FALSE(d.feed(1050, 9.8f).shake);   // 50 ms 後の戻りは数えない
    TEST_ASSERT_TRUE(d.feed(1300, 30.0f).shake);
}

// ---------------------------------------------------------------------------
// 状態遷移
// ---------------------------------------------------------------------------

static Input in(uint32_t t, const Quat& q, bool shake = false, bool triple = false) {
    Input i;
    i.nowMs = t;
    i.shake.shake = shake;
    i.shake.triple = triple;
    i.quatValid = true;
    i.q = q;
    return i;
}

static GestureFsm menuAt(uint32_t t, const Quat& base) {
    GestureFsm f;
    f.begin(0);
    TEST_ASSERT_EQUAL(Action::EnterMenu, f.update(in(t, base, true, true)));
    TEST_ASSERT_EQUAL(Action::None, f.update(in(t + kMenuSettleMs - 1, base)));
    return f;
}

void test_boot_guard(void) {
    GestureFsm f;
    f.begin(0);
    TEST_ASSERT_EQUAL(Action::None, f.update(in(4000, someBase(), true, true)));
    TEST_ASSERT_EQUAL(Action::EnterMenu, f.update(in(5000, someBase(), true, true)));
    TEST_ASSERT_EQUAL(UiState::Menu, f.state());
}

void test_menu_timeout(void) {
    const Quat base = someBase();
    GestureFsm f = menuAt(6000, base);
    TEST_ASSERT_EQUAL(Action::None, f.update(in(15999, base)));
    TEST_ASSERT_EQUAL(Action::MenuTimeout, f.update(in(16000, base)));
    TEST_ASSERT_EQUAL(UiState::Normal, f.state());
}

void test_z_minus_toggles_ap(void) {
    const Quat base = someBase();
    const Quat q = rotatedInWorld(base, axisAngle(0, 0, 1, -60));
    GestureFsm f = menuAt(6000, base);
    TEST_ASSERT_EQUAL(Action::SelectStart, f.update(in(7000, q)));
    TEST_ASSERT_EQUAL(Action::None, f.update(in(7999, q)));
    TEST_ASSERT_EQUAL(Action::ApToggle, f.update(in(8000, q)));
    TEST_ASSERT_EQUAL(UiState::Normal, f.state());
}

void test_hold_restarts_when_rotation_drops(void) {
    const Quat base = someBase();
    const Quat q = rotatedInWorld(base, axisAngle(0, 0, 1, 60));
    const Quat half = rotatedInWorld(base, axisAngle(0, 0, 1, 30));
    GestureFsm f = menuAt(6000, base);
    TEST_ASSERT_EQUAL(Action::SelectStart, f.update(in(7000, q)));
    TEST_ASSERT_EQUAL(Action::None, f.update(in(7500, half)));
    TEST_ASSERT_EQUAL(Action::SelectStart, f.update(in(7600, q)));
    TEST_ASSERT_EQUAL(Action::None, f.update(in(8000, q)));   // 7000 からなら確定していた
    TEST_ASSERT_EQUAL(Action::PowerOffArm, f.update(in(8600, q)));
}

void test_x_rotation_is_ignored(void) {
    const Quat base = someBase();
    const Quat q = rotatedInWorld(base, axisAngle(1, 0, 0, 80));
    GestureFsm f = menuAt(6000, base);
    f.update(in(6400, base));   // 振り終わり (0.5 秒) の間の姿勢が基準になる
    for (uint32_t t = 6600; t < 15000; t += 100) {
        TEST_ASSERT_EQUAL(Action::None, f.update(in(t, q)));
    }
    TEST_ASSERT_EQUAL(UiState::Menu, f.state());
}

void test_z_plus_power_off_after_4s(void) {
    const Quat base = someBase();
    const Quat q = rotatedInWorld(base, axisAngle(0, 0, 1, 60));
    GestureFsm f = menuAt(6000, base);
    f.update(in(7000, q));
    TEST_ASSERT_EQUAL(Action::PowerOffArm, f.update(in(8000, q)));
    TEST_ASSERT_EQUAL(UiState::PowerOffPending, f.state());
    TEST_ASSERT_EQUAL(Action::None, f.update(in(11999, base)));   // 元の向きに戻しても取り消さない
    TEST_ASSERT_EQUAL(Action::PowerOffNow, f.update(in(12000, base)));
    TEST_ASSERT_EQUAL(UiState::PoweringOff, f.state());
    TEST_ASSERT_EQUAL(Action::None, f.update(in(20000, base, true, true)));
}

void test_shake_cancels_power_off(void) {
    const Quat base = someBase();
    const Quat q = rotatedInWorld(base, axisAngle(0, 0, 1, 60));
    GestureFsm f = menuAt(6000, base);
    f.update(in(7000, q));
    f.update(in(8000, q));
    TEST_ASSERT_EQUAL(Action::PowerOffCancel, f.update(in(10000, q, true)));
    TEST_ASSERT_EQUAL(UiState::Normal, f.state());
}

void test_base_is_taken_after_shaking_settles(void) {
    // 3 回目のシェイクの瞬間は大きく傾いていた。振り終わった姿勢 (settled) から測る
    const Quat settled = someBase();
    const Quat shaking = rotatedInWorld(settled, axisAngle(0, 0, 1, 40));
    GestureFsm f;
    f.begin(0);
    TEST_ASSERT_EQUAL(Action::EnterMenu, f.update(in(6000, shaking, true, true)));
    TEST_ASSERT_EQUAL(Action::None, f.update(in(6300, rotatedInWorld(settled, axisAngle(0, 0, 1, 90)))));  // 揺れ中は選ばない
    TEST_ASSERT_EQUAL(Action::None, f.update(in(6400, settled)));
    // settled から −30° は選ばない (シェイク時の姿勢からなら −70° で選ばれていた)
    TEST_ASSERT_EQUAL(Action::None, f.update(in(6600, rotatedInWorld(settled, axisAngle(0, 0, 1, -30)))));
    TEST_ASSERT_EQUAL(Action::SelectStart, f.update(in(6700, rotatedInWorld(settled, axisAngle(0, 0, 1, -50)))));
}

void test_recover_after_failed_power_off(void) {
    const Quat base = someBase();
    const Quat q = rotatedInWorld(base, axisAngle(0, 0, 1, 60));
    GestureFsm f = menuAt(6000, base);
    TEST_ASSERT_FALSE(f.recoverFromFailedPowerOff(6600));   // PoweringOff 以外では何もしない
    TEST_ASSERT_EQUAL(UiState::Menu, f.state());
    f.update(in(7000, q));
    f.update(in(8000, q));
    f.update(in(12000, q));
    TEST_ASSERT_EQUAL(UiState::PoweringOff, f.state());
    TEST_ASSERT_TRUE(f.recoverFromFailedPowerOff(15000));
    TEST_ASSERT_EQUAL(UiState::Normal, f.state());
    TEST_ASSERT_EQUAL(Action::EnterMenu, f.update(in(16000, base, true, true)));   // 操作が戻る
}

void test_invalid_quat_does_not_enter_menu(void) {
    GestureFsm f;
    f.begin(0);
    Input i = in(6000, someBase(), true, true);
    i.quatValid = false;
    TEST_ASSERT_EQUAL(Action::None, f.update(i));
}

// ---------------------------------------------------------------------------
// 予告の明滅
// ---------------------------------------------------------------------------

void test_power_off_scale_blinks_faster_and_dims(void) {
    TEST_ASSERT_EQUAL_UINT8(255, powerOffScale(0));
    TEST_ASSERT_EQUAL_UINT8(0, powerOffScale(kPowerOffConfirmMs));

    // 点灯区間の数 (= 点滅回数) と、前半 / 後半の点滅回数、点灯中の最大明るさ
    int blinksFirst = 0, blinksSecond = 0;
    uint8_t maxFirst = 0, maxLast = 0;
    bool prevOn = false;
    for (uint32_t t = 0; t < kPowerOffConfirmMs; t++) {
        const uint8_t s = powerOffScale(t);
        const bool on = s > 0;
        if (on && !prevOn) (t < kPowerOffConfirmMs / 2 ? blinksFirst : blinksSecond)++;
        prevOn = on;
        if (t < 1000 && s > maxFirst) maxFirst = s;
        if (t >= 3000 && s > maxLast) maxLast = s;
    }
    TEST_ASSERT_EQUAL_INT(14, blinksFirst + blinksSecond);
    TEST_ASSERT_TRUE(blinksSecond * 2 >= blinksFirst * 3);   // 後半ほど速い (前半 5 回、後半 9 回)
    TEST_ASSERT_TRUE(maxLast < maxFirst / 2);           // 後半ほど暗い
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_relative_rotation_world_z);
    RUN_TEST(test_relative_rotation_world_x);
    RUN_TEST(test_relative_rotation_ignores_quat_sign);
    RUN_TEST(test_relative_rotation_matches_render_mapping);
    RUN_TEST(test_z_selection_needs_dominant_z);
    RUN_TEST(test_shake_first_sample_is_not_shake);
    RUN_TEST(test_triple_shake_in_window);
    RUN_TEST(test_triple_shake_too_slow);
    RUN_TEST(test_shake_min_interval);
    RUN_TEST(test_boot_guard);
    RUN_TEST(test_menu_timeout);
    RUN_TEST(test_z_minus_toggles_ap);
    RUN_TEST(test_hold_restarts_when_rotation_drops);
    RUN_TEST(test_x_rotation_is_ignored);
    RUN_TEST(test_z_plus_power_off_after_4s);
    RUN_TEST(test_shake_cancels_power_off);
    RUN_TEST(test_base_is_taken_after_shaking_settles);
    RUN_TEST(test_recover_after_failed_power_off);
    RUN_TEST(test_invalid_quat_does_not_enter_menu);
    RUN_TEST(test_power_off_scale_blinks_faster_and_dims);
    return UNITY_END();
}
