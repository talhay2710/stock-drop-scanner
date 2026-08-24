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
from . import market_data
from . import strategy as strategy_mod
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
# הרצפה (יחס 1:1 מול מרחק הסטופ) הוסרה ב-23.8.2026 יחד עם הרחבת הסטופ
# (ATR_STOP_MULTIPLIER ל-2.5x, ר' strategy.py) - לבקשת המשתמש, היעד לא זז
# לעולם בגלל מרחק הסטופ יותר. נשאר כאן כפולבאק היסטורי בלבד, לא רצפה פעילה.
MIN_TARGET_REWARD_RISK_RATIO = 1.0


def _effective_target(entry_limit: float | None, target_base: float, stop_loss: float) -> float:
    """target_base כפי שנשמר - זהה בדיוק ל-strategy.live_target_price, כדי
    שהבקטסט יבדוק את אותו יעד שבאמת מוצג/משמש באחזקה החיה. entry_limit/stop_loss
    לא בשימוש כאן יותר (נשארו בחתימה כדי לא לשבור קריאות קיימות)."""
    return target_base


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


CANDIDATE_TARGET_PCTS = (0.02, 0.03, 0.04, 0.05, 0.06)


def _fetch_high_low_window(ticker: str, entry_ts: str, window_days: int, skip_entry_day: bool):
    """שולף את סדרת High/Low פעם אחת לכל התראה (לא לכל יעד מועמד בנפרד) - כדי
    שאפשר יהיה להשוות כמה אסטרטגיות יעד שונות על אותו נתון מחיר גולמי, בלי
    לכפול את מספר קריאות הרשת. מחזיר (highs, lows, still_within_window) או
    None אם אין מספיק נתונים."""
    try:
        scan_date = dt.datetime.fromisoformat(entry_ts).date()
    except Exception:
        return None
    if scan_date >= dt.date.today():
        return None

    calendar_buffer = int(window_days * 1.6) + 4
    end = min(scan_date + dt.timedelta(days=calendar_buffer), dt.date.today())
    try:
        hist = yf.download(
            ticker, start=scan_date.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
            interval="1d", progress=False, auto_adjust=False, threads=False,
        )
    except Exception as e:
        logger.debug("נכשלה שליפת היסטוריה עבור %s: %s", ticker, e)
        return None
    if hist.empty:
        return None

    highs, lows = hist["High"], hist["Low"]
    if hasattr(highs, "columns"):
        highs, lows = highs.iloc[:, 0], lows.iloc[:, 0]
    if _is_israeli_ticker(ticker):
        highs, lows = highs / 100.0, lows / 100.0
    highs, lows = highs.dropna(), lows.dropna()

    if skip_entry_day:
        highs, lows = highs.iloc[1:window_days + 1], lows.iloc[1:window_days + 1]
    else:
        highs, lows = highs.iloc[:window_days], lows.iloc[:window_days]

    still_within_window = (dt.date.today() - scan_date).days < calendar_buffer
    return highs.tolist(), lows.tolist(), still_within_window


def _outcome_from_series(highs: list, lows: list, target: float, stop_loss: float, still_within_window: bool) -> str:
    for h, l in zip(highs, lows):
        if l <= stop_loss:
            return HIT_STOP
        if h >= target:
            return HIT_TARGET
    return PENDING if still_within_window else NEITHER


