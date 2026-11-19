"""שלב 2 בתוכנית פיצול ה-DB (DB_SPLIT_PLAN.md): מיגרציה *לא הרסנית* מ-alerts.db לשני קבצים עם כותב יחיד.

  user.db        (כותב יחיד: פעולות המשתמש בדשבורד)
    positions    אחת לכל אחזקה פתוחה (alert_id PK) - מחליפה את עמודות bought/actual_*/holding_stop_price/is_manual_trade ב-alerts
    alert_flags  alert_id -> is_manual, לכל התראה שסומנה כעסקה ידנית (גם כשהאחזקה כבר נסגרה) - לצורך החרגה מהבדיקה הקדימה
    closed_trades, watchlist   עותק מדויק (אותם id-ים ואותן עמודות)
    price_alerts הגדרות בלבד: id, ticker, ..., target_price, direction, created_at, cancelled
    meta         גרסת סכמה, זמן מיגרציה, טביעת אצבע של המקור

  scan_state.db  (יעבור ל-scan.db בשלב 5; כותב יחיד: הסורק)
    holding_state(alert_id PK, last_gain_alert_pct, stop_alert_active, target_alert_active, hold_alert_sent) - רק לאחזקות פתוחות
    price_alert_triggers(price_alert_id PK, triggered_at)

הסקריפט רק קורא את alerts.db (נפתח לקריאה בלבד) וכותב קבצי פלט חדשים בתיקייה נפרדת. אף קורא עדיין לא משתמש בקבצים האלה.
הרצה: python -m src.db_split <alerts.db> <out_dir>   (מדפיס דוח אימות; קוד יציאה 1 אם האימות נכשל)

דטרמיניסטי: אותו מקור -> אותו תוכן (הרצה חוזרת בונה מחדש, לא מצטברת)."""
import hashlib
import os
import sqlite3
import sys

SCHEMA_VERSION = 1

