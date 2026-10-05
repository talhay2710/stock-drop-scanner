"""שולח הודעת טלגרם אחת בתחילת יום המסחר (כ-10 דקות אחרי פתיחת ת"א): תמונת מצב
מיידית - האחזקות שלך והמניות הכי בולטות (עולות/יורדות) בכל מדד שנסרק. בניגוד
לסיכום היומי (run_daily_summary.py, שמבוסס על התראות שנשלחו באותו יום) זה
snapshot חי של המחירים ברגע השליחה. מיועד להרצה פעם אחת ביום ~10:10
(ראה setup_task_scheduler_morning_summary.ps1).
"""
import logging
import sys
import os
import ctypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ר' run_daily_summary.py להסבר המלא על הצורך ב-ES_SYSTEM_REQUIRED כאן -
# אותה בעיה בדיוק (Task Scheduler מעיר את המחשב כדי *להתחיל*, לא מונע ממנו
# לחזור לישון תוך כדי הריצה).
if sys.platform == "win32":
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

from src.config import load_config, db_path
from src.store import get_conn
from src.daily_summary import build_morning_summary
from src.holdings_summary import build_holdings_summary
from src import market_data, notifier, constituents, schedule_guard
from src.market_hours import israel_today


def _build_movers_by_index(cfg) -> dict[str, list[dict]]:
    # רק ת"א - הדוח נשלח ~10:10-10:45 שעון ישראל, מיד אחרי פתיחת ת"א, אבל
    # שעות לפני פתיחת ארה"ב (16:30 שעון ישראל). "שינוי היום" למדדי ארה"ב
    # באותה שעה הוא בהכרח עדיין השינוי של *אתמול* (הסגירה האחרונה הזמינה) -
    # לא רלוונטי לדוח "תחילת יום", מטעה כאילו זה נתון של היום (9.9.2026,
    # "זה נכון לאתמול. לא רלוונטי").
    movers_by_index: dict[str, list[dict]] = {}
    for index_name in (cfg.get("indices") or []):
        if index_name.upper() not in ("TA35", "TA125"):
            continue
        tickers = constituents.get_constituents(index_name)
        df = market_data.fetch_universe_daily_changes(tickers)
        if df.empty:
            continue
        name_map = (
            constituents.get_il_name_map(index_name) if index_name.upper() in ("TA35", "TA125")
            else constituents.get_us_name_map(index_name)
        )
        # שורה עם prev_close_gap לא מוצגת: האחוז שלה פורש כמה ימי מסחר ולא יום, וכאן
        # הוא מתויג כשינוי יומי (1.10.2026, "אני לא מוכן שתשלח לי נתונים לא נכונים").
        movers_by_index[index_name] = [
            {"ticker": r["ticker"], "name": name_map.get(r["ticker"], r["ticker"]), "pct_change": r["pct_change"]}
            for _, r in df.iterrows() if not r.get("prev_close_gap")
        ]
    return movers_by_index


def _build_index_changes(cfg) -> dict[str, float | None]:
    # רק ת"א - ר' הערה ב-_build_movers_by_index למעלה, אותה סיבה בדיוק.
    return {
        index_name: market_data.fetch_index_proxy_change(index_name)
        for index_name in (cfg.get("indices") or [])
        if index_name.upper() in ("TA35", "TA125")
    }


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    # ר' run_daily_summary.py - אותה הגנה מפני שליחה בשעה/פעם לא נכונה (הרצת-
    # השלמה מקומית של Task Scheduler, או ריצות חוזרות של scan.yml בענן),
    # מותאמת לחלון הזמן של דוח הבוקר (~10:30 שעון ישראל).
    try:
        cfg = load_config()
        conn = get_conn(db_path(cfg))
        try:
            if not schedule_guard.in_window(10, 30, 10, 45, weekday=schedule_guard.TRADING_WEEKDAYS):
                print("דילוג - מחוץ לחלון הזמן של דוח הבוקר (~10:30 שעון ישראל).")
                sys.exit(0)
            if schedule_guard.already_sent_today(conn, "morning"):
                print("דילוג - כבר נשלח דוח בוקר היום.")
                sys.exit(0)

            holdings_summary = build_holdings_summary(conn, cfg)

            index_changes = _build_index_changes(cfg)
            movers_by_index = _build_movers_by_index(cfg)
            message = build_morning_summary(
                israel_today().isoformat(), index_changes, holdings_summary, movers_by_index,
            )

            if message:
                if schedule_guard.send_and_mark(conn, cfg, "morning", "morning_summary", message, "🌅 תמונת מצב - תחילת יום"):
                    print("תמונת מצב בוקר נשלחה.")
                else:
                    print("שליחת תמונת הבוקר נכשלה - לא מסומן כנשלח, ינסה שוב בתוך החלון.")
            else:
                print("אין נתונים - לא נשלח דוח בוקר.")
        finally:
            conn.close()
    finally:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