def compare_target_strategies(conn: sqlite3.Connection, window_days: int = 10) -> pd.DataFrame:
    """משווה את יעד ה-Fibonacci בפועל (target_base, כפי שנשמר בזמן ההתראה - אחרי
    רצפת יחס 1:1) מול כמה יעדים קבועים פשוטים (2%-6%) ומול רמות Fibonacci
    אחרות (38.2%/61.8%, משוחזרות מ-last_close/prev_close) - על אותם התראות
    היסטוריות בדיוק, אותו סטופ-לוס ואותה נקודת כניסה. עונה על השאלה "האם
    Fibonacci בפועל טוב יותר מיעד קבוע פשוט, או שזה רק 'נראה מדעי'".
    מחזיר טבלת סיכום: אסטרטגיה, סה"כ, הגיעו ליעד, שיעור הצלחה (%), תוחלת (%).
    תוחלת (expectancy) חשובה יותר משיעור הצלחה לבדו - יעד קטן "מצליח" יותר
    כמעט תמיד (קל יותר להגיע ל-2% מ-50% תיקון), אבל שווה פחות בכל ניצחון.
    תוחלת = ממוצע התשואה על פני כל ההתראות (רווח על הצלחה, הפסד על סטופ,
    0% על 'לא הגיע לאף אחד' - הנחה שמרנית, לא יודעים את המחיר בפועל בסוף החלון)."""
    df = pd.read_sql_query(
        "SELECT ticker, scan_ts, entry_limit, stop_loss, target_base, last_close, prev_close, "
        "bought, actual_entry_price, bought_at "
        "FROM alerts WHERE entry_limit IS NOT NULL AND stop_loss IS NOT NULL",
        conn,
    )
    if df.empty:
        return pd.DataFrame(columns=["אסטרטגיה", "סה\"כ", "הגיעו ליעד", "שיעור הצלחה (%)", "תוחלת (%)"])

    results: dict[str, list[tuple[str, float]]] = {}
    for _, row in df.iterrows():
        has_real_entry = bool(row["bought"]) and row["actual_entry_price"] and row["bought_at"]
        entry_ref = row["actual_entry_price"] if has_real_entry else row["entry_limit"]
        entry_ts = row["bought_at"] if has_real_entry else row["scan_ts"]
        stop_loss = row["stop_loss"]

        target_fib50 = _effective_target(entry_ref, row["target_base"], stop_loss)
        scaled_window = _scaled_window_days(entry_ref, target_fib50, window_days)
        fetched = _fetch_high_low_window(row["ticker"], entry_ts, scaled_window, skip_entry_day=has_real_entry)
        if fetched is None:
            continue
        highs, lows, still_pending = fetched

        drop_size = (row["prev_close"] - row["last_close"]) if pd.notna(row["prev_close"]) and pd.notna(row["last_close"]) else None

        candidates = {"Fibonacci 50% (בפועל, עם רצפת 1:1)": target_fib50}
        if drop_size and drop_size > 0:
            candidates["Fibonacci 38.2%"] = row["last_close"] + 0.382 * drop_size
            candidates["Fibonacci 61.8%"] = row["last_close"] + 0.618 * drop_size
        for pct in CANDIDATE_TARGET_PCTS:
            candidates[f"קבוע +{pct*100:.0f}%"] = entry_ref * (1 + pct)

        for name, target in candidates.items():
            outcome = _outcome_from_series(highs, lows, target, stop_loss, still_pending)
            target_pct = (target / entry_ref - 1) * 100
            stop_pct = (stop_loss / entry_ref - 1) * 100
            if outcome == HIT_TARGET:
                trade_return = target_pct
            elif outcome == HIT_STOP:
                trade_return = stop_pct
            elif outcome == NEITHER:
                trade_return = 0.0  # שמרני - לא יודעים את המחיר בפועל בסוף החלון
            else:
                continue  # PENDING - עדיין לא הוכרע, לא נכנס לממוצע
            results.setdefault(name, []).append((outcome, trade_return))

    rows = []
    for name, entries in results.items():
        if not entries:
            continue
        outcomes = [o for o, _ in entries]
        hits = sum(1 for o in outcomes if o == HIT_TARGET)
        expectancy = sum(r for _, r in entries) / len(entries)
        rows.append({
            "אסטרטגיה": name, "סה\"כ": len(entries), "הגיעו ליעד": hits,
            "שיעור הצלחה (%)": round(hits / len(entries) * 100, 1),
            "תוחלת (%)": round(expectancy, 2),
        })
    return pd.DataFrame(rows).sort_values("תוחלת (%)", ascending=False).reset_index(drop=True)


