"""בדיקות אופליין (בלי רשת) לתקלות שכבר קרו בפועל - כל בדיקה מתועדת לפי התקלה שהיא
מגינה מפניה. הרצה: python -m unittest discover -s tests -v"""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import market_data, notifier, schedule_guard, store
from src.market_hours import is_trading_day


class HolidayCalendar(unittest.TestCase):
    def test_tase_holiday_is_closed_but_us_is_open(self):
        # 2.10.2026 - חג בת"א, יום מסחר רגיל בארה"ב
        self.assertFalse(is_trading_day("IL", dt.date(2026, 10, 2)))
        self.assertTrue(is_trading_day("US", dt.date(2026, 10, 2)))

    def test_regular_monday_is_trading_day(self):
        self.assertTrue(is_trading_day("IL", dt.date(2026, 10, 5)))

    def test_expected_prev_close_skips_tase_holiday(self):
        # אחרי 2.10 (חג) ה"אתמול" של 5.10 הוא 1.10 - אחרת כל מניה תסומן כפער
        self.assertEqual(market_data._expected_last_close_date(dt.date(2026, 10, 5), "X.TA"), dt.date(2026, 10, 1))
        self.assertEqual(market_data._expected_last_close_date(dt.date(2026, 10, 5), ""), dt.date(2026, 10, 2))


class ThinPrint(unittest.TestCase):
    # 5.10.2026 סאמיט: עסקה של 21 מניות הפכה ל"ירידה" של 3.8%
    def _rows(self, vol, date):
        return [dict(ticker="SMT.TA", last_volume=vol, avg_volume_20d=45000, last_close_date=date)]

    def test_tiny_volume_while_market_open_is_flagged(self):
        rows = self._rows(21, dt.datetime.now(market_data.ZoneInfo("Asia/Jerusalem")).date())
        with mock.patch.object(market_data, "is_market_open", return_value=True):
            market_data._flag_thin_prints(rows)
        self.assertTrue(rows[0]["thin_print"])

    def test_normal_volume_not_flagged(self):
        rows = self._rows(3000, dt.datetime.now(market_data.ZoneInfo("Asia/Jerusalem")).date())
        with mock.patch.object(market_data, "is_market_open", return_value=True):
            market_data._flag_thin_prints(rows)
        self.assertFalse(rows[0]["thin_print"])

    def test_market_closed_not_flagged(self):
        rows = self._rows(21, dt.date.today())
        with mock.patch.object(market_data, "is_market_open", return_value=False):
            market_data._flag_thin_prints(rows)
        self.assertFalse(rows[0]["thin_print"])


class BidCrossCheck(unittest.TestCase):
    def _run(self, info, price):
        fake = mock.Mock()
        fake.info = info
        with mock.patch.object(market_data.yf, "Ticker", return_value=fake):
            return market_data.find_prints_below_bid([("SMT.TA", price)])

    def test_price_below_bid_is_rejected(self):
        self.assertIn("SMT.TA", self._run({"bid": 4137, "ask": 4175}, 40.55))

    def test_price_inside_spread_passes(self):
        self.assertEqual(self._run({"bid": 4137, "ask": 4175}, 41.5), {})

    def test_missing_or_crossed_book_is_not_blocked(self):
        self.assertEqual(self._run({}, 40.55), {})
        self.assertEqual(self._run({"bid": 4200, "ask": 4100}, 40.55), {})


class SummaryDelivery(unittest.TestCase):
    def setUp(self):
        self.conn = store.get_conn(os.path.join(tempfile.mkdtemp(), "t.db"))

    def _send(self, msg_id, enabled=True, active=True, kind="daily"):
        with mock.patch.object(notifier, "notify_typed", return_value=msg_id), \
             mock.patch.object(notifier, "is_message_type_enabled", return_value=enabled), \
             mock.patch.object(notifier, "telegram_active", return_value=active):
            return schedule_guard.send_and_mark(self.conn, {}, kind, "daily_summary", "x", "t")

    def test_failed_send_is_not_marked_sent(self):
        self.assertFalse(self._send(None))
        self.assertFalse(schedule_guard.already_sent_today(self.conn, "daily"))

    def test_successful_send_is_marked(self):
        self.assertTrue(self._send(123))
        self.assertTrue(schedule_guard.already_sent_today(self.conn, "daily"))

    def test_disabled_type_or_inactive_telegram_is_marked(self):
        self.assertTrue(self._send(None, enabled=False, kind="a"))
        self.assertTrue(self._send(None, active=False, kind="b"))


