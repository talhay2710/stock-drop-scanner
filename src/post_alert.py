"""תוצאות *אחרי* ההתראה, מחושבות מנתוני 5 דקות (ולא מ-High/Low יומי).

למה: בבק-טסט היומי (backtest.py) יום ההתראה כולו נספר - כולל ה-High של הבוקר, *לפני* שהמניה
ירדה וההתראה נשלחה. מניה שיורדת 4% ביום נראית אוטומטית כמי ש"הגיעה ליעד של 3%" כבר ביום הראשון
(7.10.2026, בדיקה מחדש: שיעור ההצלחה בישראל ירד מ-~58% ל-~43% כשמודדים רק מרגע ההתראה).
כאן כל התראה נמדדת מרגע ההתראה ואילך: כניסה במחיר ההתראה, ושיא/שפל/סגירה בסוף כל אחד
מ-3 ימי המסחר הראשונים (יום ההתראה = יום 1). הנתונים נשמרים בטבלה post_alert_outcomes כי
נתוני 5 הדקות של yfinance זמינים רק ל-60 הימים האחרונים.

כל ערכי האחוזים יחסית למחיר ההתראה (last_close): max_up_k = השיא עד סוף יום k, last_k =
הסגירה בסוף יום k. כך אפשר לחשב רטרואקטיבית כל יעד וכל אופק (1-3 ימים) בלי להוריד שוב.
"""
import datetime as dt
import logging
import sqlite3

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

HOLD_DAYS = 3
_SCALE_IL = 100.0  # מניות ת"א מדווחות באגורות

_SCHEMA = """
CREATE TABLE IF NOT EXISTS post_alert_outcomes (
    alert_id INTEGER PRIMARY KEY,
    max_up_1 REAL, max_up_2 REAL, max_up_3 REAL,
    last_1 REAL, last_2 REAL, last_3 REAL,
    max_dn_3 REAL,
    computed_at TEXT
)
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    conn.commit()


def _alert_ts(scan_ts: str) -> pd.Timestamp | None:
    """זמן ההתראה כ-Timestamp עם tz. שורות ישנות שמורות כזמן ישראל בלי אזור זמן."""
    try:
        ts = pd.Timestamp(scan_ts)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Jerusalem")
    return ts


def _compute_one(bars: pd.DataFrame, ts: pd.Timestamp, entry: float) -> dict | None:
    """bars: High/Low/Close ב-5 דקות (כבר בש"ח/$), index עם tz של הבורסה."""
    if bars is None or bars.empty or not entry:
        return None
    ts = ts.tz_convert(bars.index.tz)
    days = sorted(set(bars.index.date))
    d0 = ts.date()
    if d0 not in days:
        return None
    k = days.index(d0)
    window_days = days[k:k + HOLD_DAYS]
    if len(window_days) < HOLD_DAYS:
        return None  # החלון עדיין לא הסתיים
    after = bars[bars.index > ts]
    out: dict = {}
    for i, day in enumerate(window_days, start=1):
        upto = after[after.index.date <= day]
        if upto.empty:
            return None
        out[f"max_up_{i}"] = (float(upto["High"].max()) / entry - 1) * 100
        out[f"last_{i}"] = (float(upto["Close"].iloc[-1]) / entry - 1) * 100
    out["max_dn_3"] = (float(after[after.index.date <= window_days[-1]]["Low"].min()) / entry - 1) * 100
    return out


def update_missing(conn: sqlite3.Connection, max_alerts: int = 400) -> int:
    """מחשב ושומר תוצאות להתראות שחלון 3 הימים שלהן הסתיים ועדיין אין להן שורה. מחזיר כמה נוספו."""
    ensure_table(conn)
    df = pd.read_sql_query(
        "SELECT id, ticker, scan_ts, last_close FROM alerts "
        "WHERE id NOT IN (SELECT alert_id FROM post_alert_outcomes) AND last_close IS NOT NULL "
        "AND date(substr(scan_ts, 1, 10)) <= date('now', '-4 day') "
        "ORDER BY id DESC LIMIT ?",
        conn, params=(max_alerts,),
    )
    if df.empty:
        return 0
    tickers = sorted(df["ticker"].dropna().unique())
    try:
        raw = yf.download(
            tickers=tickers, period="60d", interval="5m", group_by="ticker",
            threads=True, auto_adjust=False, progress=False,
        )
    except Exception as e:
        logger.warning("הורדת נתוני 5 דקות נכשלה (%d טיקרים): %s", len(tickers), e)
        return 0
    added = 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    for _, r in df.iterrows():
        try:
            bars = raw[r["ticker"]][["High", "Low", "Close"]].dropna() if isinstance(raw.columns, pd.MultiIndex) else raw[["High", "Low", "Close"]].dropna()
            if str(r["ticker"]).upper().endswith(".TA"):
                bars = bars / _SCALE_IL
            ts = _alert_ts(r["scan_ts"])
            if ts is None:
                continue
            res = _compute_one(bars, ts, float(r["last_close"]))
        except Exception as e:
            logger.debug("post_alert נכשל עבור %s: %s", r["ticker"], e)
            continue
        if res is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO post_alert_outcomes "
            "(alert_id, max_up_1, max_up_2, max_up_3, last_1, last_2, last_3, max_dn_3, computed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (int(r["id"]), res["max_up_1"], res["max_up_2"], res["max_up_3"],
             res["last_1"], res["last_2"], res["last_3"], res["max_dn_3"], now),
        )
        added += 1
    conn.commit()
    return added


def load_outcomes(conn: sqlite3.Connection) -> pd.DataFrame:
    ensure_table(conn)
    return pd.read_sql_query("SELECT * FROM post_alert_outcomes", conn)


def evaluate(df: pd.DataFrame, target_pct: float, hold_days: int) -> pd.DataFrame:
    """מוסיף ל-df (alerts מחובר ל-post_alert_outcomes) את outcome ('hit_target'/'hit_stop'/
    'neither'/'pending') ואת ret (תשואה באחוזים: target_pct בהצלחה, אחרת הסגירה ביום hold_days).
    התראה בלי נתונים מחושבים = pending (החלון לא הסתיים או שאין נתוני 5 דקות)."""
    from .backtest import HIT_TARGET, HIT_STOP, NEITHER, PENDING
    k = max(1, min(HOLD_DAYS, int(hold_days)))
    out = df.copy()
    up, last = out[f"max_up_{k}"], out[f"last_{k}"]
    stop_pct = (out["stop_loss"] / out["last_close"] - 1) * 100
    has = up.notna()
    win = has & (up >= target_pct)
    loss = has & ~win & (out["max_dn_3"] <= stop_pct)
    out["outcome"] = PENDING
    out.loc[has, "outcome"] = NEITHER
    out.loc[loss, "outcome"] = HIT_STOP
    out.loc[win, "outcome"] = HIT_TARGET
    out["ret"] = pd.NA
    out.loc[has, "ret"] = last[has]
    out.loc[win, "ret"] = target_pct
    out.loc[loss, "ret"] = stop_pct[loss]
    out["ret"] = pd.to_numeric(out["ret"], errors="coerce")
    return out