def resolve_signal_outcomes(conn: sqlite3.Connection, older_than_days: int = 10, window_days: int = 10) -> int:
    """ממלא outcome_json עבור אותות-צל (signal_log, ר' scanner._log_shadow_signals)
    שנרשמו לפחות older_than_days ימים ועדיין לא הוכרעו. שולף את סדרת ה-High/Low
    האמיתית מאז רגע האות ומחשב MFE/MAE (התנועה הכי טובה/גרועה שהייתה זמינה)
    וכמה ימים לקח להגיע לכל אחת מהרמות +1%/+2%/+3%/+5% - בלי להניח יעד/סטופ
    ספציפיים, כדי שניתוח עתידי יוכל לבדוק כל שילוב שירצה על הדאטה הגולמי
    (בדיוק הרעיון של compare_target_strategies, רק על מדגם הרבה יותר רחב
    ממה שבאמת הפך להתראה). מחזיר כמה אותות עודכנו."""
    pending = store.get_unresolved_signals(conn, older_than_days=older_than_days)
    resolved_count = 0
    for sig in pending:
        entry = sig.get("last_close")
        if not entry:
            store.mark_signal_resolved(conn, sig["id"], json.dumps({"status": "no_data"}))
            resolved_count += 1
            continue

        fetched = _fetch_high_low_window(sig["ticker"], sig["scan_ts"], window_days, skip_entry_day=False)
        if fetched is None:
            store.mark_signal_resolved(conn, sig["id"], json.dumps({"status": "no_data"}))
            resolved_count += 1
            continue

        highs, lows, still_within_window = fetched
        if not highs or not lows:
            store.mark_signal_resolved(conn, sig["id"], json.dumps({"status": "no_data"}))
            resolved_count += 1
            continue
        if still_within_window:
            continue  # עוד מוקדם לסגור סופית - ייבדק שוב בהרצה הבאה

        mfe_pct = (max(highs) / entry - 1) * 100
        mae_pct = (min(lows) / entry - 1) * 100
        outcome = {
            "status": "resolved",
            "window_days": window_days,
            "mfe_pct": round(mfe_pct, 2),
            "mae_pct": round(mae_pct, 2),
            "days_to_mfe": highs.index(max(highs)) + 1,
            "days_to_mae": lows.index(min(lows)) + 1,
        }
        for pct in (1, 2, 3, 5):
            level = entry * (1 + pct / 100)
            day_idx = next((i for i, h in enumerate(highs) if h >= level), None)
            outcome[f"days_to_plus{pct}"] = (day_idx + 1) if day_idx is not None else None

        store.mark_signal_resolved(conn, sig["id"], json.dumps(outcome))
        resolved_count += 1
    return resolved_count


STOP_ATR_MULTIPLIERS = (1.0, 1.5, 2.0, 2.5)
_ATR_PERIOD = 14


