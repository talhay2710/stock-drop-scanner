"""אחסון התראות ב-SQLite מקומי - משמש גם לדדופ יומי וגם כמקור נתונים לדשבורד."""
import sqlite3
import datetime as dt
import json

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date TEXT NOT NULL,
    scan_ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company_name TEXT,
    index_name TEXT,
    pct_change REAL,
    last_close REAL,
    prev_close REAL,
    reason_text TEXT,
    reasons_json TEXT,
    headlines_json TEXT,
    overreaction_verdict TEXT,
    overreaction_score INTEGER,
    entry_limit REAL,
    target_base REAL,
    stop_loss REAL,
    net_result_json TEXT,
    UNIQUE(scan_date, ticker)
);
CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    company_name TEXT,
    index_name TEXT,
    target_price REAL NOT NULL,
    direction TEXT NOT NULL,
    created_at TEXT NOT NULL,
    triggered_at TEXT,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS summary_log (
    kind TEXT NOT NULL,
    sent_date TEXT NOT NULL,
    PRIMARY KEY (kind, sent_date)
);
CREATE TABLE IF NOT EXISTS closed_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER,
    ticker TEXT NOT NULL,
    company_name TEXT,
    index_name TEXT,
    currency TEXT,
    entry_price REAL,
    qty REAL,
    entry_at TEXT,
    exit_price REAL,
    exit_at TEXT,
    forecast_entry_limit REAL,
    forecast_target REAL,
    forecast_stop REAL,
    forecast_score INTEGER,
    forecast_verdict TEXT,
    holding_days INTEGER,
    gross_pnl REAL,
    net_pnl REAL,
    net_pct REAL,
    is_manual_trade INTEGER DEFAULT 0,
    closed_at TEXT NOT NULL
);
"""


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for column_def in (
        "company_name TEXT", "outcome TEXT", "sector TEXT", "telegram_message_id INTEGER",
        "bought INTEGER DEFAULT 0", "actual_entry_price REAL", "actual_qty REAL", "bought_at TEXT",
        "last_gain_alert_pct REAL", "stop_alert_active INTEGER DEFAULT 0", "holding_stop_price REAL",
        "target_alert_active INTEGER DEFAULT 0",
        "quality_tier TEXT", "quality_score INTEGER", "quality_flags_json TEXT", "rebound_tier TEXT",
        "is_manual_trade INTEGER DEFAULT 0", "last_close_date TEXT",
        "zscore REAL", "rsi REAL", "volume_ratio REAL", "vix_level REAL", "intraday_recovery_pct REAL",
    ):
        try:
            conn.execute(f"ALTER TABLE alerts ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass  # העמודה כבר קיימת (מסד נתונים ישן יותר)
    try:
        conn.execute("ALTER TABLE closed_trades ADD COLUMN is_manual_trade INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # העמודה כבר קיימת (מסד נתונים ישן יותר)
    conn.commit()
    return conn


def was_summary_sent(conn: sqlite3.Connection, kind: str, sent_date: str) -> bool:
    """נשלחה כבר הודעת סיכום (יומי/בוקר/שבועי) בתאריך הזה? מונע שליחה כפולה כש-
    scan.yml בענן מריץ את סקריפט הסיכום בכל סריקה (כל 5 דק') בתוך חלון הזמן שלו -
    בלי זה, כל הרצה בתוך החלון הייתה שולחת הודעת טלגרם נוספת."""
    cur = conn.execute("SELECT 1 FROM summary_log WHERE kind = ? AND sent_date = ?", (kind, sent_date))
    return cur.fetchone() is not None


def mark_summary_sent(conn: sqlite3.Connection, kind: str, sent_date: str) -> None:
    conn.execute("INSERT OR IGNORE INTO summary_log (kind, sent_date) VALUES (?, ?)", (kind, sent_date))
    conn.commit()


def get_todays_alert_pct(conn: sqlite3.Connection, ticker: str, scan_date: str) -> float | None:
    """שינוי האחוז (pct_change) של ההתראה האחרונה שכבר נשלחה היום עבור טיקר זה,
    אם יש, אחרת None. משמש כדי לשלוח שוב התראה אם הירידה החמירה (למשל לאחר
    שהעלית את אחוז הסף, או שהמניה פשוט המשיכה לרדת) - במקום לדלג בגלל דדופ יומי גורף."""
    cur = conn.execute(
        "SELECT pct_change FROM alerts WHERE ticker = ? AND scan_date = ? LIMIT 1", (ticker, scan_date)
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_todays_telegram_message_id(conn: sqlite3.Connection, ticker: str, scan_date: str) -> int | None:
    """message_id של הודעת הטלגרם האחרונה שכבר נשלחה היום עבור טיקר זה, אם יש -
    כדי לערוך אותה במקום לשלוח הודעה כפולה כשההתראה מתעדכנת (ירידה שהחמירה)."""
    cur = conn.execute(
        "SELECT telegram_message_id FROM alerts WHERE ticker = ? AND scan_date = ? LIMIT 1", (ticker, scan_date)
    )
    row = cur.fetchone()
    return row[0] if row else None


def mark_as_bought(
    conn: sqlite3.Connection, alert_id: int, actual_entry_price: float, actual_qty: float,
    bought_at: str | None = None, holding_stop_price: float | None = None,
    is_manual_trade: bool = False,
) -> None:
    """מסמן התראה כ'נקנתה בפועל' עם מחיר וכמות אמיתיים - לצורך מעקב רווח/הפסד
    אמיתי מול המחיר הנוכחי, בנוסף לתרחיש התיאורטי שכבר מוצג בהתראה עצמה.
    bought_at אופציונלי - תאריך ביצוע בפועל (אם לא הוזן באותו רגע, למשל עסקה
    שכבר בוצעה קודם), אחרת נופל חזרה לרגע הנוכחי. holding_stop_price - קו
    הסטופ-לוס (מבוסס ATR בזמן הקנייה) נקבע *פעם אחת* כאן ונשאר קבוע לכל אורך
    ההחזקה - בדיוק כמו סטופ אמיתי אצל ברוקר, לא מתעדכן עם תנודתיות עתידית.
    is_manual_trade - עסקה שבוצעה על דעת המשקיע ולא לפי התראת המערכת/האסטרטגיה -
    לא נמחקת, רק מסומנת כך שאפשר לסנן אותה מסטטיסטיקת ביצועי האסטרטגיה."""
    conn.execute(
        "UPDATE alerts SET bought = 1, actual_entry_price = ?, actual_qty = ?, bought_at = ?, "
        "holding_stop_price = ?, is_manual_trade = ? WHERE id = ?",
        (
            actual_entry_price, actual_qty,
            bought_at or dt.datetime.now().isoformat(timespec="seconds"),
            holding_stop_price, 1 if is_manual_trade else 0, alert_id,
        ),
    )
    conn.commit()


def update_holding_stop_price(conn: sqlite3.Connection, alert_id: int, holding_stop_price: float) -> None:
    """מילוי retroactive של קו סטופ (ATR) לאחזקה שנקנתה לפני שהמנגנון הזה נוסף -
    נקרא פעם אחת בלבד (רק אם עדיין NULL), ואז הוא קבוע בדיוק כמו אחזקה חדשה."""
    conn.execute("UPDATE alerts SET holding_stop_price = ? WHERE id = ?", (holding_stop_price, alert_id))
    conn.commit()


def save_closed_trade(conn: sqlite3.Connection, record: dict) -> int:
    """שומר עסקה שנסגרה בפועל (מכירה) - היסטוריה קבועה שלא נמחקת, בניגוד לשדות
    האחזקה הפעילה בטבלת alerts שמתאפסים ב-unmark_as_bought. נקרא תמיד *לפני*
    unmark_as_bought, כדי שהמידע על הכניסה/תחזית יישמר לצמיתות."""
    record = {**record, "closed_at": dt.datetime.now().isoformat(timespec="seconds")}
    record["is_manual_trade"] = 1 if record.get("is_manual_trade") else 0
    cur = conn.execute(
        """INSERT INTO closed_trades
        (alert_id, ticker, company_name, index_name, currency, entry_price, qty, entry_at,
         exit_price, exit_at, forecast_entry_limit, forecast_target, forecast_stop,
         forecast_score, forecast_verdict, holding_days, gross_pnl, net_pnl, net_pct,
         is_manual_trade, closed_at)
        VALUES (:alert_id, :ticker, :company_name, :index_name, :currency, :entry_price, :qty, :entry_at,
                :exit_price, :exit_at, :forecast_entry_limit, :forecast_target, :forecast_stop,
                :forecast_score, :forecast_verdict, :holding_days, :gross_pnl, :net_pnl, :net_pct,
                :is_manual_trade, :closed_at)""",
        record,
    )
    conn.commit()
    return cur.lastrowid


def get_closed_trades(conn: sqlite3.Connection) -> list[dict]:
    """כל העסקאות הסגורות (מכירות בפועל), מהחדשה לישנה - היסטוריית הניסויים
    המעשיים שלך מול השוק, לשימוש בטאב 'היסטוריית עסקאות'."""
    cur = conn.execute("SELECT * FROM closed_trades ORDER BY exit_at DESC, id DESC")
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def unmark_as_bought(conn: sqlite3.Connection, alert_id: int) -> None:
    conn.execute(
        "UPDATE alerts SET bought = 0, actual_entry_price = NULL, actual_qty = NULL, bought_at = NULL, "
        "last_gain_alert_pct = NULL, stop_alert_active = 0, holding_stop_price = NULL WHERE id = ?",
        (alert_id,),
    )
    conn.commit()


def update_stop_alert(conn: sqlite3.Connection, alert_id: int, active: bool) -> None:
    conn.execute("UPDATE alerts SET stop_alert_active = ? WHERE id = ?", (1 if active else 0, alert_id))
    conn.commit()


def get_bought_holdings(conn: sqlite3.Connection) -> list[dict]:
    """כל האחזקות המסומנות כ'נקנו בפועל' - לשימוש בבדיקת עלייה מהכניסה שלך."""
    cur = conn.execute(
        "SELECT id, ticker, company_name, index_name, actual_entry_price, actual_qty, "
        "last_gain_alert_pct, bought_at, stop_alert_active, holding_stop_price, target_base, "
        "target_alert_active, is_manual_trade "
        "FROM alerts WHERE bought = 1"
    )
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def update_gain_alert(conn: sqlite3.Connection, alert_id: int, gain_pct: float) -> None:
    conn.execute("UPDATE alerts SET last_gain_alert_pct = ? WHERE id = ?", (gain_pct, alert_id))
    conn.commit()


def update_target_alert(conn: sqlite3.Connection, alert_id: int, active: bool) -> None:
    conn.execute("UPDATE alerts SET target_alert_active = ? WHERE id = ?", (1 if active else 0, alert_id))
    conn.commit()


def get_alert_pct_for_close_date(conn: sqlite3.Connection, ticker: str, last_close_date: str) -> float | None:
    """שינוי האחוז של ההתראה האחרונה שכבר נשלחה עבור טיקר זה על בסיס אותו
    last_close_date בדיוק - בלי קשר ל-scan_date (יום הסריקה בפועל). קיים כי
    מקור הנתונים לפעמים לא מתעדכן כמה ימים ברציפות (למשל מניית ת"א שנפתח יום
    מסחר חדש אבל מקור הנתונים עדיין מציג את סגירת אתמול) - בלי הבדיקה הזו,
    כל סבב סריקה ביום חדש היה שולח שוב "התראה חדשה" על אותה ירידה בדיוק
    שכבר נשלחה, כי scan_date השתנה גם כשה'נתון' עצמו לא באמת השתנה."""
    cur = conn.execute(
        "SELECT pct_change FROM alerts WHERE ticker = ? AND last_close_date = ? "
        "ORDER BY scan_ts DESC LIMIT 1",
        (ticker, last_close_date),
    )
    row = cur.fetchone()
    return row[0] if row else None


def save_alert(conn: sqlite3.Connection, record: dict) -> int:
    """שומר/מעדכן התראה. אם כבר קיימת שורה לאותו (scan_date, ticker) - מעדכן רק
    את שדות התוכן (כדי לתמוך בהתראה חוזרת כשהירידה מחמירה), ולא נוגע ב-
    telegram_message_id/bought/actual_entry_price וכו' שנקבעו קודם, כדי לא לאבד
    אותם (INSERT OR REPLACE היה מוחק את כל השורה כולל את השדות האלה)."""
    existing = conn.execute(
        "SELECT id FROM alerts WHERE scan_date = ? AND ticker = ?", (record["scan_date"], record["ticker"])
    ).fetchone()
    if existing:
        alert_id = existing[0]
        conn.execute(
            """UPDATE alerts SET
                scan_ts=:scan_ts, company_name=:company_name, index_name=:index_name, pct_change=:pct_change,
                last_close=:last_close, prev_close=:prev_close, reason_text=:reason_text,
                reasons_json=:reasons_json, headlines_json=:headlines_json,
                overreaction_verdict=:overreaction_verdict, overreaction_score=:overreaction_score,
                entry_limit=:entry_limit, target_base=:target_base, stop_loss=:stop_loss,
                net_result_json=:net_result_json, sector=:sector,
                quality_tier=:quality_tier, quality_score=:quality_score,
                quality_flags_json=:quality_flags_json, rebound_tier=:rebound_tier,
                last_close_date=:last_close_date,
                zscore=:zscore, rsi=:rsi, volume_ratio=:volume_ratio, vix_level=:vix_level,
                intraday_recovery_pct=:intraday_recovery_pct
               WHERE id = :id""",
            {**record, "id": alert_id},
        )
        conn.commit()
        return alert_id

    cur = conn.execute(
        """INSERT INTO alerts
        (scan_date, scan_ts, ticker, company_name, index_name, pct_change, last_close, prev_close,
         reason_text, reasons_json, headlines_json, overreaction_verdict, overreaction_score,
         entry_limit, target_base, stop_loss, net_result_json, sector,
         quality_tier, quality_score, quality_flags_json, rebound_tier, last_close_date,
         zscore, rsi, volume_ratio, vix_level, intraday_recovery_pct)
        VALUES (:scan_date, :scan_ts, :ticker, :company_name, :index_name, :pct_change, :last_close, :prev_close,
                :reason_text, :reasons_json, :headlines_json, :overreaction_verdict, :overreaction_score,
                :entry_limit, :target_base, :stop_loss, :net_result_json, :sector,
                :quality_tier, :quality_score, :quality_flags_json, :rebound_tier, :last_close_date,
                :zscore, :rsi, :volume_ratio, :vix_level, :intraday_recovery_pct)""",
        record,
    )
    conn.commit()
    return cur.lastrowid


def update_telegram_message_id(conn: sqlite3.Connection, alert_id: int, message_id: int) -> None:
    conn.execute("UPDATE alerts SET telegram_message_id = ? WHERE id = ?", (message_id, alert_id))
    conn.commit()


def count_todays_sector_alerts(conn: sqlite3.Connection, sector: str, scan_date: str, exclude_ticker: str) -> int:
    """כמה טיקרים שונים (לא כולל exclude_ticker) כבר קיבלו התראה היום מאותו סקטור -
    לזיהוי ריכוז סקטוריאלי (כמה מניות מאותו ענף נופלות באותו יום, כנראה אירוע רחב אחד)."""
    if not sector:
        return 0
    cur = conn.execute(
        "SELECT COUNT(DISTINCT ticker) FROM alerts WHERE sector = ? AND scan_date = ? AND ticker != ?",
        (sector, scan_date, exclude_ticker),
    )
    return cur.fetchone()[0]


def update_outcomes(conn: sqlite3.Connection, id_outcome_pairs: list[tuple[int, str]]) -> None:
    """מעדכן את עמודת outcome עבור רשימת (id, outcome) - נקרא אחרי הרצת backtest,
    כדי לשמור תוצאות מחושבות לשימוש חוזר מהיר (למשל בטרק-רקורד להתראות עתידיות)."""
    conn.executemany("UPDATE alerts SET outcome = ? WHERE id = ?", [(o, i) for i, o in id_outcome_pairs])
    conn.commit()


def get_ticker_track_record(conn: sqlite3.Connection, ticker: str, exclude_id: int | None = None) -> dict:
    """סטטיסטיקת הצלחה היסטורית עבור טיקר נתון, מבוססת על outcome-ים שכבר חושבו
    ונשמרו (ראו update_outcomes) - לא מבצע קריאות רשת, מהיר לשימוש בזמן סריקה חיה."""
    query = "SELECT outcome FROM alerts WHERE ticker = ? AND outcome IN ('hit_target', 'hit_stop', 'neither')"
    params = [ticker]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    rows = [r[0] for r in conn.execute(query, params).fetchall()]
    hit_target = rows.count("hit_target")
    return {"total_decided": len(rows), "hit_target": hit_target}


def add_price_alert(
    conn: sqlite3.Connection, ticker: str, company_name: str | None, index_name: str,
    target_price: float, direction: str,
) -> int:
    """יוצר התראת מחיר ידנית - direction הוא 'above' (מעל) או 'below' (מתחת).
    נבדקת ע"י הסורק בכל סבב (ראו scanner.check_price_alerts), לא רק בזמן קנייה/
    מכירה כמו יתר ההתראות - זו התראה על מחיר-יעד שאתה קובע בעצמך, לא קשורה
    לירידה חדה או לאחזקה קיימת."""
    cur = conn.execute(
        "INSERT INTO price_alerts (ticker, company_name, index_name, target_price, direction, created_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (ticker, company_name, index_name, target_price, direction, dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return cur.lastrowid


def get_active_price_alerts(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT id, ticker, company_name, index_name, target_price, direction, created_at "
        "FROM price_alerts WHERE active = 1 ORDER BY created_at DESC"
    )
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def deactivate_price_alert(conn: sqlite3.Connection, alert_id: int, triggered: bool = False) -> None:
    """מסמן התראת מחיר כלא-פעילה - triggered=True כשהיא נורתה בפועל (נשמר תאריך
    ההפעלה לתיעוד), triggered=False כשהמשתמש פשוט ביטל אותה ידנית."""
    if triggered:
        conn.execute(
            "UPDATE price_alerts SET active = 0, triggered_at = ? WHERE id = ?",
            (dt.datetime.now().isoformat(timespec="seconds"), alert_id),
        )
    else:
        conn.execute("UPDATE price_alerts SET active = 0 WHERE id = ?", (alert_id,))
    conn.commit()


def build_record(scan_date: str, ticker: str, company_name: str | None, index_name: str,
                  row: dict, analysis, trade_idea, net_results: dict) -> dict:
    return {
        "scan_date": scan_date,
        "scan_ts": dt.datetime.now().isoformat(timespec="seconds"),
        "ticker": ticker,
        "company_name": company_name or "",
        "index_name": index_name,
        "pct_change": row["pct_change"],
        "last_close": row["last_close"],
        "prev_close": row["prev_close"],
        "reason_text": analysis.reason_text,
        "reasons_json": json.dumps(analysis.reasons, ensure_ascii=False),
        "headlines_json": json.dumps(analysis.headlines, ensure_ascii=False, default=str),
        "overreaction_verdict": analysis.overreaction_verdict,
        "overreaction_score": analysis.overreaction_score,
        "entry_limit": trade_idea.entry_limit,
        "target_base": trade_idea.target_base,
        "stop_loss": trade_idea.stop_loss,
        "net_result_json": json.dumps(net_results, ensure_ascii=False, default=lambda o: o.__dict__),
        "sector": analysis.sector,
        "quality_tier": analysis.quality.tier if analysis.quality else None,
        "quality_score": analysis.quality.score if analysis.quality else None,
        "quality_flags_json": json.dumps(analysis.quality.flags, ensure_ascii=False) if analysis.quality else None,
        "rebound_tier": analysis.rebound_tier,
        "last_close_date": row.get("last_close_date").isoformat() if row.get("last_close_date") else None,
        # הגורמים הגולמיים שמרכיבים את overreaction_score (ר' analysis._score_overreaction) -
        # רק הציון הסופי המשוקלל נשמר עד עכשיו, לא הגורמים הבודדים, כך שאי אפשר
        # היה לבדוק בדיעבד אילו גורמים בפועל מנבאים הצלחה. שומרים את הגולמי (לא
        # את תת-הציון 0-100) כדי שאם נוסחת תת-הציון תשתנה בעתיד, אפשר יהיה עדיין
        # לחשב מחדש בעקביות על נתונים היסטוריים.
        "zscore": analysis.zscore,
        "rsi": analysis.rsi,
        "volume_ratio": analysis.volume_ratio,
        "vix_level": analysis.vix_level,
        "intraday_recovery_pct": analysis.intraday_recovery_pct,
    }