class AlertRollback(unittest.TestCase):
    def setUp(self):
        self.conn = store.get_conn(os.path.join(tempfile.mkdtemp(), "t.db"))

    def _insert(self, ticker, pct, msg_id=None):
        self.conn.execute(
            "INSERT INTO alerts(scan_date,scan_ts,ticker,index_name,pct_change,last_close,prev_close,reasons_json,telegram_message_id)"
            " VALUES('2026-10-05','x',?,'TA35',?,1,1,'[]',?)", (ticker, pct, msg_id))
        self.conn.commit()

    def test_new_row_is_deleted_on_restore(self):
        self._insert("AAA.TA", -5)
        store.restore_alert(self.conn, "2026-10-05", "AAA.TA", None)
        self.assertIsNone(store.get_todays_alert_pct(self.conn, "AAA.TA", "2026-10-05"))

    def test_existing_row_returns_to_previous_state(self):
        self._insert("BBB.TA", -4, 77)
        snap = store.snapshot_alert(self.conn, "2026-10-05", "BBB.TA")
        self.conn.execute("UPDATE alerts SET pct_change=-9 WHERE ticker='BBB.TA'")
        self.conn.commit()
        store.restore_alert(self.conn, "2026-10-05", "BBB.TA", snap)
        self.assertEqual(store.get_todays_alert_pct(self.conn, "BBB.TA", "2026-10-05"), -4)
        self.assertEqual(store.get_todays_telegram_message_id(self.conn, "BBB.TA", "2026-10-05"), 77)


class ExcludedAlerts(unittest.TestCase):
    def test_exclusion_list_loaded(self):
        ids = store.excluded_alert_ids()
        self.assertEqual(len(ids), 16)
        self.assertIn("NOT IN", store.exclusion_clause())


class HoleBackfill(unittest.TestCase):
    # 6.10.2026: yfinance השמיט יום מסחר שלם (בעוד שהנתונים התוך-יומיים קיימים) - כל המניות
    # סומנו כ"פער" והשינוי היומי התעוות. שחזור מבארים של 5 דקות, רק ליום מלא.
    def _intraday(self, day, n_bars=88, last="17:25"):
        import pandas as pd
        idx = pd.date_range(f"{day} 09:55", periods=n_bars, freq="5min", tz="Asia/Jerusalem")
        if last:
            idx = idx[:-1].append(pd.DatetimeIndex([pd.Timestamp(f"{day} {last}", tz="Asia/Jerusalem")]))
        return __import__("pandas").DataFrame(
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 10.0}, index=idx)

    def test_full_day_is_rebuilt(self):
        rows = market_data._intraday_rows_for_holes("X.TA", [dt.date(2026, 10, 6)], self._intraday("2026-10-06"), None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["Close"], 100.5)
        self.assertEqual(rows[0][1]["Volume"], 880.0)

    def test_incomplete_day_is_not_invented(self):
        short = self._intraday("2026-10-06", n_bars=10, last="10:45")
        self.assertEqual(market_data._intraday_rows_for_holes("X.TA", [dt.date(2026, 10, 6)], short, None), [])
        early_end = self._intraday("2026-10-06", n_bars=30, last="12:30")
        self.assertEqual(market_data._intraday_rows_for_holes("X.TA", [dt.date(2026, 10, 6)], early_end, None), [])


class EntrySignal(unittest.TestCase):
    # 7.10.2026: כרטיס ניקוד רב-גורמי לאופק החזקה של עד 3 ימים
    def setUp(self):
        from src import strategy
        self.f = strategy.entry_signal
        self.s = strategy

    def test_israel_strong_setup_is_buy(self):
        sig, why = self.f("TA35", -5.0, None, -12, "Utilities", 10)
        self.assertEqual(sig, self.s.SIGNAL_BUY)
        self.assertIn("ניקוד 6", why)

    def test_israel_drop_alone_is_not_enough(self):
        # ירידה חדה בסקטור חלש וקרוב לממוצע - לא מספיק
        self.assertNotEqual(self.f("TA125", -4.6, None, 3, "Real Estate", 14)[0], self.s.SIGNAL_BUY)

    def test_israel_small_drop_weak_sector_is_avoid(self):
        self.assertEqual(self.f("TA125", -3.8, None, 3, "Real Estate", 15)[0], self.s.SIGNAL_AVOID)

    def test_israel_mid_score_is_wait(self):
        self.assertEqual(self.f("TA125", -3.8, None, None, "Technology", 11)[0], self.s.SIGNAL_WAIT)  # 2+1

    def test_us_uses_recovery_not_hour(self):
        self.assertEqual(self.f("SP500", -6.5, 15, -11, "Technology", None)[0], self.s.SIGNAL_BUY)
        self.assertEqual(self.f("SP500", -3.7, 0, 5, "Energy", None)[0], self.s.SIGNAL_AVOID)

    def test_missing_drop_is_unknown_and_missing_factors_dont_crash(self):
        self.assertEqual(self.f("TA35", float("nan"))[0], self.s.SIGNAL_UNKNOWN)
        self.assertEqual(self.f("TA35", -4.6)[0], self.s.SIGNAL_WAIT)  # רק ירידה חדה = 2 נקודות

    def test_target_is_three_percent(self):
        self.assertAlmostEqual(self.s.FIXED_TARGET_PCT, 0.03)