def _fetch_atr_and_post_window(ticker: str, entry_ts: str, window_days: int, skip_entry_day: bool):
    """שולף חלון מחיר אחד רחב (לפני ואחרי תאריך ההתראה) לכל אלט - ATR מחושב
    מ-14 הימים שלפני ההתראה (אותו חישוב בדיוק כמו market_data.compute_atr
    בזמן אמת), וה-High/Low שאחרי משמשים לבדיקת התוצאה, בלי שתי קריאות רשת
    נפרדות. מחזיר (atr, highs_post, lows_post, still_within_window) או None."""
    try:
        scan_date = dt.datetime.fromisoformat(entry_ts).date()
    except Exception:
        return None
    if scan_date >= dt.date.today():
        return None

    calendar_buffer = int(window_days * 1.6) + 4
    start = scan_date - dt.timedelta(days=45)  # מרווח ליותר מ-14 ימי מסחר + סופי שבוע/חגים
    end = min(scan_date + dt.timedelta(days=calendar_buffer), dt.date.today())
    try:
        hist = yf.download(
            ticker, start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
            interval="1d", progress=False, auto_adjust=False, threads=False,
        )
    except Exception as e:
        logger.debug("נכשלה שליפת היסטוריה עבור %s: %s", ticker, e)
        return None
    if hist.empty:
        return None

    highs, lows, closes = hist["High"], hist["Low"], hist["Close"]
    if hasattr(highs, "columns"):
        highs, lows, closes = highs.iloc[:, 0], lows.iloc[:, 0], closes.iloc[:, 0]
    if _is_israeli_ticker(ticker):
        highs, lows, closes = highs / 100.0, lows / 100.0, closes / 100.0

    hist_dates = [d.date() if hasattr(d, "date") else d for d in hist.index]
    idx_candidates = [i for i, d in enumerate(hist_dates) if d <= scan_date]
    if not idx_candidates:
        return None
    alert_idx = idx_candidates[-1]
    if alert_idx < _ATR_PERIOD:
        return None  # לא מספיק היסטוריה לפני ההתראה כדי לחשב ATR אמין

    atr = market_data.compute_atr(
        highs.iloc[:alert_idx + 1], lows.iloc[:alert_idx + 1], closes.iloc[:alert_idx + 1], period=_ATR_PERIOD
    )
    if atr is None or atr <= 0:
        return None

    post_start = alert_idx + 1 if skip_entry_day else alert_idx
    post_highs = highs.iloc[post_start:post_start + window_days].dropna().tolist()
    post_lows = lows.iloc[post_start:post_start + window_days].dropna().tolist()
    still_within_window = (dt.date.today() - scan_date).days < calendar_buffer
    return atr, post_highs, post_lows, still_within_window


def compare_stop_multipliers(conn: sqlite3.Connection, window_days: int = 10) -> pd.DataFrame:
    """משווה כמה מכפילי ATR שונים לסטופ-לוס (1.0-2.5) על אותן התראות היסטוריות
    בדיוק, עם אותו יעד קבוע (target_base כפי שנשמר בזמן ההתראה - לא משתנה כאן,
    רק מרחק הסטופ) - כדי לבודד את ההשפעה של הרחבת/צמצום הסטופ בלבד, בלי
    שהיעד יזוז יחד איתו. מגבלה חשובה: anchor (הבסיס לחישוב הסטופ) מקורב
    ל-entry_limit/מחיר כניסה בפועל - last_low ההיסטורי לא נשמר בטבלה, אז אי
    אפשר לשחזר אותו במדויק בדיעבד. זה מכניס סטייה קטנה מול איך שהסטופ באמת
    חושב בזמן אמת, אבל לא משנה את המסקנה ההשוואתית בין המכפילים עצמם.
    מחזיר טבלת סיכום כמו compare_target_strategies: מכפיל, סה"כ, הגיעו ליעד,
    שיעור הצלחה (%), תוחלת (%)."""
    df = pd.read_sql_query(
        "SELECT ticker, scan_ts, entry_limit, target_base, bought, actual_entry_price, bought_at "
        "FROM alerts WHERE entry_limit IS NOT NULL AND target_base IS NOT NULL",
        conn,
    )
    if df.empty:
        return pd.DataFrame(columns=["מכפיל ATR", "סה\"כ", "הגיעו ליעד", "שיעור הצלחה (%)", "תוחלת (%)"])

    results: dict[float, list[tuple[str, float]]] = {}
    for _, row in df.iterrows():
        has_real_entry = bool(row["bought"]) and row["actual_entry_price"] and row["bought_at"]
        entry_ref = row["actual_entry_price"] if has_real_entry else row["entry_limit"]
        entry_ts = row["bought_at"] if has_real_entry else row["scan_ts"]
        target = row["target_base"]

        fetched = _fetch_atr_and_post_window(row["ticker"], entry_ts, window_days, skip_entry_day=has_real_entry)
        if fetched is None:
            continue
        atr, post_highs, post_lows, still_pending = fetched
        if not post_highs or not post_lows:
            continue

        for mult in STOP_ATR_MULTIPLIERS:
            stop = entry_ref - mult * atr
            if stop <= 0:
                continue
            outcome = _outcome_from_series(post_highs, post_lows, target, stop, still_pending)
            target_pct = (target / entry_ref - 1) * 100
            stop_pct = (stop / entry_ref - 1) * 100
            if outcome == HIT_TARGET:
                trade_return = target_pct
            elif outcome == HIT_STOP:
                trade_return = stop_pct
            elif outcome == NEITHER:
                trade_return = 0.0
            else:
                continue  # PENDING
            results.setdefault(mult, []).append((outcome, trade_return))

    rows = []
    for mult, entries in results.items():
        if not entries:
            continue
        outcomes = [o for o, _ in entries]
        hits = sum(1 for o in outcomes if o == HIT_TARGET)
        expectancy = sum(r for _, r in entries) / len(entries)
        rows.append({
            "מכפיל ATR": f"{mult:g}x", "סה\"כ": len(entries), "הגיעו ליעד": hits,
            "שיעור הצלחה (%)": round(hits / len(entries) * 100, 1),
            "תוחלת (%)": round(expectancy, 2),
        })
    return pd.DataFrame(rows).sort_values("תוחלת (%)", ascending=False).reset_index(drop=True)


