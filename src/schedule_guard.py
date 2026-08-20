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

_TZ = ZoneInfo("Asia/Jerusalem")


def in_window(start_hour: int, start_minute: int, end_hour: int, end_minute: int, weekday: int | None = None) -> bool:
    """weekday: 0=שני ... 4=שישי ... 6=ראשון (Python weekday()), None = כל יום."""
    now = dt.datetime.now(_TZ)
    if weekday is not None and now.weekday() != weekday:
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
