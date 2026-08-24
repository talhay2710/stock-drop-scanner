"""בדיקת שעות מסחר לפי המדד (ארה"ב / ישראל).

חשוב: מ-5.1.2026 הבורסה לניירות ערך בתל אביב (TASE) עברה משבוע מסחר
ראשון-חמישי לשבוע מסחר שני-שישי (כמו בשווקים הגלובליים), עם יום שישי מקוצר
שנסגר מוקדם לקראת כניסת השבת. יום ראשון כבר אינו יום מסחר.
מקור: https://www.tase.co.il/en/content/about/tradingdays_change
"""
import datetime as dt
from zoneinfo import ZoneInfo

from .constituents import INDEX_COUNTRY_CODE

MARKET_HOURS = {
    "US": {
        "tz": "America/New_York", "open": (9, 30), "close": (16, 0),
        "weekdays": {1, 2, 3, 4, 5}, "close_overrides": {},
    },
    "IL": {
        "tz": "Asia/Jerusalem", "open": (9, 59), "close": (17, 30),
        "weekdays": {1, 2, 3, 4, 5},
        "close_overrides": {5: (14, 0)},  # יום שישי - מסחר מקוצר
    },
}


def israel_now() -> dt.datetime:
    """זמן נוכחי לפי שעון ישראל, לא לפי שעון המערכת שמריץ את הקוד - הסריקה
    בענן (GitHub Actions) רצה על UTC, אז scan_ts שנשמר עם dt.datetime.now()
    רגיל היה מוצג בדשבורד באיחור של 2-3 שעות (בהתאם לשעון קיץ/חורף) לעומת
    השעה האמיתית בישראל (24.8.2026)."""
    return dt.datetime.now(ZoneInfo("Asia/Jerusalem"))


def israel_today() -> dt.date:
    """תאריך 'היום' לפי שעון ישראל, לא לפי שעון המערכת שמריץ את הקוד - כדי
    שהדשבורד המקומי (שעון ישראל) והציבורי/הסריקה (UTC ב-GitHub Actions
    ו-Streamlit Cloud) יתחלפו ל'יום חדש' באותו רגע בדיוק, במקום בפער של
    כמה שעות בלילה (24.8.2026)."""
    return israel_now().date()


def _close_for_weekday(spec: dict, weekday: int) -> tuple[int, int]:
    return spec.get("close_overrides", {}).get(weekday, spec["close"])


def is_market_open(index: str) -> bool:
    country = INDEX_COUNTRY_CODE[index.upper()]
    spec = MARKET_HOURS[country]
    now = dt.datetime.now(ZoneInfo(spec["tz"]))
    if now.isoweekday() not in spec["weekdays"]:
        return False
    close_hm = _close_for_weekday(spec, now.isoweekday())
    open_t = now.replace(hour=spec["open"][0], minute=spec["open"][1], second=0, microsecond=0)
    close_t = now.replace(hour=close_hm[0], minute=close_hm[1], second=0, microsecond=0)
    return open_t <= now <= close_t


def get_market_status(country: str) -> dict:
    """מחזיר תמונת מצב מדויקת של השוק: פתוח/סגור, הזמן המקומי, ומתי האירוע
    הבא (פתיחה/סגירה) יחד עם ספירה לאחור אליו. מתחשב בסגירה מוקדמת בימי שישי בישראל."""
    spec = MARKET_HOURS[country]
    tz = ZoneInfo(spec["tz"])
    now = dt.datetime.now(tz)

    def at(day: dt.date, hm: tuple[int, int]) -> dt.datetime:
        return dt.datetime.combine(day, dt.time(hm[0], hm[1]), tzinfo=tz)

    today_open = at(now.date(), spec["open"])
    today_close = at(now.date(), _close_for_weekday(spec, now.isoweekday()))
    is_trading_day = now.isoweekday() in spec["weekdays"]

    if is_trading_day and today_open <= now <= today_close:
        return {"open": True, "now": now, "next_change": today_close, "next_label": "נסגר"}

    if is_trading_day and now < today_open:
        next_open = today_open
    else:
        d = now.date()
        for _ in range(8):
            d = d + dt.timedelta(days=1)
            if d.isoweekday() in spec["weekdays"]:
                next_open = at(d, spec["open"])
                break

    return {"open": False, "now": now, "next_change": next_open, "next_label": "נפתח"}


def format_countdown(target: dt.datetime, now: dt.datetime) -> str:
    delta = target - now
    total_minutes = max(0, int(delta.total_seconds() // 60))
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    if days > 0:
        return f"{days} ימים ו-{hours} שעות"
    if hours > 0:
        return f"{hours} שעות ו-{minutes} דקות"
    return f"{minutes} דקות"
