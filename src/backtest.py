"""בדיקה לאחור (backtest): האם ההתראות וההמלצות שנשלחו בעבר הצליחו בפועל?
לכל התראה היסטורית בודקים אם המחיר הגיע ליעד המכירה (הצלחה) או לסטופ-לוס
(כישלון) קודם, בטווח ימי מסחר נתון - על בסיס נתוני High/Low יומיים אמיתיים.
"""
import datetime as dt
import json
import logging
import sqlite3

import pandas as pd
import yfinance as yf

from . import store
from .market_data import _is_israeli_ticker

logger = logging.getLogger(__name__)


def primary_reason_tag(reasons_json: str) -> str:
    """מחלץ את תגית הסיבה הראשית (הראשונה ברשימה) מתוך reasons_json שנשמר עם
    ההתראה - לשימוש בקיבוץ/סטטיסטיקה (backtest tab, דוח שבועי וכו')."""
    try:
        reasons = json.loads(reasons_json or "[]")
        return reasons[0] if reasons else "unclear"
    except Exception:
        return "unclear"

HIT_TARGET = "hit_target"
HIT_STOP = "hit_stop"
NEITHER = "neither"
PENDING = "pending"
NO_DATA = "no_data"

OUTCOME_LABELS_HE = {
    HIT_TARGET: "הגיע ליעד",
    HIT_STOP: "פגע בסטופ",
    NEITHER: "לא הגיע לאף אחד",
    PENDING: "עדיין מוקדם מדי",
    NO_DATA: "אין נתונים",
}


BASELINE_TARGET_PCT = 5.0  # יעד "טיפוסי" שסביבו כוילה חלון-ההמתנה הבסיסי (window_days)
MAX_WINDOW_DAYS = 30  # תקרה - לא לתת חודשים של המתנה על תיקון קיצוני
MIN_TARGET_REWARD_RISK_RATIO = 1.0  # רצפה על target_base - היעד לעולם לא קטן ממרחק הסטופ (יחס 1:1)


def _effective_target(entry_limit: float | None, target_base: float, stop_loss: float) -> float:
    """target_base (תיקון-Fibonacci מגודל הירידה בפועל) עם רצפה של יחס 1:1 מול
    הסטופ - זהה בדיוק ל-_live_target_price בדשבורד, כדי שהבקטסט יבדוק את אותו
    יעד שבאמת מוצג/משמש באחזקה החיה."""
    if not entry_limit:
        return target_base
    floor_price = entry_limit + (entry_limit - stop_loss) * MIN_TARGET_REWARD_RISK_RATIO
    return max(target_base, floor_price)


def _scaled_window_days(entry_limit: float | None, target: float | None, base_window_days: int) -> int:
    """חלון-ההמתנה גדל יחסית לגודל היעד - יעד רחוק יותר מקבל יותר זמן להתממש,
    במקום תמיד להישפט מול אותו חלון קבוע. אומת: השוואה עם חלון קבוע בין יעד
    קטן לגדול נתנה תמונה מוטה - היעד הגדול "נכשל" בעיקר כי לא ניתן לו מספיק
    זמן, לא כי פחות בר-השגה; כשמקנים זמן יחסי, שיעור ההצלחה כמעט זהה."""
    if not entry_limit or not target:
        return base_window_days
    target_pct = (target / entry_limit - 1) * 100
    if target_pct <= 0:
        return base_window_days
    scaled = round(base_window_days * target_pct / BASELINE_TARGET_PCT)
    return min(MAX_WINDOW_DAYS, max(base_window_days, scaled))


