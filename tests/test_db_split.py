"""שלב 2 בתוכנית פיצול ה-DB: המיגרציה ל-user.db / scan_state.db נאמנה למקור, אידמפוטנטית, ולא נוגעת במקור.
הרצה: python -m unittest tests.test_db_split -v"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import db_split, store


def _seed(path: str) -> None:
    conn = store.get_conn(path)
    for i, t in enumerate(("AAA.TA", "BBB.TA", "CCC.TA", "DDD.TA"), 1):
        conn.execute(
            "INSERT INTO alerts (scan_date, scan_ts, ticker, index_name, pct_change, last_close, prev_close, reason_text) "
            "VALUES (?, ?, ?, 'TA35', -4.0, 10.0, 10.4, 'x')", (f"2026-11-1{i}", f"2026-11-1{i}T10:00:00", t))
    conn.commit()
    store.mark_as_bought(conn, 1, 10.0, 100.0, "2026-11-12T10:00:00", 9.0)
    store.mark_as_bought(conn, 2, 20.0, 50.0, "2026-11-13T10:00:00", 18.0, is_manual_trade=True)
    store.update_stop_alert_state(conn, 1, True) if hasattr(store, "update_stop_alert_state") else None
    conn.execute("UPDATE alerts SET last_gain_alert_pct = 3.5, stop_alert_active = 1, hold_alert_sent = 1 WHERE id = 1")
    conn.execute("UPDATE alerts SET is_manual_trade = 1 WHERE id = 3")  # התראה שסומנה ידנית ואינה אחזקה
    store.save_closed_trade(conn, {
        "alert_id": 4, "ticker": "DDD.TA", "company_name": "די", "index_name": "TA35", "currency": "ILS", "entry_price": 10.0,
        "qty": 10.0, "entry_at": "2026-11-11T10:00:00", "exit_price": 11.0, "exit_at": "2026-11-12T10:00:00",
        "forecast_entry_limit": 9.8, "forecast_target": 10.5, "forecast_stop": 9.0, "forecast_score": 3, "forecast_verdict": "v",
        "holding_days": 2, "gross_pnl": 10.0, "net_pnl": 5.0, "net_pct": 5.0, "is_manual_trade": False,
    })
    store.add_watchlist_item(conn, "AAA.TA", "איי", "TA35", 10.0)
    store.add_price_alert(conn, "AAA.TA", "איי", "TA35", 12.0, "above")      # פעילה
    store.add_price_alert(conn, "BBB.TA", "בי", "TA35", 18.0, "below")       # תבוטל
    store.add_price_alert(conn, "CCC.TA", "סי", "TA35", 9.0, "below")        # תופעל
    conn.commit()
    ids = [r[0] for r in conn.execute("SELECT id FROM price_alerts ORDER BY id")]
    conn.execute("UPDATE price_alerts SET active = 0 WHERE id = ?", (ids[1],))
    conn.execute("UPDATE price_alerts SET active = 0, triggered_at = '2026-11-14T11:00:00' WHERE id = ?", (ids[2],))
    conn.commit()
    conn.close()


def _dump(db_path: str) -> dict:
    c = sqlite3.connect(db_path)
    try:
        return {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for (t,) in
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}
    finally:
        c.close()


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class MigrationFidelity(unittest.TestCase):
    def setUp(self):
        store.set_layout("legacy")  # פריסה גלובלית לתהליך - בדיקות אחרות משנות אותה
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "alerts.db")
        self.out = os.path.join(self.tmp, "out")
        _seed(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_migrates_and_verifies(self):
        counts = db_split.migrate(self.src, self.out)
        self.assertEqual(db_split.verify(self.src, self.out), [])
        self.assertEqual((counts["positions"], counts["alert_flags"], counts["closed_trades"], counts["watchlist"]), (2, 2, 1, 1))
        u = sqlite3.connect(os.path.join(self.out, "user.db"))
        self.assertEqual(u.execute("SELECT alert_id, entry_price, qty, stop_price, is_manual FROM positions ORDER BY alert_id").fetchall(),
                         [(1, 10.0, 100.0, 9.0, 0), (2, 20.0, 50.0, 18.0, 1)])
        self.assertEqual([r[0] for r in u.execute("SELECT alert_id FROM alert_flags ORDER BY alert_id")], [2, 3])  # גם התראה 3 שאינה אחזקה
        self.assertEqual([r[0] for r in u.execute("SELECT cancelled FROM price_alerts ORDER BY id")], [0, 1, 0])  # פעילה / בוטלה / הופעלה (לא בוטלה)
        s = sqlite3.connect(os.path.join(self.out, "scan_state.db"))
        self.assertEqual(s.execute("SELECT alert_id, last_gain_alert_pct, stop_alert_active, hold_alert_sent FROM holding_state WHERE alert_id = 1").fetchone(),
                         (1, 3.5, 1, 1))
        self.assertEqual(s.execute("SELECT triggered_at FROM price_alert_triggers").fetchall(), [("2026-11-14T11:00:00",)])

    def test_source_is_not_modified(self):
        before = _sha(self.src)
        db_split.migrate(self.src, self.out)
        self.assertEqual(_sha(self.src), before)

    def test_idempotent(self):
        db_split.migrate(self.src, self.out)
        first = {n: _dump(os.path.join(self.out, n)) for n in ("user.db", "scan_state.db")}
        db_split.migrate(self.src, self.out)
        second = {n: _dump(os.path.join(self.out, n)) for n in ("user.db", "scan_state.db")}
        self.assertEqual(first, second)

    def test_verify_detects_tampering(self):
        db_split.migrate(self.src, self.out)
        u = sqlite3.connect(os.path.join(self.out, "user.db"))
        u.execute("UPDATE positions SET qty = qty + 1 WHERE alert_id = 1")
        u.commit()
        u.close()
        self.assertTrue(db_split.verify(self.src, self.out))

    def test_sold_position_state_is_not_carried(self):
        c = sqlite3.connect(self.src)
        c.execute("UPDATE alerts SET bought = 0 WHERE id = 1")  # נמכרה: המצב הישן (hold_alert_sent וכו') לא עובר
        c.commit()
        c.close()
        db_split.migrate(self.src, self.out)
        s = sqlite3.connect(os.path.join(self.out, "scan_state.db"))
        self.assertEqual([r[0] for r in s.execute("SELECT alert_id FROM holding_state")], [2])


@unittest.skipUnless(os.path.exists(os.path.join(ROOT, "alerts.db")), "אין alerts.db מקומי")
class RealDataSnapshot(unittest.TestCase):
    def test_real_alerts_db_copy(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "alerts.db")
            shutil.copyfile(os.path.join(ROOT, "alerts.db"), src)
            db_split.migrate(src, os.path.join(tmp, "out"))
            self.assertEqual(db_split.verify(src, os.path.join(tmp, "out")), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
