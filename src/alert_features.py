"""וקטורים מועמדים לניקוד, שנשמרים לכל התראה *בלי להשפיע על הניקוד* (8.10.2026).

הבדיקה ההצלבתית (ימים שלמים מחוץ לאימון, 20 חזרות) הראתה שהוספת וקטורים לניקוד של ישראל מורידה את יכולת ההבחנה
(AUC 0.678 -> 0.665), בעיקר מהתאמת-יתר למדגם קטן (~30 ימים). כדי שבעוד כמה שבועות אפשר יהיה לבדוק שוב באותו מבחן
על מדגם גדול יותר, כל התראה חדשה שומרת כאן את הערכים של הווקטורים המבטיחים בזמן ההתראה (טבלה alert_features,
בבעלות הסורק בלבד - כמו post_alert_outcomes, אז מיזוג ה-DB לא נוגע בה).

כל החישובים מנתונים שהיו זמינים ברגע ההתראה (בלי הצצה לעתיד).
"""
import datetime as dt
import logging
import math
import sqlite3

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_features (
    alert_id INTEGER PRIMARY KEY,
    dd_5d REAL,            -- % מהשיא של 5 ימי המסחר שלפני ההתראה (שלילי = נפילה)
    atr_norm_drop REAL,    -- גודל הירידה ביחס לתנודתיות הרגילה (ירידה% / (ATR14/מחיר*100))
    dollar_vol REAL,       -- מחזור יומי ממוצע (20 ימים) במטבע המנייה
    gap_open_pct REAL,     -- פער פתיחה ביום ההתראה לעומת הסגירה הקודמת
    down_streak INTEGER,   -- ימי ירידה רצופים לפני יום ההתראה
    ret_20d REAL,          -- שינוי % ב-20 הימים שלפני ההתראה
    computed_at TEXT
)
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    conn.commit()


def _finite(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def compute(row) -> dict:
    """row = שורת הסריקה (df) של המניה: history/highs/lows_series (סגירות/שיאים/שפלים, כולל היום), last_close,
    prev_close, pct_change, last_open, avg_volume_20d. מחזיר dict ערכים (None כשחסר מידע)."""
    out = {"dd_5d": None, "atr_norm_drop": None, "dollar_vol": None, "gap_open_pct": None,
           "down_streak": None, "ret_20d": None}
    try:
        closes = row["history"].dropna()
        prior = closes.iloc[:-1]            # בלי יום ההתראה עצמו (מחיר חלקי)
        if len(prior) >= 21:
            prev = float(prior.iloc[-1])
            out["dd_5d"] = _finite((prev / float(prior.iloc[-6:].max()) - 1) * 100)
            out["ret_20d"] = _finite((prev / float(prior.iloc[-21]) - 1) * 100)
            diffs = prior.diff().dropna()
            streak = 0
            for v in diffs.iloc[::-1]:
                if v < 0:
                    streak += 1
                else:
                    break
            out["down_streak"] = streak
            highs = row["highs"].dropna().iloc[:-1]
            lows = row["lows_series"].dropna().iloc[:-1]
            if len(highs) >= 15 and len(lows) >= 15:
                h, l, c = highs.iloc[-15:].values, lows.iloc[-15:].values, prior.iloc[-15:].values
                tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
                atr = sum(tr[-14:]) / len(tr[-14:])
                if atr > 0 and prev > 0:
                    out["atr_norm_drop"] = _finite(abs(float(row["pct_change"])) / (atr / prev * 100))
            last_open = _finite(row.get("last_open"))
            if last_open and prev > 0:
                out["gap_open_pct"] = _finite((last_open / prev - 1) * 100)
        avg_vol, last_close = _finite(row.get("avg_volume_20d")), _finite(row.get("last_close"))
        if avg_vol and last_close:
            out["dollar_vol"] = avg_vol * last_close
    except Exception as e:  # שמירת נתונים נלווים לעולם לא מפילה התראה
        logger.debug("alert_features.compute נכשל: %s", e)
    return out


def save(conn: sqlite3.Connection, alert_id: int, features: dict) -> None:
    ensure_table(conn)
    conn.execute(
        "INSERT OR REPLACE INTO alert_features "
        "(alert_id, dd_5d, atr_norm_drop, dollar_vol, gap_open_pct, down_streak, ret_20d, computed_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (alert_id, features["dd_5d"], features["atr_norm_drop"], features["dollar_vol"], features["gap_open_pct"],
         features["down_streak"], features["ret_20d"], dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
