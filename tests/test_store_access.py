"""שלב 1 בתוכנית פיצול ה-DB (DB_SPLIT_PLAN.md): כל קריאה של עמודות המשתמש מטבלת alerts עוברת דרך store.read_alerts_*.
הבדיקה האחרונה שומרת על זה אוטומטית - SQL חדש שקורא עמודות משתמש ישירות ייכשל כאן, ולא יפתיע בשלב המעבר.
הרצה: python -m unittest tests.test_store_access -v"""
import ast
import glob
import os
import sys
import tempfile
import unittest

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import db_merge, store


def _seed(path: str) -> None:
    conn = store.get_conn(path)
    for ticker, date in (("AAA.TA", "2026-11-10"), ("BBB.TA", "2026-11-11"), ("CCC.TA", "2026-11-12")):
        conn.execute(
            "INSERT INTO alerts (scan_date, scan_ts, ticker, index_name, pct_change, last_close, prev_close, reason_text, "
            "entry_limit, stop_loss, target_base) VALUES (?, ?, ?, 'TA35', -4.0, 10.0, 10.4, 'x', 9.8, 9.0, 10.5)",
            (date, date + "T10:00:00", ticker))
    conn.commit()
    store.mark_as_bought(conn, 2, 9.9, 100.0, "2026-11-11T10:30:00", 9.1, is_manual_trade=True)
    conn.close()


class ReadAlertsLayer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "alerts.db")
        _seed(self.path)
        self.conn = store.get_conn(self.path)

    def tearDown(self):
        self.conn.close()

    def test_user_cols_match_merge_definition(self):
        self.assertEqual(list(store.ALERT_USER_COLS), db_merge.USER_OWNED_ALERT_COLS)

    def test_star_matches_direct_sql(self):
        direct = pd.read_sql_query("SELECT * FROM alerts ORDER BY scan_ts DESC", self.conn)
        layer = store.read_alerts_df(self.conn, order="scan_ts DESC")
        pd.testing.assert_frame_equal(direct, layer)

    def test_columns_where_params_match_direct_sql(self):
        cols = ["ticker", "scan_ts", "entry_limit", "bought", "actual_entry_price", "bought_at"]
        direct = pd.read_sql_query(
            "SELECT ticker, scan_ts, entry_limit, bought, actual_entry_price, bought_at FROM alerts "
            "WHERE entry_limit IS NOT NULL AND id != ?", self.conn, params=(1,))
        layer = store.read_alerts_df(self.conn, columns=cols, where="entry_limit IS NOT NULL AND id != ?", params=(1,))
        pd.testing.assert_frame_equal(direct, layer)

    def test_rows_variant_keeps_column_order(self):
        rows = store.read_alerts_rows(self.conn, ["id", "ticker", "bought", "is_manual_trade"], where="bought = 1")
        self.assertEqual(rows, [(2, "BBB.TA", 1, 1)])


class NoDirectUserColumnSql(unittest.TestCase):
    """SQL שנכתב כמחרוזת ב-Python וקורא מ-alerts: אסור `SELECT *` או עמודות משתמש מחוץ לשכבת הגישה."""
    ALLOWED = {"store.py", "db_merge.py", "config.py", "test_store_access.py", "test_tester_isolation.py",
               "test_smoke_tabs.py", "test_core.py", "resolve_alerts_db_conflict.py"}

    def test_no_direct_sql(self):
        files = glob.glob(os.path.join(ROOT, "src", "*.py")) + glob.glob(os.path.join(ROOT, "*.py"))
        offenders = []
        for f in files:
            if os.path.basename(f) in self.ALLOWED:
                continue
            with open(f, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and "FROM alerts" in n.value:
                    sql = n.value
                    if "SELECT *" in sql.upper() or any(c in sql for c in store.ALERT_USER_COLS):
                        offenders.append((os.path.basename(f), n.lineno, sql[:70].replace("\n", " ")))
        self.assertEqual(offenders, [], "SQL ישיר על עמודות משתמש - יש להשתמש ב-store.read_alerts_df/rows")


if __name__ == "__main__":
    unittest.main()
