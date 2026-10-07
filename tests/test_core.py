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
    # 7.10.2026: 🟢/🟡/🔴 לפי ניתוח ההתראות באופק החזקה של עד 3 ימים
    def setUp(self):
        from src import strategy
        self.f = strategy.entry_signal
        self.s = strategy

    def test_israel_thresholds(self):
        self.assertEqual(self.f("TA35", -4.0)[0], self.s.SIGNAL_BUY)
        self.assertEqual(self.f("TA125", -4.6)[0], self.s.SIGNAL_BUY)
        self.assertEqual(self.f("TA125", -3.9)[0], self.s.SIGNAL_WAIT)
        self.assertEqual(self.f("TA35", -3.5)[0], self.s.SIGNAL_WAIT)
        self.assertEqual(self.f("TA35", -3.2)[0], self.s.SIGNAL_AVOID)

    def test_israel_ignores_position_data(self):
        self.assertEqual(self.f("TA35", -4.2, 0, 5)[0], self.s.SIGNAL_BUY)

    def test_us_needs_deep_drop_and_strong_position(self):
        self.assertEqual(self.f("SP500", -6.5, 30, None)[0], self.s.SIGNAL_BUY)
        self.assertEqual(self.f("SP500", -6.5, 2, -3)[0], self.s.SIGNAL_WAIT)
        self.assertEqual(self.f("NASDAQ100", -4.5)[0], self.s.SIGNAL_WAIT)
        self.assertEqual(self.f("SP500", -3.8)[0], self.s.SIGNAL_AVOID)

    def test_missing_drop_is_unknown(self):
        self.assertEqual(self.f("TA35", float("nan"))[0], self.s.SIGNAL_UNKNOWN)
        self.assertEqual(self.f("SP500", -7.0)[0], self.s.SIGNAL_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