def _outcome_for_alert(ticker: str, scan_ts: str, target_base: float, stop_loss: float,
                        window_days: int = 10, entry_limit: float | None = None,
                        actual_entry_price: float | None = None, actual_entry_date: str | None = None) -> str:
    """אם actual_entry_price/actual_entry_date מסופקים (עסקה שבאמת מומשה) -
    בודקים יעד/סטופ מרגע הכניסה האמיתי, לא מרגע ההתראה - אחרת תנודה חדה באותו
    יום של ההתראה עצמה (לפני שהייתה הזדמנות ריאלית להיכנס) יכולה להיספר כהצלחה
    שלא באמת הייתה שייכת לעסקה שנפתחה בפועל."""
    entry_ts = actual_entry_date if (actual_entry_price and actual_entry_date) else scan_ts
    try:
        scan_date = dt.datetime.fromisoformat(entry_ts).date()
    except Exception:
        return NO_DATA

    entry_ref = actual_entry_price if actual_entry_price else entry_limit
    target = _effective_target(entry_ref, target_base, stop_loss)
    window_days = _scaled_window_days(entry_ref, target, window_days)
    start = scan_date
    calendar_buffer = int(window_days * 1.6) + 4  # מרווח לסופי שבוע/חגים
    end = min(start + dt.timedelta(days=calendar_buffer), dt.date.today())
    if start >= dt.date.today():
        return PENDING

    try:
        hist = yf.download(
            ticker, start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
            interval="1d", progress=False, auto_adjust=False, threads=False,
        )
    except Exception as e:
        logger.debug("נכשלה שליפת היסטוריה עבור %s: %s", ticker, e)
        return NO_DATA

    if hist.empty:
        return NO_DATA

    highs, lows = hist["High"], hist["Low"]
    if hasattr(highs, "columns"):  # yfinance עשוי להחזיר multiindex גם למניה בודדת
        highs, lows = highs.iloc[:, 0], lows.iloc[:, 0]

    if _is_israeli_ticker(ticker):  # מניות ת"א מדווחות באגורות - ממירים לש"ח כמו בשאר האפליקציה
        highs, lows = highs / 100.0, lows / 100.0

    highs, lows = highs.dropna(), lows.dropna()
    if actual_entry_price and actual_entry_date:
        # נר יומי לא אומר באיזו שעה בתוך היום נכנסנו בפועל - תנודה חדה שקרתה
        # באותו יום (אולי לפני שהייתה הזדמנות ריאלית להיכנס) לא אמורה להיספר
        # כהצלחה/כישלון של העסקה. בלי לנחש שעה או להשוות מחירים - פשוט מדלגים
        # לגמרי על נר יום הכניסה, ומתחילים לבדוק מהיום שאחריו.
        highs, lows = highs.iloc[1:window_days + 1], lows.iloc[1:window_days + 1]
    else:
        highs, lows = highs.iloc[:window_days], lows.iloc[:window_days]

    for h, l in zip(highs.tolist(), lows.tolist()):
        if l <= stop_loss:
            return HIT_STOP
        if h >= target:
            return HIT_TARGET

    still_within_window = (dt.date.today() - start).days < calendar_buffer
    return PENDING if still_within_window else NEITHER


def run_backtest(alerts_df: pd.DataFrame, window_days: int = 10) -> pd.DataFrame:
    """מקבל DataFrame גולמי מטבלת alerts (SELECT *), ומחזיר אותו עם עמודת 'outcome' נוספת."""
    if alerts_df.empty:
        return alerts_df
    df = alerts_df.copy()
    df["outcome"] = [
        _outcome_for_alert(
            row["ticker"], row["scan_ts"], row["target_base"], row["stop_loss"], window_days,
            entry_limit=row.get("entry_limit"),
            actual_entry_price=(row.get("actual_entry_price") if row.get("bought") == 1 else None),
            actual_entry_date=(row.get("bought_at") if row.get("bought") == 1 else None),
        )
        for _, row in df.iterrows()
    ]
    return df