def retrofit_historical_stops(conn: sqlite3.Connection, multiplier: float | None = None) -> int:
    """מעדכן stop_loss בפועל (UPDATE ב-DB) עבור כל ההתראות ההיסטוריות הקיימות,
    לפי מכפיל ATR חדש (ר' strategy.ATR_STOP_MULTIPLIER) - כדי ש'ביצועי
    האסטרטגיה' ישקפו את אותו מכפיל גם על התראות ישנות, לא רק חדשות. היעד
    (target_base) לא נוגעים בו בכלל - לבקשת המשתמש (23.8.2026), הסטופ מתרחב
    בלי שהיעד זז יחד איתו.
    מגבלה מתועדת: anchor (הבסיס לחישוב הסטופ) מקורב ל-entry_limit/מחיר כניסה
    בפועל - last_low ההיסטורי לא נשמר בטבלה, אז אי אפשר לשחזר אותו במדויק
    (אותה מגבלה כמו compare_stop_multipliers). מחזיר כמה שורות עודכנו בפועל."""
    mult = multiplier if multiplier is not None else strategy_mod.ATR_STOP_MULTIPLIER
    rows = conn.execute(
        "SELECT id, ticker, scan_ts, entry_limit, bought, actual_entry_price, bought_at "
        "FROM alerts WHERE entry_limit IS NOT NULL"
    ).fetchall()
    columns = ["id", "ticker", "scan_ts", "entry_limit", "bought", "actual_entry_price", "bought_at"]

    updated = 0
    for raw in rows:
        r = dict(zip(columns, raw))
        has_real_entry = bool(r["bought"]) and r["actual_entry_price"] and r["bought_at"]
        entry_ref = r["actual_entry_price"] if has_real_entry else r["entry_limit"]
        entry_ts = r["bought_at"] if has_real_entry else r["scan_ts"]

        fetched = _fetch_atr_and_post_window(r["ticker"], entry_ts, window_days=1, skip_entry_day=has_real_entry)
        if fetched is None:
            continue
        atr, _post_highs, _post_lows, _still_pending = fetched
        new_stop = round(entry_ref - mult * atr, 2)
        if new_stop <= 0:
            continue

        conn.execute("UPDATE alerts SET stop_loss = ? WHERE id = ?", (new_stop, r["id"]))
        updated += 1
    conn.commit()
    return updated


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