class TrailingNanClose(unittest.TestCase):
    # 8.10.2026: yfinance החזירה שורה ליום המסחר האחרון (7.10) עם Close=NaN - הכרטיס הציג את 6.10.
    def test_last_finished_day_with_nan_close_is_a_hole(self):
        import pandas as pd
        idx = pd.DatetimeIndex(["2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07"], tz="Asia/Jerusalem")
        frame = pd.DataFrame({"Close": [100.0, 101.0, 102.0, float("nan")], "Volume": [1, 1, 1, 1]}, index=idx)
        multi = pd.concat({"X.TA": frame}, axis=1)  # _find_hole_days מצפה לעמודות (טיקר, שדה)
        holes = market_data._find_hole_days(multi, ["X.TA"])
        self.assertIn(dt.date(2026, 10, 7), holes.get("X.TA", []))


class StopCap(unittest.TestCase):
    # 8.10.2026: סטופ ATR (כ-11%) כמעט לא נפגע באופק של 3 ימים - תקרה של 7% מתחת לכניסה
    def test_volatile_stock_stop_is_capped_at_seven_percent(self):
        from src import strategy
        idea = strategy.suggest_strategy(last_close=100.0, last_low=97.0, recent_20d_low=95.0,
                                         overreaction_score=40, atr=6.0)
        self.assertAlmostEqual(idea.stop_loss / idea.entry_limit - 1, -0.07, places=3)

    def test_stable_stock_keeps_its_tighter_atr_stop(self):
        from src import strategy
        idea = strategy.suggest_strategy(last_close=100.0, last_low=97.0, recent_20d_low=95.0,
                                         overreaction_score=40, atr=1.5)
        self.assertGreater(idea.stop_loss / idea.entry_limit - 1, -0.07)


class AlertFeatures(unittest.TestCase):
    # 8.10.2026: וקטורים מועמדים נשמרים לניתוח עתידי, בלי להשפיע על הניקוד
    def _row(self, n=40):
        import pandas as pd
        idx = pd.date_range("2026-08-01", periods=n, freq="B")
        close = pd.Series([100.0 + i * 0.1 for i in range(n)], index=idx)
        close.iloc[-2] = close.iloc[-3] - 3          # יום ירידה לפני ההתראה
        return {"history": close, "highs": close + 1, "lows_series": close - 1, "pct_change": -5.0,
                "last_close": float(close.iloc[-1]), "last_open": float(close.iloc[-2]) * 0.99, "avg_volume_20d": 1000.0}

    def test_compute_returns_all_fields_from_prior_days_only(self):
        from src import alert_features
        f = alert_features.compute(self._row())
        for k in ("dd_5d", "atr_norm_drop", "dollar_vol", "gap_open_pct", "down_streak", "ret_20d"):
            self.assertIsNotNone(f[k], k)
        self.assertLess(f["dd_5d"], 0)
        self.assertGreaterEqual(f["down_streak"], 1)

    def test_compute_never_raises_on_bad_row(self):
        from src import alert_features
        f = alert_features.compute({})
        self.assertTrue(all(v is None for v in f.values()))

    def test_save_roundtrip(self):
        from src import alert_features
        conn = store.get_conn(os.path.join(tempfile.mkdtemp(), "t.db"))
        alert_features.save(conn, 7, alert_features.compute(self._row()))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM alert_features WHERE alert_id=7").fetchone()[0], 1)


class StrategyStats(unittest.TestCase):
    # 8.10.2026: סטטיסטיקות ברמת יום (cluster bootstrap), נטו אחרי עמלות, ו-Top-K
    FEES = {"IL": {"commission_pct": 0.3, "commission_min": 26.0, "currency": "ILS",
                   "capital_gains_tax_pct": 25.0, "management_fee_annual_pct": 1.15}}

    def _df(self):
        import pandas as pd
        rows = []
        for d, day in enumerate(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"] * 4):
            rows.append({"scan_date": day, "score": 5 if d % 2 == 0 else 0, "y": 1 if d % 2 == 0 else 0,
                         "ret": 3.0 if d % 2 == 0 else -1.0, "pct_change": -4.0 - (d % 3)})
        return pd.DataFrame(rows)

    def test_small_position_pays_minimum_commission(self):
        from src import strategy_stats
        small = strategy_stats.net_return_pct(0.0, 5000, self.FEES)
        large = strategy_stats.net_return_pct(0.0, 20000, self.FEES)
        self.assertLess(small, large)          # מינימום עמלה (26 ש"ח לצד) כבד יותר בפוזיציה קטנה
        self.assertLess(small, -0.9)

    def test_bucket_summary_has_confidence_intervals(self):
        from src import strategy_stats
        t = strategy_stats.bucket_summary(self._df(), self.FEES, position=10000, B=100)
        buy = t[t["קבוצה"].str.startswith("4+")].iloc[0]
        self.assertEqual(buy["התראות"], 10)
        self.assertLessEqual(buy["הצלחה CI"][0], buy["הצלחה %"])
        self.assertGreaterEqual(buy["הצלחה CI"][1], buy["הצלחה %"])

    def test_topk_only_counts_buy_scores_in_filtered_columns(self):
        from src import strategy_stats
        t = strategy_stats.topk_table(self._df(), ks=(1,))
        self.assertEqual(int(t.iloc[0]["K"]), 1)
        self.assertGreaterEqual(t.iloc[0]["רק 4+: הצלחה %"], 99)   # בדוגמה כל ה-4+ הצליחו


if __name__ == "__main__":
    unittest.main()