def closed_trades_as_outcomes(conn: sqlite3.Connection, exclude_manual: bool = True) -> pd.DataFrame:
    """ממיר עסקאות שכבר נסגרו (טבלת closed_trades) לאותו פורמט עמודות שה-backtest
    מייצר להתראות פתוחות (outcome/ticker/scan_ts/target_base/stop_loss/...) - כדי
    שאפשר יהיה לשלב אותן עם פוזיציות פתוחות לתמונה אחת של 'התראות שמומשו'. בניגוד
    לפוזיציה פתוחה, כאן לא מסמלצים כלום - כבר יודעים בוודאות את מחיר היציאה
    בפועל, אז ה-outcome נקבע ישירות ממנו מול היעד/סטופ שהוצעו בזמן ההתראה."""
    closed = pd.read_sql_query(
        "SELECT ct.*, a.reasons_json AS alert_reasons_json, a.overreaction_score AS alert_score "
        "FROM closed_trades ct LEFT JOIN alerts a ON ct.alert_id = a.id",
        conn,
    )
    if closed.empty:
        return closed
    if exclude_manual and "is_manual_trade" in closed.columns:
        closed = closed[closed["is_manual_trade"] != 1]
    if closed.empty:
        return closed

    def _outcome(row) -> str:
        if pd.isna(row.get("forecast_target")) or pd.isna(row.get("forecast_stop")) or pd.isna(row.get("exit_price")):
            return NO_DATA
        if row["exit_price"] <= row["forecast_stop"]:
            return HIT_STOP
        if row["exit_price"] >= row["forecast_target"]:
            return HIT_TARGET
        return NEITHER

    closed["outcome"] = closed.apply(_outcome, axis=1)
    closed["scan_ts"] = closed["entry_at"]
    closed["target_base"] = closed["forecast_target"]
    closed["stop_loss"] = closed["forecast_stop"]
    closed["overreaction_score"] = closed["alert_score"]
    closed["reasons_json"] = closed["alert_reasons_json"].fillna("[]")
    closed["pct_change"] = None
    return closed


def summarize_by(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """סיכום שיעור הצלחה (הגיע ליעד מתוך המוכרעים - לא כולל pending/no_data) לפי עמודת קיבוץ."""
    decided = df[df["outcome"].isin([HIT_TARGET, HIT_STOP, NEITHER])]
    if decided.empty:
        return pd.DataFrame(columns=[group_col, "סה\"כ", "הגיעו ליעד", "שיעור הצלחה (%)"])
    grouped = decided.groupby(group_col)["outcome"].agg(
        total="count",
        hits=lambda s: (s == HIT_TARGET).sum(),
    )
    grouped["rate"] = (grouped["hits"] / grouped["total"] * 100).round(1)
    grouped = grouped.sort_values("rate", ascending=False).reset_index()
    grouped.columns = [group_col, "סה\"כ", "הגיעו ליעד", "שיעור הצלחה (%)"]
    return grouped


def refresh_pending_outcomes(conn: sqlite3.Connection, window_days: int = 10) -> int:
    """מריץ backtest על כל ההתראות שעדיין לא הוכרעו (outcome ריק/pending) ושומר
    outcome-ים שהתבררו - כדי שטרק-רקורד לכל מניה יהיה זמין גם בלי לפתוח את
    הדשבורד (למשל כשקורא מ-run_daily_summary.py). מחזיר כמה outcome-ים עודכנו."""
    pending_df = pd.read_sql_query(
        "SELECT * FROM alerts WHERE outcome IS NULL OR outcome = ?", conn, params=(PENDING,)
    )
    if pending_df.empty:
        return 0
    result = run_backtest(pending_df, window_days)
    decided = result[result["outcome"] != PENDING]
    if decided.empty:
        return 0
    store.update_outcomes(conn, list(zip(decided["id"], decided["outcome"])))
    return len(decided)


def overall_summary(df: pd.DataFrame) -> dict:
    counts = df["outcome"].value_counts().to_dict()
    decided_total = counts.get(HIT_TARGET, 0) + counts.get(HIT_STOP, 0) + counts.get(NEITHER, 0)
    win_rate = (counts.get(HIT_TARGET, 0) / decided_total * 100) if decided_total else None
    return {
        "total_alerts": len(df),
        "hit_target": counts.get(HIT_TARGET, 0),
        "hit_stop": counts.get(HIT_STOP, 0),
        "neither": counts.get(NEITHER, 0),
        "pending": counts.get(PENDING, 0),
        "no_data": counts.get(NO_DATA, 0),
        "win_rate_pct": win_rate,
    }