USER_SCHEMA = """
CREATE TABLE positions (
    alert_id INTEGER PRIMARY KEY,
    entry_price REAL NOT NULL,
    qty REAL NOT NULL,
    bought_at TEXT,
    stop_price REAL,
    is_manual INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE alert_flags (
    alert_id INTEGER PRIMARY KEY,
    is_manual INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE price_alerts (
    id INTEGER PRIMARY KEY,
    ticker TEXT, company_name TEXT, index_name TEXT,
    target_price REAL, direction TEXT, created_at TEXT,
    cancelled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

SCAN_STATE_SCHEMA = """
CREATE TABLE holding_state (
    alert_id INTEGER PRIMARY KEY,
    last_gain_alert_pct REAL,
    stop_alert_active INTEGER NOT NULL DEFAULT 0,
    target_alert_active INTEGER NOT NULL DEFAULT 0,
    hold_alert_sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE price_alert_triggers (
    price_alert_id INTEGER PRIMARY KEY,
    triggered_at TEXT NOT NULL
);
"""


def _ro(path: str) -> sqlite3.Connection:
    uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def fingerprint(conn: sqlite3.Connection) -> str:
    """טביעת אצבע של נתוני המשתמש במקור (לא של כל הקובץ - הסורק משנה אותו כל 5 דקות)."""
    h = hashlib.sha256()
    for q in (
        "SELECT id, bought, actual_entry_price, actual_qty, bought_at, holding_stop_price, is_manual_trade, "
        "last_gain_alert_pct, stop_alert_active, target_alert_active, hold_alert_sent FROM alerts "
        "WHERE bought = 1 OR is_manual_trade = 1 ORDER BY id",
        "SELECT * FROM closed_trades ORDER BY id",
        "SELECT * FROM watchlist ORDER BY id",
        "SELECT * FROM price_alerts ORDER BY id",
    ):
        for row in conn.execute(q):
            h.update(repr(row).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> int:
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
    col_list = ", ".join(cols)
    dst.execute(f"CREATE TABLE {table} ({', '.join(c + ' ' + t for c, t in [(r[1], r[2] or '') for r in src.execute(f'PRAGMA table_info({table})')])}, PRIMARY KEY (id))"
                if "id" in cols else f"CREATE TABLE {table} ({col_list})")
    rows = src.execute(f"SELECT {col_list} FROM {table} ORDER BY id").fetchall()
    dst.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({', '.join('?' for _ in cols)})", rows)
    return len(rows)


def migrate(src_path: str, out_dir: str) -> dict:
    """בונה user.db ו-scan_state.db חדשים ב-out_dir (מחליף קיימים). מחזיר ספירות."""
    os.makedirs(out_dir, exist_ok=True)
    user_path, state_path = os.path.join(out_dir, "user.db"), os.path.join(out_dir, "scan_state.db")
    tmp_user, tmp_state = user_path + ".new", state_path + ".new"
    for p in (tmp_user, tmp_state):
        if os.path.exists(p):
            os.remove(p)
    src = _ro(src_path)
    counts = {}
    try:
        u = sqlite3.connect(tmp_user)
        s = sqlite3.connect(tmp_state)
        try:
            u.executescript(USER_SCHEMA)
            s.executescript(SCAN_STATE_SCHEMA)
            # positions + holding_state: אחזקות פתוחות בלבד
            held = src.execute(
                "SELECT id, actual_entry_price, actual_qty, bought_at, holding_stop_price, COALESCE(is_manual_trade, 0), "
                "last_gain_alert_pct, COALESCE(stop_alert_active, 0), COALESCE(target_alert_active, 0), COALESCE(hold_alert_sent, 0) "
                "FROM alerts WHERE bought = 1 ORDER BY id").fetchall()
            u.executemany("INSERT INTO positions (alert_id, entry_price, qty, bought_at, stop_price, is_manual) VALUES (?, ?, ?, ?, ?, ?)",
                          [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in held])
            s.executemany("INSERT INTO holding_state (alert_id, last_gain_alert_pct, stop_alert_active, target_alert_active, hold_alert_sent) "
                          "VALUES (?, ?, ?, ?, ?)", [(r[0], r[6], r[7], r[8], r[9]) for r in held])
            counts["positions"] = len(held)
            # דגלי "ידני" גם להתראות שהאחזקה שלהן כבר נסגרה
            manual = src.execute("SELECT id FROM alerts WHERE is_manual_trade = 1 ORDER BY id").fetchall()
            u.executemany("INSERT INTO alert_flags (alert_id, is_manual) VALUES (?, 1)", manual)
            counts["alert_flags"] = len(manual)
            # עותקים מדויקים
            counts["closed_trades"] = _copy_table(src, u, "closed_trades")
            counts["watchlist"] = _copy_table(src, u, "watchlist")
            # התראות מחיר: הגדרה (user.db) מול הפעלה (scan_state.db)
            pas = src.execute("SELECT id, ticker, company_name, index_name, target_price, direction, created_at, triggered_at, active "
                              "FROM price_alerts ORDER BY id").fetchall()
            u.executemany(
                "INSERT INTO price_alerts (id, ticker, company_name, index_name, target_price, direction, created_at, cancelled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], 1 if (r[8] == 0 and r[7] is None) else 0) for r in pas])
            s.executemany("INSERT INTO price_alert_triggers (price_alert_id, triggered_at) VALUES (?, ?)",
                          [(r[0], r[7]) for r in pas if r[7] is not None])
            counts["price_alerts"] = len(pas)
            counts["price_alert_triggers"] = sum(1 for r in pas if r[7] is not None)
            u.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                          [("schema_version", str(SCHEMA_VERSION)), ("source_fingerprint", fingerprint(src))])
            u.commit()
            s.commit()
        finally:
            u.close()
            s.close()
    finally:
        src.close()
    os.replace(tmp_user, user_path)
    os.replace(tmp_state, state_path)
    return counts


def verify(src_path: str, out_dir: str) -> list[str]:
    """משווה את הפלט למקור. מחזיר רשימת הבדלים (ריקה = תקין)."""
    problems: list[str] = []
    src = _ro(src_path)
    u = sqlite3.connect(os.path.join(out_dir, "user.db"))
    s = sqlite3.connect(os.path.join(out_dir, "scan_state.db"))
    try:
        # אחזקות
        held = src.execute("SELECT id, actual_entry_price, actual_qty, bought_at, holding_stop_price, COALESCE(is_manual_trade, 0) "
                           "FROM alerts WHERE bought = 1 ORDER BY id").fetchall()
        pos = u.execute("SELECT alert_id, entry_price, qty, bought_at, stop_price, is_manual FROM positions ORDER BY alert_id").fetchall()
        if held != pos:
            problems.append(f"positions differ: source {len(held)} rows vs {len(pos)}")
        st_src = src.execute("SELECT id, last_gain_alert_pct, COALESCE(stop_alert_active, 0), COALESCE(target_alert_active, 0), "
                             "COALESCE(hold_alert_sent, 0) FROM alerts WHERE bought = 1 ORDER BY id").fetchall()
        st_out = s.execute("SELECT alert_id, last_gain_alert_pct, stop_alert_active, target_alert_active, hold_alert_sent "
                           "FROM holding_state ORDER BY alert_id").fetchall()
        if st_src != st_out:
            problems.append("holding_state differs from source")
        # דגלי ידני
        m_src = [r[0] for r in src.execute("SELECT id FROM alerts WHERE is_manual_trade = 1 ORDER BY id")]
        m_out = [r[0] for r in u.execute("SELECT alert_id FROM alert_flags ORDER BY alert_id")]
        if m_src != m_out:
            problems.append("manual flags differ")
        # עותקים מדויקים
        for t in ("closed_trades", "watchlist"):
            cols = ", ".join(r[1] for r in src.execute(f"PRAGMA table_info({t})"))
            a = src.execute(f"SELECT {cols} FROM {t} ORDER BY id").fetchall()
            b = u.execute(f"SELECT {cols} FROM {t} ORDER BY id").fetchall()
            if a != b:
                problems.append(f"{t} differ: {len(a)} vs {len(b)} rows")
        # התראות מחיר
        pa_src = src.execute("SELECT id, ticker, company_name, index_name, target_price, direction, created_at, triggered_at, active "
                             "FROM price_alerts ORDER BY id").fetchall()
        pa_out = u.execute("SELECT id, ticker, company_name, index_name, target_price, direction, created_at, cancelled "
                           "FROM price_alerts ORDER BY id").fetchall()
        trig = dict(s.execute("SELECT price_alert_id, triggered_at FROM price_alert_triggers"))
        for r_src, r_out in zip(pa_src, pa_out):
            if r_src[:7] != r_out[:7]:
                problems.append(f"price_alert {r_src[0]}: definition differs")
            was_active = (r_src[8] == 1)
            # "פעילה" במקור = לא בוטלה ואין טריגר
            now_active = (r_out[7] == 0 and r_src[0] not in trig)
            if was_active != now_active:
                problems.append(f"price_alert {r_src[0]}: active state differs ({was_active} vs {now_active})")
            if trig.get(r_src[0]) != r_src[7]:
                problems.append(f"price_alert {r_src[0]}: trigger time differs")
        if len(pa_src) != len(pa_out):
            problems.append("price_alerts count differs")
        # טביעת אצבע
        fp = u.execute("SELECT value FROM meta WHERE key = 'source_fingerprint'").fetchone()
        if not fp or fp[0] != fingerprint(src):
            problems.append("source fingerprint mismatch (source changed during migration?)")
    finally:
        src.close()
        u.close()
        s.close()
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m src.db_split <alerts.db> <out_dir>")
        return 2
    counts = migrate(argv[1], argv[2])
    problems = verify(argv[1], argv[2])
    print("migrated:", counts)
    if problems:
        print("VERIFICATION FAILED:")
        for p in problems:
            print(" -", p)
        return 1
    print("verification OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
