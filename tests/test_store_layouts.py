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
