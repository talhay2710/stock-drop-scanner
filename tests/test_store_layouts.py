"""שלב 3 בתוכנית פיצול ה-DB: אותן פעולות store נותנות אותן תוצאות בשתי הפריסות (legacy / split),
ובפריסת split כתיבות המשתמש הולכות ל-user.db ולא נוגעות בקובץ הסורק. הרצה: python -m unittest tests.test_store_layouts -v"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import store


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


TRADE = {
    "alert_id": 1, "ticker": "AAA.TA", "company_name": "איי", "index_name": "TA35", "currency": "ILS", "entry_price": 10.0,
    "qty": 10.0, "entry_at": "2026-11-11T10:00:00", "exit_price": 11.0, "exit_at": "2026-11-12T10:00:00",
    "forecast_entry_limit": 9.8, "forecast_target": 10.5, "forecast_stop": 9.0, "forecast_score": 3, "forecast_verdict": "v",
    "holding_days": 2, "gross_pnl": 10.0, "net_pnl": 5.0, "net_pct": 5.0, "is_manual_trade": False,
}


class _LayoutCases:
    LAYOUT = "legacy"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "alerts.db")
        store.set_layout(self.LAYOUT)
        store.get_conn(self.path).close()  # יוצר קבצים/טבלאות

    def tearDown(self):
        store.set_layout("legacy")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_closed_trades_roundtrip(self):
        conn = store.get_conn(self.path)
        tid = store.save_closed_trade(conn, dict(TRADE))
        rows = store.get_closed_trades(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["ticker"], rows[0]["gross_pnl"], rows[0]["net_pnl"]), (tid, "AAA.TA", 10.0, 5.0))
        self.assertEqual(len(store.get_closed_trades_on_date(conn, "2026-11-12")), 1)
        self.assertEqual(store.get_closed_trades_on_date(conn, "2026-11-13"), [])
        conn.close()

    def test_watchlist_roundtrip(self):
        conn = store.get_conn(self.path)
        a = store.add_watchlist_item(conn, "AAA.TA", "איי", "TA35", 10.0)
        b = store.add_watchlist_item(conn, "BBB.TA", "בי", "TA35", 20.0)
        self.assertEqual(sorted(r["ticker"] for r in store.get_watchlist(conn)), ["AAA.TA", "BBB.TA"])
        store.remove_watchlist_item(conn, a)
        self.assertEqual([r["id"] for r in store.get_watchlist(conn)], [b])
        conn.close()

    def test_price_alert_lifecycle(self):
        conn = store.get_conn(self.path)
        p1 = store.add_price_alert(conn, "AAA.TA", "איי", "TA35", 12.0, "above")
        p2 = store.add_price_alert(conn, "BBB.TA", "בי", "TA35", 18.0, "below")
        p3 = store.add_price_alert(conn, "CCC.TA", "סי", "TA35", 9.0, "below")
        self.assertEqual(sorted(a["id"] for a in store.get_active_price_alerts(conn)), sorted([p1, p2, p3]))
        store.deactivate_price_alert(conn, p2, triggered=False)   # ביטול ע"י המשתמש
        store.deactivate_price_alert(conn, p3, triggered=True)    # הופעלה ע"י הסורק
        self.assertEqual([a["id"] for a in store.get_active_price_alerts(conn)], [p1])
        conn.close()


class LegacyLayout(_LayoutCases, unittest.TestCase):
    LAYOUT = "legacy"

    def test_no_user_db_created(self):
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "user.db")))


class SplitLayout(_LayoutCases, unittest.TestCase):
    LAYOUT = "split"

    def test_user_data_goes_to_user_db_and_not_the_scan_file(self):
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "user.db")))
        before = _sha(self.path)
        conn = store.get_conn(self.path)
        store.save_closed_trade(conn, dict(TRADE))
        store.add_watchlist_item(conn, "AAA.TA", "איי", "TA35", 10.0)
        pid = store.add_price_alert(conn, "AAA.TA", "איי", "TA35", 12.0, "above")
        store.deactivate_price_alert(conn, pid, triggered=False)  # ביטול משתמש: user.db
        conn.close()
        self.assertEqual(_sha(self.path), before, "כתיבות משתמש לא אמורות לשנות את קובץ הסורק")

    def test_scanner_trigger_goes_to_scan_file(self):
        conn = store.get_conn(self.path)
        pid = store.add_price_alert(conn, "AAA.TA", "איי", "TA35", 12.0, "above")
        conn.close()
        before_user = _sha(os.path.join(self.tmp, "user.db"))
        conn = store.get_conn(self.path)
        store.deactivate_price_alert(conn, pid, triggered=True)
        conn.close()
        self.assertEqual(_sha(os.path.join(self.tmp, "user.db")), before_user, "הפעלה ע\"י הסורק לא אמורה לשנות את user.db")
        conn = store.get_conn(self.path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM main.price_alert_triggers").fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# שלב 3ב: אחזקות (positions), מצב התראות אחזקה (holding_state) וקריאת alerts - אותן תוצאות בשתי הפריסות
# ---------------------------------------------------------------------------
def _seed_alerts(conn) -> None:
    for i, t in enumerate(("AAA.TA", "BBB.TA", "CCC.TA"), 1):
        conn.execute(
            "INSERT INTO alerts (scan_date, scan_ts, ticker, index_name, pct_change, last_close, prev_close, reason_text, "
            "entry_limit, stop_loss, target_base) VALUES (?, ?, ?, 'TA35', -4.0, 10.0, 10.4, 'x', 9.8, 9.0, 10.5)",
            (f"2026-11-1{i}", f"2026-11-1{i}T10:00:00", t))
    conn.commit()


class _HoldingCases:
    LAYOUT = "legacy"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "alerts.db")
        store.set_layout(self.LAYOUT)
        c = store.get_conn(self.path)
        _seed_alerts(c)
        c.close()

    def tearDown(self):
        store.set_layout("legacy")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _buy(self, conn):
        store.mark_as_bought(conn, 1, 10.0, 100.0, "2026-11-12T10:00:00", 9.0)
        store.mark_as_bought(conn, 2, 20.0, 50.0, "2026-11-13T10:00:00", 18.0, is_manual_trade=True)

    def test_get_bought_holdings_same_in_both_layouts(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        rows = store.get_bought_holdings(conn)
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(sorted(by_id), [1, 2])
        self.assertEqual((by_id[1]["actual_entry_price"], by_id[1]["actual_qty"], by_id[1]["holding_stop_price"], by_id[1]["is_manual_trade"]),
                         (10.0, 100.0, 9.0, 0))
        self.assertEqual(by_id[2]["is_manual_trade"], 1)
        self.assertEqual(by_id[1]["target_base"], 10.5)
        conn.close()

    def test_alert_state_updates(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        store.update_gain_alert(conn, 1, 3.5)
        store.update_stop_alert(conn, 1, True)
        store.update_target_alert(conn, 1, True)
        store.update_hold_alert(conn, 1, True)
        r = [h for h in store.get_bought_holdings(conn) if h["id"] == 1][0]
        self.assertEqual((r["last_gain_alert_pct"], r["stop_alert_active"], r["target_alert_active"], r["hold_alert_sent"]), (3.5, 1, 1, 1))
        conn.close()

    def test_update_holding_stop_price(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        store.update_holding_stop_price(conn, 1, 8.5)
        r = [h for h in store.get_bought_holdings(conn) if h["id"] == 1][0]
        self.assertEqual(r["holding_stop_price"], 8.5)
        conn.close()

    def test_sell_clears_position_and_state(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        store.update_hold_alert(conn, 1, True)
        store.unmark_as_bought(conn, 1)
        store.sync_holding_state(conn)  # בסורק: מנקה מצב של אחזקה שנמכרה (ב-legacy: no-op, unmark מאפס בעצמו)
        self.assertEqual([h["id"] for h in store.get_bought_holdings(conn)], [2])
        store.mark_as_bought(conn, 1, 11.0, 10.0, "2026-11-14T10:00:00", 10.0)  # קנייה חוזרת של אותה התראה
        store.sync_holding_state(conn)
        r = [h for h in store.get_bought_holdings(conn) if h["id"] == 1][0]
        self.assertEqual(r["stop_alert_active"], 0)
        if store.is_split():  # ב-split המצב הישן באמת נמחק (ב-legacy hold_alert_sent נשאר 1 - באג ידוע שהפיצול מתקן)
            self.assertEqual(r["hold_alert_sent"], 0)
        conn.close()

    def test_read_alerts_user_columns(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        df = store.read_alerts_df(conn, order="id")
        self.assertEqual(list(df["bought"]), [1, 1, 0])
        self.assertEqual(list(df["actual_entry_price"].fillna(-1)), [10.0, 20.0, -1])
        self.assertEqual(list(df["is_manual_trade"].fillna(0)), [0, 1, 0])
        sub = store.read_alerts_df(conn, columns=["id", "bought", "actual_entry_price", "bought_at"], where="bought_at IS NOT NULL" if not store.is_split() else "id < 3", order="id")
        self.assertEqual(list(sub["id"]), [1, 2])
        rows = store.read_alerts_rows(conn, ["id", "bought", "actual_qty"], where="id = 1")
        self.assertEqual(rows, [(1, 1, 100.0)])
        conn.close()


class HoldingsLegacy(_HoldingCases, unittest.TestCase):
    LAYOUT = "legacy"


class HoldingsSplit(_HoldingCases, unittest.TestCase):
    LAYOUT = "split"

    def test_dashboard_writes_do_not_touch_scan_file(self):
        conn = store.get_conn(self.path)
        conn.close()
        before = _sha(self.path)
        conn = store.get_conn(self.path)
        self._buy(conn)
        store.update_holding_stop_price(conn, 1, 8.5)
        store.unmark_as_bought(conn, 2)
        conn.close()
        self.assertEqual(_sha(self.path), before, "קנייה/מכירה/סטופ של המשתמש חייבים ללכת ל-user.db בלבד")

    def test_scanner_state_writes_do_not_touch_user_file(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        conn.close()
        before = _sha(os.path.join(self.tmp, "user.db"))
        conn = store.get_conn(self.path)
        store.update_gain_alert(conn, 1, 3.5)
        store.update_stop_alert(conn, 1, True)
        store.sync_holding_state(conn)
        conn.close()
        self.assertEqual(_sha(os.path.join(self.tmp, "user.db")), before, "מצב ההתראות הוא של הסורק ואסור שישנה את user.db")

    def test_sync_removes_state_without_position(self):
        conn = store.get_conn(self.path)
        self._buy(conn)
        store.update_hold_alert(conn, 1, True)
        store.unmark_as_bought(conn, 1)
        res = store.sync_holding_state(conn)
        self.assertEqual(res["removed"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM main.holding_state WHERE alert_id = 1").fetchone()[0], 0)
        conn.close()
