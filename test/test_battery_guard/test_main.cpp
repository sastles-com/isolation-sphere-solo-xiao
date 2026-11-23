#include <unity.h>
#include "BatteryGuard.h"
using namespace sastle::battery_guard;

void setUp(void) {}
void tearDown(void) {}

/// t0 から t1 まで 5 秒ごとに同じ値を入れ、最初に出たイベントを返す
static Event feed(Guard& g, uint32_t t0, uint32_t t1, uint16_t mv, int16_t ma = -1000, bool valid = true) {
    Event first = Event::None;
    for (uint32_t t = t0; t <= t1; t += 5000) {
        const Event e = g.update(valid, mv, ma, t);
        if (e != Event::None && first == Event::None) first = e;
    }
    return first;
}

void test_normal_voltage_no_event(void) {
    Guard g;
    TEST_ASSERT_EQUAL(Event::None, feed(g, 0, 600000, 7600));
    TEST_ASSERT_EQUAL(Level::Ok, g.level());
}

void test_warn_after_hold(void) {
    Guard g;
    TEST_ASSERT_EQUAL(Event::None, feed(g, 0, 25000, 6550));     // 25 秒ではまだ
    TEST_ASSERT_EQUAL(Event::Warn, g.update(true, 6550, -1000, 30000));
    TEST_ASSERT_EQUAL(Level::Low, g.level());
    TEST_ASSERT_EQUAL(Event::None, feed(g, 35000, 120000, 6550));  // 1 回だけ
}

void test_short_dip_ignored(void) {
    Guard g;
    // 負荷で 20 秒だけ 6.3 V に落ちて戻る → 予告も OFF もしない
    TEST_ASSERT_EQUAL(Event::None, feed(g, 0, 20000, 6300));
    TEST_ASSERT_EQUAL(Event::None, feed(g, 25000, 300000, 7000));
    TEST_ASSERT_EQUAL(Level::Ok, g.level());
}

void test_power_off_after_hold(void) {
    Guard g;
    feed(g, 0, 60000, 6550);                                       // 予告済み
    TEST_ASSERT_EQUAL(Event::None, feed(g, 65000, 90000, 6390));    // 25 秒
    TEST_ASSERT_EQUAL(Event::PowerOff, g.update(true, 6390, -1000, 95000));
    TEST_ASSERT_EQUAL(Level::Empty, g.level());
    TEST_ASSERT_EQUAL(Event::None, feed(g, 100000, 200000, 6300));  // 以後は出さない
}

void test_direct_drop_gives_warn_and_off(void) {
    Guard g;
    // 予告の前にいきなり 6.4 V 未満 → 30 秒で予告と OFF の両方の条件がそろう。OFF を優先
    TEST_ASSERT_EQUAL(Event::None, feed(g, 0, 25000, 6300));
    TEST_ASSERT_EQUAL(Event::PowerOff, g.update(true, 6300, -1000, 30000));
}

void test_charging_not_counted(void) {
    Guard g;
    TEST_ASSERT_EQUAL(Event::None, feed(g, 0, 300000, 6300, +500));
    TEST_ASSERT_EQUAL(Level::Ok, g.level());
}

void test_charging_resets_timer(void) {
    Guard g;
    feed(g, 0, 25000, 6300);                                       // 25 秒下回る
    g.update(true, 6300, +500, 27000);                              // 充電器を挿した
    TEST_ASSERT_EQUAL(Event::None, feed(g, 30000, 50000, 6300));     // 抜いてから 20 秒
}

void test_invalid_samples_ignored(void) {
    Guard g;
    TEST_ASSERT_EQUAL(Event::None, feed(g, 0, 600000, 6000, -1000, false));
    TEST_ASSERT_EQUAL(Level::Ok, g.level());
}

void test_warn_rearms_after_recovery(void) {
    Guard g;
    TEST_ASSERT_EQUAL(Event::Warn, feed(g, 0, 60000, 6550));
    feed(g, 65000, 100000, 6700);                                  // 6.8 V 未満なのでまだ解除しない
    TEST_ASSERT_EQUAL(Event::None, feed(g, 105000, 200000, 6550));
    feed(g, 205000, 240000, 6900, +800);                            // 充電して戻った
    TEST_ASSERT_EQUAL(Level::Ok, g.level());
    TEST_ASSERT_EQUAL(Event::Warn, feed(g, 245000, 400000, 6550));
}

void test_millis_wraparound(void) {
    Guard g;
    const uint32_t t0 = 0xFFFFFFFFu - 10000;
    g.update(true, 6300, -1000, t0);
    TEST_ASSERT_EQUAL(Event::None, g.update(true, 6300, -1000, t0 + 20000));
    TEST_ASSERT_EQUAL(Event::PowerOff, g.update(true, 6300, -1000, t0 + 30000));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_normal_voltage_no_event);
    RUN_TEST(test_warn_after_hold);
    RUN_TEST(test_short_dip_ignored);
    RUN_TEST(test_power_off_after_hold);
    RUN_TEST(test_direct_drop_gives_warn_and_off);
    RUN_TEST(test_charging_not_counted);
    RUN_TEST(test_charging_resets_timer);
    RUN_TEST(test_invalid_samples_ignored);
    RUN_TEST(test_warn_rearms_after_recovery);
    RUN_TEST(test_millis_wraparound);
    return UNITY_END();
}
