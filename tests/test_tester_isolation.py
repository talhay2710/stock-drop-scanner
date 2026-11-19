"""בדיקות בידוד לאתרי הבודקים (בלי רשת): הנתונים האישיים של הבעלים לא מגיעים לעותק של הבודק בשום מצב.
מקור: ב-17.11.2026 נמצא אתר בודק שהציג אחזקות ועסקאות אמיתיות כי העותק שלו נשאר "גולמי" (קטיעה בין ההעתקה לניקוי).
הרצה: python -m unittest tests.test_tester_isolation -v"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import config, store


def _make_source(path: str) -> None:
    """מסד מקור קטן: שלוש התראות, אחת מהן אחזקה של הבעלים, ועסקה סגורה אחת של הבעלים."""
    conn = store.get_conn(path)
    for i, (ticker, date) in enumerate((("AAA.TA", "2026-11-10"), ("BBB.TA", "2026-11-11"), ("CCC.TA", "2026-11-12")), 1):
        conn.execute(
            "INSERT INTO alerts (scan_date, scan_ts, ticker, index_name, pct_change, last_close, prev_close, reason_text) "
            "VALUES (?, ?, ?, 'TA35', -4.0, 10.0, 10.4, 'x')", (date, date + "T10:00:00", ticker))
    conn.commit()
    store.mark_as_bought(conn, 1, 10.0, 100.0, "2026-11-12T10:00:00", 9.0)
    store.save_closed_trade(conn, {
        "alert_id": 2, "ticker": "BBB.TA", "company_name": "בי", "index_name": "TA35", "currency": "ILS",
        "entry_price": 10.0, "qty": 50.0, "entry_at": "2026-11-11T10:00:00", "exit_price": 11.0,
        "exit_at": "2026-11-12T10:00:00", "forecast_entry_limit": None, "forecast_target": None, "forecast_stop": None,
        "forecast_score": None, "forecast_verdict": None, "holding_days": 2, "gross_pnl": 50.0, "net_pnl": 40.0,
        "net_pct": 8.0, "is_manual_trade": False,
    })
    conn.close()


def _counts(path: str) -> tuple:
    c = sqlite3.connect(path)
    try:
        return (c.execute("SELECT COUNT(*) FROM alerts WHERE bought=1").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0])
    finally:
        c.close()


class TesterDbIsolation(unittest.TestCase):
    def setUp(self):
        # בדיקת הטאבים (Streamlit) מוחקת וטוענת מחדש את מודולי src, וה-config.yaml המקומי כבר ב-split: עובדים מול המודולים הנוכחיים
        global config, store
        import importlib
        config, store = importlib.import_module("src.config"), importlib.import_module("src.store")
        store.set_layout("legacy")  # פריסה גלובלית לתהליך - בדיקות אחרות משנות אותה
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "alerts.db")
        _make_source(self.src)
        self._root = config.ROOT_DIR
        config.ROOT_DIR = self.tmp
        config._tester_verified_src_mtime = None
        self.dst = os.path.join(self.tmp, "alerts_tester.db")

    def tearDown(self):
        config.ROOT_DIR = self._root
        config._tester_verified_src_mtime = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_build_has_no_owner_data(self):
        out = config._tester_db(self.src)
        self.assertEqual(out, self.dst)
        self.assertEqual(_counts(out), (0, 0, 0))

    def test_raw_copy_is_detected_and_rebuilt(self):
        shutil.copyfile(self.src, self.dst)  # בדיוק התקלה שקרתה: עותק גולמי שלא נוקה
        self.assertTrue(config._tester_contaminated(self.src, self.dst))
        out = config._tester_db(self.src)
        self.assertEqual(_counts(out), (0, 0, 0))

    def test_testers_own_data_survives_refresh(self):
        config._tester_db(self.src)
        c = sqlite3.connect(self.dst)
        c.execute("INSERT INTO watchlist (ticker, company_name, index_name, entry_price, added_at) "
                  "VALUES ('ZZZ.TA','זי','TA35',1.0,'2026-11-17')")
        c.commit()
        c.close()
        os.utime(self.src, (os.path.getatime(self.src), os.path.getmtime(self.src) + 100))
        config._tester_verified_src_mtime = None
        out = config._tester_db(self.src)
        self.assertEqual(_counts(out), (0, 0, 1))

    def test_new_owner_purchase_after_copy_does_not_leak(self):
        config._tester_db(self.src)
        c = sqlite3.connect(self.src)  # הבעלים קונה התראה חדשה שנוצרה אחרי יצירת העותק
        c.execute("INSERT INTO alerts (scan_date, scan_ts, ticker, index_name, pct_change, last_close, prev_close, reason_text) "
                  "VALUES ('2026-11-13','2026-11-13T10:00:00','DDD.TA','TA35',-4.0,10.0,10.4,'x')")
        new_id = c.execute("SELECT MAX(id) FROM alerts").fetchone()[0]
        c.commit()
        c.close()
        store_conn = store.get_conn(self.src)
        store.mark_as_bought(store_conn, new_id, 10.0, 10.0, "2026-11-13T11:00:00", 9.0)
        store_conn.close()
        os.utime(self.src, (os.path.getatime(self.src), os.path.getmtime(self.src) + 200))
        config._tester_verified_src_mtime = None
        out = config._tester_db(self.src)
        self.assertEqual(_counts(out), (0, 0, 0))


class TesterDbIsolationSplit(unittest.TestCase):
    """פריסת split: נתוני הבודק ב-user_tester.db; alerts_tester.db = עותק נתוני סריקה נקי (גם ממצב הסורק לאחזקות הבעלים)."""
    def setUp(self):
        # בדיקת הטאבים (Streamlit) טוענת מחדש את מודולי src; config.py מייבא את store בזמן ריצה, אז עובדים מול המודולים הנוכחיים
        global config, store
        import importlib
        config, store = importlib.import_module("src.config"), importlib.import_module("src.store")
        store.set_layout("legacy")
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "alerts.db")
        _make_source(self.src)
        from src import db_split
        self.assertEqual(db_split.install(self.src)[1], [])  # user.db של הבעלים + holding_state עם האחזקה שלו
        c = sqlite3.connect(self.src)
        c.execute("INSERT INTO price_alert_triggers (price_alert_id, triggered_at) VALUES (1, '2026-11-12T10:00:00')")
        c.commit()
        c.close()
        self._root = config.ROOT_DIR
        config.ROOT_DIR = self.tmp
        config._tester_verified_src_mtime = None
        self.dst = os.path.join(self.tmp, "alerts_tester.db")
        self.user_tester = os.path.join(self.tmp, "user_tester.db")

    def tearDown(self):
        config.ROOT_DIR = self._root
        config._tester_verified_src_mtime = None
        store.set_layout("legacy")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tester_view(self):
        store.set_layout("split")
        conn = store.get_conn(config._tester_db(self.src))
        try:
            return (len(store.get_bought_holdings(conn)), len(store.get_closed_trades(conn)), len(store.get_watchlist(conn)),
                    conn.execute("SELECT COUNT(*) FROM holding_state").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM price_alert_triggers").fetchone()[0])
        finally:
            conn.close()

    def test_fresh_split_tester_sees_nothing_of_owner(self):
        self.assertEqual(self._tester_view(), (0, 0, 0, 0, 0))
        self.assertTrue(os.path.exists(self.user_tester))
        self.assertFalse(config._tester_split_contaminated(self.dst))

    def test_raw_copy_is_rebuilt(self):
        store.set_layout("split")
        shutil.copyfile(self.src, self.dst)
        with open(self.dst + ".src", "w") as f:
            f.write(str(os.path.getmtime(self.src)))
        self.assertTrue(config._tester_split_contaminated(self.dst))
        self.assertEqual(self._tester_view(), (0, 0, 0, 0, 0))

    def test_testers_own_data_survives_refresh(self):
        self._tester_view()
        store.set_layout("split")
        conn = store.get_conn(self.dst)
        store.add_watchlist_item(conn, "ZZZ.TA", "זי", "TA35", 1.0)
        conn.close()
        os.utime(self.src, (os.path.getatime(self.src), os.path.getmtime(self.src) + 100))
        config._tester_verified_src_mtime = None
        self.assertEqual(self._tester_view(), (0, 0, 1, 0, 0))

    def test_legacy_tester_data_carried_over_at_cutover(self):
        store.set_layout("legacy")
        config._tester_db(self.src)  # עותק legacy נקי
        c = sqlite3.connect(self.dst)
        c.execute("INSERT INTO watchlist (ticker, company_name, index_name, entry_price, added_at) "
                  "VALUES ('ZZZ.TA','זי','TA35',1.0,'2026-11-17')")
        c.commit()
        c.close()
        config._tester_verified_src_mtime = None
        self.assertEqual(self._tester_view(), (0, 0, 1, 0, 0))  # עבר ל-user_tester.db

    def test_contaminated_legacy_copy_is_not_carried_over(self):
        shutil.copyfile(self.src, self.dst)  # עותק legacy גולמי עם נתוני הבעלים
        self.assertEqual(self._tester_view(), (0, 0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
