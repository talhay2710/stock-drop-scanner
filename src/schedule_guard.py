"""בדיקה משותפת לסקריפטי סיכום (יומי/בוקר/שבועי): האם עכשיו בתוך חלון הזמן
הסביר להרצה, ולא נשלח כבר היום. נועד לשרת שני הקשרים בו-זמנית:
- הרצה מקומית (Task Scheduler) - עלולה להתעורר בשעה שגויה אם המחשב היה כבוי
  (StartWhenAvailable), אז חלון הזמן מונע שליחה בשעה הזויה.
- הרצה בענן (GitHub Actions, בתוך scan.yml) - רצה כל 5 דקות ובודקת לבד אם
  הגיע הזמן, אז גם חלון הזמן וגם בדיקת "כבר נשלח" נחוצים כדי לא להציף.
תמיד לפי שעון ישראל (Asia/Jerusalem), לא שעון המחשב המריץ - כי ה-runner של
GitHub Actions רץ ב-UTC, וזה חייב להתנהג זהה בשני המקומות."""
import datetime as dt
from zoneinfo import ZoneInfo

from . import store as store_mod
from . import notifier
from .market_hours import is_trading_day

_TZ = ZoneInfo("Asia/Jerusalem")

# ימי מסחר (Python weekday(): 0=שני ... 6=ראשון) - תואם ל-_CLOSED_WEEKDAYS
# ב-market_data.py ול-MARKET_HOURS ב-market_hours.py (שני-שישי, לא שבת/ראשון).
TRADING_WEEKDAYS = {0, 1, 2, 3, 4}


def in_window(
    start_hour: int, start_minute: int, end_hour: int, end_minute: int,
    weekday: int | set[int] | None = None,
) -> bool:
    """weekday: יום בודד, אוסף ימים (למשל TRADING_WEEKDAYS), או None = כל יום."""
    now = dt.datetime.now(_TZ)
    if weekday is not None:
        allowed = {weekday} if isinstance(weekday, int) else set(weekday)
        if now.weekday() not in allowed:
            return False
        # יום חול שהבורסה סגורה בו (חג/ערב חג) - לא שולחים סיכום "יומי/בוקר" על נתוני
        # היום הקודם כאילו היו של היום (קרה ב-2.10.2026: נשלחו סיכום בוקר ויומי ביום חג).
        if not is_trading_day("IL", now.date()) and now.weekday() in TRADING_WEEKDAYS:
            return False
    start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return start <= now <= end


def already_sent_today(conn, kind: str) -> bool:
    today = dt.datetime.now(_TZ).date().isoformat()
    return store_mod.was_summary_sent(conn, kind, today)


def mark_sent_today(conn, kind: str) -> None:
    today = dt.datetime.now(_TZ).date().isoformat()
    store_mod.mark_summary_sent(conn, kind, today)


def send_and_mark(conn, cfg, kind: str, message_type: str, message: str, title: str) -> bool:
    """שולח הודעה ומסמן "נשלח היום" רק אם הטלגרם באמת קיבל אותה (או שסוג ההודעה
    כבוי בכוונה). שליחה שנכשלה לא מסומנת, כך שהריצה הבאה בתוך החלון תנסה שוב
    במקום לדלג בשקט (5.10.2026)."""
    msg_id = notifier.notify_typed(cfg, message_type, message, title, "")
    if msg_id is not None or not notifier.is_message_type_enabled(cfg, message_type):
        mark_sent_today(conn, kind)
        return True
    return False
