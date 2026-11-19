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
מעבר (שלב 5): python -m src.db_split install <alerts.db>   (user.db ליד alerts.db + טבלאות מצב הסורק; ר' install())

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


# יצירה לפי דרישה (IF NOT EXISTS) - כש-store.get_conn מתחבר בפריסת split: user.db כולל גם closed_trades ו-watchlist (בסכמה זהה ל-store.SCHEMA)
USER_DDL_IF_NOT_EXISTS = """
CREATE TABLE IF NOT EXISTS positions (
    alert_id INTEGER PRIMARY KEY, entry_price REAL NOT NULL, qty REAL NOT NULL, bought_at TEXT, stop_price REAL,
    is_manual INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alert_flags (alert_id INTEGER PRIMARY KEY, is_manual INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, company_name TEXT, index_name TEXT, target_price REAL, direction TEXT,
    created_at TEXT, cancelled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS closed_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER, ticker TEXT NOT NULL, company_name TEXT, index_name TEXT, currency TEXT,
    entry_price REAL, qty REAL, entry_at TEXT, exit_price REAL, exit_at TEXT, forecast_entry_limit REAL, forecast_target REAL,
    forecast_stop REAL, forecast_score INTEGER, forecast_verdict TEXT, holding_days INTEGER, gross_pnl REAL, net_pnl REAL,
    net_pct REAL, is_manual_trade INTEGER DEFAULT 0, closed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, company_name TEXT, index_name TEXT, entry_price REAL NOT NULL,
    added_at TEXT NOT NULL
);
"""
SCAN_STATE_DDL_IF_NOT_EXISTS = SCAN_STATE_SCHEMA.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ")

USER_TABLES = ("positions", "alert_flags", "price_alerts", "closed_trades", "watchlist")


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


def _rows(path: str, table: str) -> list[tuple]:
    c = sqlite3.connect(path)
    try:
        return c.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    finally:
        c.close()


def _norm(v):
    """NaN/None והבדלי int/float (pandas) לא נחשבים הבדל."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
        return int(v)
    return v.item() if hasattr(v, "item") else v


def layout_views(scan_path: str, layout: str) -> dict:
    """מה שהאפליקציה רואה (דרך store) בפריסה נתונה: אחזקות, עסקאות סגורות, מעקב, התראות מחיר פעילות, וכל טבלת alerts."""
    from . import store
    prev = store.layout()
    store.set_layout(layout)
    conn = store.get_conn(scan_path)
    try:
        df = store.read_alerts_df(conn, order="id")
        # מצב התראות אחזקה נקרא רק דרך get_bought_holdings (סורק). ב-legacy נשארות שאריות על אחזקות שכבר נמכרו; ב-split הן לא
        # מועברות בכוונה (אחזקה חדשה מתחילה נקי) - אז משווים את העמודות האלה רק לאחזקות פתוחות.
        held = df["bought"].fillna(0).astype(int) == 1
        for col in ("last_gain_alert_pct", "stop_alert_active", "target_alert_active", "hold_alert_sent"):
            if col in df.columns:
                df[col] = df[col].astype(object).where(held, None)
        cols = sorted(df.columns)
        return {
            "holdings": sorted([{k: _norm(v) for k, v in d.items()} for d in store.get_bought_holdings(conn)], key=lambda d: d["id"]),
            "closed_trades": [{k: _norm(v) for k, v in d.items()} for d in sorted(store.get_closed_trades(conn), key=lambda d: d["id"])],
            "watchlist": sorted([{k: _norm(v) for k, v in d.items()} for d in store.get_watchlist(conn)], key=lambda d: d["id"]),
            "active_price_alerts": sorted([{k: _norm(v) for k, v in d.items()} for d in store.get_active_price_alerts(conn)],
                                          key=lambda d: d["id"]),
            "alerts": [tuple(_norm(v) for v in row) for row in df[cols].itertuples(index=False, name=None)],
        }
    finally:
        conn.close()
        store.set_layout(prev)


def install(alerts_path: str) -> tuple[dict, list[str]]:
    """שלב 5 (DB_SPLIT_PLAN.md 12.א.3): מכין את הקבצים לפריסת split, ליד alerts.db:
      1. migrate + verify לתיקייה זמנית;
      2. user.db ליד alerts.db (אם כבר קיים: רק אם זהה בדיוק - אחרת עוצרים, לעולם לא דורסים נתוני משתמש);
      3. holding_state + price_alert_triggers לתוך alerts.db (שהופך ל-scan.db). עמודות ה-legacy נשארות (חזרה אחורה עד שלב 7);
      4. אימות סופי: מה שהאפליקציה רואה ב-legacy זהה למה שהיא רואה ב-split.
    אידמפוטנטי: הרצה חוזרת על אותו מקור לא משנה כלום. מחזיר (ספירות, בעיות); בעיות = לא נכתב כלום או שהאימות הסופי נכשל."""
    import shutil
    import tempfile
    alerts_path = os.path.abspath(alerts_path)
    user_path = os.path.join(os.path.dirname(alerts_path), "user.db")
    out = tempfile.mkdtemp(prefix="db_split_install_")
    try:
        counts = migrate(alerts_path, out)
        problems = verify(alerts_path, out)
        if problems:
            return counts, problems
        new_user, new_state = os.path.join(out, "user.db"), os.path.join(out, "scan_state.db")
        # בדיקות לפני כל כתיבה
        user_exists = os.path.exists(user_path)
        if user_exists:
            for t in USER_TABLES + ("meta",):
                if _rows(user_path, t) != _rows(new_user, t):
                    return counts, [f"user.db already exists and differs ({t}) - refusing to overwrite user data"]
        c = sqlite3.connect(alerts_path)
        try:
            c.executescript(SCAN_STATE_DDL_IF_NOT_EXISTS)
            fill = []
            for t in ("holding_state", "price_alert_triggers"):
                have, want = c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall(), _rows(new_state, t)
                if have and have != want:
                    return counts, [f"{t} already exists in alerts.db and differs - refusing to overwrite scanner state"]
                if not have and want:
                    fill.append((t, want))
            # כתיבה
            if not user_exists:
                shutil.copyfile(new_user, user_path + ".new")
                os.replace(user_path + ".new", user_path)
            for t, rows in fill:
                c.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' for _ in rows[0])})", rows)
            c.commit()
        finally:
            c.close()
        legacy, split = layout_views(alerts_path, "legacy"), layout_views(alerts_path, "split")
        for k in legacy:
            if legacy[k] != split[k]:
                diff = sum(1 for a, b in zip(legacy[k], split[k]) if a != b) + abs(len(legacy[k]) - len(split[k]))
                problems.append(f"after install, {k} differs between legacy and split ({diff} rows)")
        counts["installed_user_db"] = 0 if user_exists else 1
        counts["state_tables_filled"] = len(fill)
        return counts, problems
    finally:
        shutil.rmtree(out, ignore_errors=True)


def rollback(alerts_path: str) -> tuple[dict, list[str]]:
    """חזרה אחורה (DB_SPLIT_PLAN.md 12.ג): כותב את מצב user.db (+ מצב הסורק מ-holding_state/price_alert_triggers) חזרה
    לעמודות/טבלאות ה-legacy שב-alerts.db, כך שאחרי החזרת המתג ל-legacy לא הולכת לאיבוד אף פעולת משתמש שבוצעה אחרי המעבר.
    עובד בטרנזקציה אחת; אחריה אימות הלוך-חזור: migrate מה-legacy המעודכן חייב לתת בדיוק את user.db ואת מצב הסורק, ו-store
    חייב לראות אותו דבר בשתי הפריסות. user.db לא משתנה. מחזיר (ספירות, בעיות)."""
    import shutil
    import tempfile
    alerts_path = os.path.abspath(alerts_path)
    user_path = os.path.join(os.path.dirname(alerts_path), "user.db")
    if not os.path.exists(user_path):
        return {}, [f"no user.db next to {alerts_path}"]
    c = sqlite3.connect(alerts_path)
    counts: dict = {}
    try:
        c.execute("ATTACH DATABASE ? AS u", (user_path,))
        c.executescript(SCAN_STATE_DDL_IF_NOT_EXISTS)
        c.execute("BEGIN")
        # אחזקות שנסגרו אחרי המעבר (bought=1 קפוא ב-legacy ואין position): איפוס כמו unmark_as_bought ב-legacy
        counts["unmarked"] = c.execute(
            "UPDATE alerts SET bought = 0, actual_entry_price = NULL, actual_qty = NULL, bought_at = NULL, "
            "last_gain_alert_pct = NULL, stop_alert_active = 0, holding_stop_price = NULL "
            "WHERE bought = 1 AND id NOT IN (SELECT alert_id FROM u.positions)").rowcount
        # אחזקות פתוחות: מ-positions + מצב הסורק
        counts["positions"] = c.execute(
            "UPDATE alerts SET bought = 1, "
            "actual_entry_price = (SELECT entry_price FROM u.positions p WHERE p.alert_id = alerts.id), "
            "actual_qty = (SELECT qty FROM u.positions p WHERE p.alert_id = alerts.id), "
            "bought_at = (SELECT bought_at FROM u.positions p WHERE p.alert_id = alerts.id), "
            "holding_stop_price = (SELECT stop_price FROM u.positions p WHERE p.alert_id = alerts.id), "
            "last_gain_alert_pct = (SELECT last_gain_alert_pct FROM main.holding_state h WHERE h.alert_id = alerts.id), "
            "stop_alert_active = COALESCE((SELECT stop_alert_active FROM main.holding_state h WHERE h.alert_id = alerts.id), 0), "
            "target_alert_active = COALESCE((SELECT target_alert_active FROM main.holding_state h WHERE h.alert_id = alerts.id), 0), "
            "hold_alert_sent = COALESCE((SELECT hold_alert_sent FROM main.holding_state h WHERE h.alert_id = alerts.id), 0) "
            "WHERE id IN (SELECT alert_id FROM u.positions)").rowcount
        # דגל ידני: מקור אחד - alert_flags (כולל אחזקות פתוחות ידניות) או position ידני
        c.execute("UPDATE alerts SET is_manual_trade = CASE WHEN id IN (SELECT alert_id FROM u.alert_flags) "
                  "OR id IN (SELECT alert_id FROM u.positions WHERE is_manual = 1) THEN 1 ELSE 0 END "
                  "WHERE COALESCE(is_manual_trade, 0) != CASE WHEN id IN (SELECT alert_id FROM u.alert_flags) "
                  "OR id IN (SELECT alert_id FROM u.positions WHERE is_manual = 1) THEN 1 ELSE 0 END")
        for t in ("closed_trades", "watchlist"):
            cols = ", ".join(r[1] for r in c.execute(f"PRAGMA main.table_info({t})"))
            c.execute(f"DELETE FROM main.{t}")
            counts[t] = c.execute(f"INSERT INTO main.{t} ({cols}) SELECT {cols} FROM u.{t}").rowcount
        c.execute("DELETE FROM main.price_alerts")
        counts["price_alerts"] = c.execute(
            "INSERT INTO main.price_alerts (id, ticker, company_name, index_name, target_price, direction, created_at, triggered_at, active) "
            "SELECT p.id, p.ticker, p.company_name, p.index_name, p.target_price, p.direction, p.created_at, t.triggered_at, "
            "CASE WHEN p.cancelled = 0 AND t.price_alert_id IS NULL THEN 1 ELSE 0 END "
            "FROM u.price_alerts p LEFT JOIN main.price_alert_triggers t ON t.price_alert_id = p.id").rowcount
        c.execute("COMMIT")
    except Exception as e:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        return counts, [f"rollback failed, nothing written: {e!r}"]
    finally:
        c.close()
    # אימות הלוך-חזור
    problems: list[str] = []
    out = tempfile.mkdtemp(prefix="db_split_rollback_")
    try:
        migrate(alerts_path, out)
        for t in USER_TABLES:
            a, b = _rows(os.path.join(out, "user.db"), t), _rows(user_path, t)
            if t == "price_alerts":  # "בוטלה" מול "הופעלה" לא הפיך כשגם וגם; המצב הפעיל נבדק ב-layout_views למטה
                a, b = [r[:7] for r in a], [r[:7] for r in b]
            if a != b:
                problems.append(f"round-trip: {t} differs from user.db")
        for t in ("holding_state", "price_alert_triggers"):
            want = _rows(os.path.join(out, "scan_state.db"), t)
            have = _rows(alerts_path, t)
            if t == "holding_state":  # רק לאחזקות פתוחות; אחזקה בלי שורה (הסורק עוד לא סנכרן) = מצב ריק
                held = sorted(r[0] for r in _rows(user_path, "positions"))
                empty = (None, 0, 0, 0)
                hv = {r[0]: (r[1], r[2] or 0, r[3] or 0, r[4] or 0) for r in have}
                wv = {r[0]: (r[1], r[2] or 0, r[3] or 0, r[4] or 0) for r in want}
                have = [hv.get(i, empty) for i in held]
                want = [wv.get(i, empty) for i in held]
            if want != have:
                problems.append(f"round-trip: {t} differs")
        legacy, split = layout_views(alerts_path, "legacy"), layout_views(alerts_path, "split")
        for k in legacy:
            if legacy[k] != split[k]:
                problems.append(f"after rollback, {k} differs between legacy and split")
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return counts, problems


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "rollback":
        counts, problems = rollback(argv[2])
        print("rollback:", counts)
        if problems:
            print("ROLLBACK FAILED:")
            for p in problems:
                print(" -", p)
            return 1
        print("rollback OK")
        return 0
    if len(argv) == 3 and argv[1] == "install":
        counts, problems = install(argv[2])
        print("install:", counts)
        if problems:
            print("INSTALL FAILED:")
            for p in problems:
                print(" -", p)
            return 1
        print("install OK")
        return 0
    if len(argv) != 3:
        print("usage: python -m src.db_split <alerts.db> <out_dir>   |   python -m src.db_split install <alerts.db>")
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
