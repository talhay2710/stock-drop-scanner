"""בודק את data/tase_closed_days.csv מול yfinance. לכל יום חול בחודשיים האחרונים:
  - אין מסחר אמיתי (Volume>0) ביותר מ-95% ממניות ת"א35 ולא מופיע בקובץ => חג שחסר
    (רק לימים ישנים מ-5 ימים: חור זמני של yfinance, כמו 30.9.2026, מתמלא תוך ימים)
  - מופיע בקובץ כסגור אבל יש בו מסחר אמיתי => חג שגוי בקובץ
  - בדצמבר ועדיין אין חגים של השנה הבאה בקובץ => להוסיף את הלוח
מדפיס פערים ויוצא עם קוד 1 (ריצה שבועית ב-.github/workflows/calendar_check.yml,
כשל = מייל מ-GitHub). רץ מקומית: python check_tase_calendar.py"""
import datetime as dt
import sys

import yfinance as yf

from src import constituents
from src.market_hours import _tase_closed_days

LOOKBACK_DAYS = 60
RECENT_GRACE_DAYS = 5


def main() -> int:
    today = dt.date.today()
    closed = _tase_closed_days()
    problems: list[str] = []

    # בין החגים של סוכות לפסח אין ימי סגירה, אז "הקובץ נגמר מוקדם" לבדו לא תקלה -
    # אבל בדצמבר חייב להיות כבר לוח של השנה הבאה.
    if not closed:
        problems.append("הקובץ ריק")
    elif today.month == 12 and max(closed).year <= today.year:
        problems.append(f"דצמבר ועדיין אין חגים של {today.year + 1} בקובץ (האחרון: {max(closed)})")

    tickers = constituents.get_constituents("TA35")
    data = yf.download(
        tickers, start=(today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat(),
        end=(today + dt.timedelta(days=1)).isoformat(),
        interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True,
    )
    day = today - dt.timedelta(days=LOOKBACK_DAYS)
    while day < today:
        if day.weekday() < 5:  # שני-שישי (מ-5.1.2026 הבורסה פתוחה גם בשישי)
            traded = 0
            for t in tickers:
                try:
                    vol = data[t]["Volume"]
                    vol = vol[[d.date() == day for d in vol.index]]
                    if len(vol) and float(vol.iloc[0]) > 0:
                        traded += 1
                except Exception:
                    continue
            share = traded / len(tickers)
            if day in closed and share > 0.5:
                problems.append(f"{day}: מופיע כסגור בקובץ אבל נסחרו {traded}/{len(tickers)} מניות")
            elif day not in closed and share < 0.05 and (today - day).days > RECENT_GRACE_DAYS:
                problems.append(f"{day}: אין מסחר אצל {len(tickers) - traded}/{len(tickers)} מניות ולא מופיע בקובץ (חג שחסר?)")
        day += dt.timedelta(days=1)

    if problems:
        print("נמצאו פערים בלוח החגים:")
        for p in problems:
            print(" -", p)
        return 1
    print("לוח החגים תקין.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
