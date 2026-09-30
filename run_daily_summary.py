"""שולח סיכום יומי אחד בטלגרם על כל ההתראות שנשלחו היום, עם מחיר עדכני מול
הכניסה/יעד/סטופ שהוצעו. מיועד להרצה פעם אחת ביום אחרי סגירת המסחר האמריקאי
(ראה setup_task_scheduler.ps1).
"""
import logging
import sys
import os
import ctypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ה-Task Scheduler מגדיר "להעיר את המחשב כדי להריץ" - אבל זה רק מעיר אותו
# כדי *להתחיל*, לא מונע ממנו לחזור לישון (Modern Standby) תוך כדי הריצה.
# נצפה בפועל: המחשב יצא משינה, המשימה התחילה, והמחשב חזר לישון תוך שנייה -
# הפייתון נהרג עוד לפני שהספיק לכתוב אפילו שורת לוג אחת. ES_SYSTEM_REQUIRED
# אומר ל-Windows "אל תירדם כל עוד אני רץ" - בלי זה, הנעילה על השעון בלבד לא מספיקה.
if sys.platform == "win32":
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

from src.config import load_config, db_path
from src.store import get_conn, get_closed_trades_on_date
from src.daily_summary import build_daily_summary
from src.holdings_summary import build_holdings_summary, enrich_closed_today_with_today_pnl
from src import notifier, backtest, schedule_guard
from src.market_hours import israel_today

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    # מיועד לרוץ ~18:00 שעון ישראל. שני שימושים אפשריים: (א) Task Scheduler
    # מקומי - אם המחשב היה כבוי בזמן המתוזמן, StartWhenAvailable מריץ את
    # המשימה שהוחמצה מיד כשהמחשב מתעורר, גם אם זה 3 לפנות בוקר. (ב) scan.yml
    # בענן - רץ כל 5 דק' ומזהה לבד מתי הגיע הזמן. חלון הזמן + "כבר נשלח היום"
    # מגנים משני התרחישים גם יחד - ר' src/schedule_guard.py.
    try:
        cfg = load_config()
        conn = get_conn(db_path(cfg))
        try:
            if not schedule_guard.in_window(18, 0, 18, 15, weekday=schedule_guard.TRADING_WEEKDAYS):
                print("דילוג - מחוץ לחלון הזמן של הסיכום היומי (~18:00 שעון ישראל).")
                sys.exit(0)
            if schedule_guard.already_sent_today(conn, "daily"):
                print("דילוג - כבר נשלח סיכום יומי היום.")
                sys.exit(0)

            today = israel_today().isoformat()
            holdings_summary = build_holdings_summary(conn, cfg)
            closed_today = enrich_closed_today_with_today_pnl(get_closed_trades_on_date(conn, today))
            message = build_daily_summary(conn, today, holdings_summary, closed_today=closed_today)

            updated = backtest.refresh_pending_outcomes(conn)
            if updated:
                print(f"עודכנו {updated} outcome-ים היסטוריים (לטרק-רקורד עתידי).")

            signals_resolved = backtest.resolve_signal_outcomes(conn)
            if signals_resolved:
                print(f"נפתרו {signals_resolved} אותות-צל (signal_log).")

            if message:
                notifier.notify_typed(cfg, "daily_summary", message, "📅 סיכום יומי", "")
                schedule_guard.mark_sent_today(conn, "daily")
                print("סיכום יומי נשלח.")
            else:
                print("אין התראות היום - לא נשלח סיכום.")
        finally:
            conn.close()
    finally:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
