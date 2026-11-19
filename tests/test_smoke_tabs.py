"""בדיקת עשן: כל טאב באתר נטען בלי חריגה - במצב בודק (עותק נקי, בלי נתונים אישיים, בלי git, בלי טלגרם),
פעם על מצב ריק ופעם עם אחזקה אחת ועסקה סגורה אחת. נתפסים כאן שברים כמו מפתח/פונקציה שנמחקו.

דורש streamlit (קיים ב-requirements) ובדרך כלל גם רשת (שליפת מחירים) - כשל רשת לא אמור להפיל טאב, וזה בדיוק מה שנבדק.
הרצה: python -m unittest tests.test_smoke_tabs -v"""
import datetime as dt
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from streamlit.testing.v1 import AppTest
except Exception:  # pragma: no cover
    AppTest = None

TABS = ("movers", "today", "portfolio", "history", "backtest")


def _cleanup_tester_files() -> None:
    for name in os.listdir(ROOT):
        if name.startswith(("alerts_tester.db", "user_tester.db")):
            try:
                os.remove(os.path.join(ROOT, name))
            except OSError:
                pass


@unittest.skipIf(AppTest is None, "streamlit.testing לא זמין")
class TabsLoadWithoutExceptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = mock.patch.dict(os.environ, {"TESTER_MODE": "1"})
        cls._env.start()
        _cleanup_tester_files()

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        _cleanup_tester_files()

    def _run_tab(self, tab):
        at = AppTest.from_file(os.path.join(ROOT, "dashboard.py"), default_timeout=180)
        if tab:
            at.session_state["active_tab"] = tab
        at.run()
        return at

    def _assert_no_exceptions(self, label):
        for tab in (None,) + TABS:
            with self.subTest(state=label, tab=tab or "home"):
                at = self._run_tab(tab)
                self.assertEqual([str(e.value)[:200] for e in at.exception], [])

    def test_empty_state(self):
        self._assert_no_exceptions("empty")

    def test_with_holding_and_closed_trade(self):
        from src import config, store
        src_db = os.path.join(ROOT, "alerts.db")
        tester_db = config._tester_db(src_db)
        conn = store.get_conn(tester_db)
        try:
            rows = conn.execute(
                "SELECT id, ticker, company_name, index_name, last_close, entry_limit, target_base, stop_loss, "
                "overreaction_score, overreaction_verdict FROM alerts "
                "WHERE index_name IN ('TA35','TA125') AND last_close > 0 ORDER BY id DESC LIMIT 2"
            ).fetchall()
            if len(rows) < 2:
                self.skipTest("אין מספיק התראות בבסיס הנתונים לבדיקה")
            hold, closed = rows[0], rows[1]
            now = dt.datetime.now().replace(microsecond=0)
            entry = float(hold[4])
            store.mark_as_bought(conn, hold[0], entry, round(5000 / entry) or 1, (now - dt.timedelta(days=2)).isoformat(), entry * 0.93)
            cl_entry = float(closed[4])
            store.save_closed_trade(conn, {
                "alert_id": closed[0], "ticker": closed[1], "company_name": closed[2], "index_name": closed[3],
                "currency": "ILS", "entry_price": cl_entry, "qty": 10, "entry_at": (now - dt.timedelta(days=5)).isoformat(),
                "exit_price": cl_entry * 1.04, "exit_at": now.isoformat(), "forecast_entry_limit": closed[5],
                "forecast_target": closed[6], "forecast_stop": closed[7], "forecast_score": closed[8],
                "forecast_verdict": closed[9], "holding_days": 5, "gross_pnl": cl_entry * 0.4,
                "net_pnl": cl_entry * 0.3, "net_pct": 3.0, "is_manual_trade": False,
            })
        finally:
            conn.close()
        self._assert_no_exceptions("with data")


@unittest.skipIf(AppTest is None, "streamlit.testing לא זמין")
class TabsLoadInSplitLayout(unittest.TestCase):
    """אותו דבר בפריסת split (DB_LAYOUT=split): אחזקה ועסקה סגורה ב-user_tester.db, וכל טאב נטען בלי חריגה."""

    @classmethod
    def setUpClass(cls):
        cls._env = mock.patch.dict(os.environ, {"TESTER_MODE": "1", "DB_LAYOUT": "split"})
        cls._env.start()
        _cleanup_tester_files()

    @classmethod
    def tearDownClass(cls):
        from src import store
        cls._env.stop()
        store.set_layout("legacy")
        _cleanup_tester_files()

    def test_with_holding_and_closed_trade(self):
        from src import config, store
        store.set_layout("split")
        tester_db = config._tester_db(os.path.join(ROOT, "alerts.db"))
        conn = store.get_conn(tester_db)
        try:
            rows = conn.execute(
                "SELECT id, ticker, company_name, index_name, last_close, entry_limit, target_base, stop_loss, "
                "overreaction_score, overreaction_verdict FROM alerts "
                "WHERE index_name IN ('TA35','TA125') AND last_close > 0 ORDER BY id DESC LIMIT 2"
            ).fetchall()
            if len(rows) < 2:
                self.skipTest("אין מספיק התראות בבסיס הנתונים לבדיקה")
            hold, closed = rows[0], rows[1]
            now = dt.datetime.now().replace(microsecond=0)
            entry = float(hold[4])
            store.mark_as_bought(conn, hold[0], entry, round(5000 / entry) or 1, (now - dt.timedelta(days=2)).isoformat(), entry * 0.93)
            cl_entry = float(closed[4])
            store.save_closed_trade(conn, {
                "alert_id": closed[0], "ticker": closed[1], "company_name": closed[2], "index_name": closed[3],
                "currency": "ILS", "entry_price": cl_entry, "qty": 10, "entry_at": (now - dt.timedelta(days=5)).isoformat(),
                "exit_price": cl_entry * 1.04, "exit_at": now.isoformat(), "forecast_entry_limit": closed[5],
                "forecast_target": closed[6], "forecast_stop": closed[7], "forecast_score": closed[8],
                "forecast_verdict": closed[9], "holding_days": 5, "gross_pnl": cl_entry * 0.4,
                "net_pnl": cl_entry * 0.3, "net_pct": 3.0, "is_manual_trade": False,
            })
        finally:
            conn.close()
        for tab in (None,) + TABS:
            with self.subTest(layout="split", tab=tab or "home"):
                at = AppTest.from_file(os.path.join(ROOT, "dashboard.py"), default_timeout=180)
                if tab:
                    at.session_state["active_tab"] = tab
                at.run()
                self.assertEqual([str(e.value)[:200] for e in at.exception], [])


if __name__ == "__main__":
    unittest.main()
