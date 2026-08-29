"""שולח דוח שבועי אחד בטלגרם: אילו סוגי סיבות-ירידה הצליחו יותר בשבוע האחרון.
מיועד להרצה פעם בשבוע (ראה setup_task_scheduler_weekly_report.ps1).
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config, db_path
from src.store import get_conn
from src.backtest import refresh_pending_outcomes
from src.weekly_report import build_weekly_report
from src import notifier, schedule_guard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    # ר' run_daily_summary.py - אותה הגנה מפני שליחה בשעה/פעם לא נכונה, מותאמת
    # לחלון הזמן של הדוח השבועי (ראשון ~15:00 שעון ישראל בלבד - הועבר משישי
    # כי זה עדיין יום מסחר, לא הגיוני לסכם "שבוע" באמצעו).
    cfg = load_config()
    conn = get_conn(db_path(cfg))
    try:
        if not schedule_guard.in_window(15, 0, 15, 15, weekday=6):
            print("דילוג - מחוץ לחלון הזמן של הדוח השבועי (ראשון ~15:00 שעון ישראל).")
            sys.exit(0)
        if schedule_guard.already_sent_today(conn, "weekly"):
            print("דילוג - כבר נשלח דוח שבועי היום.")
            sys.exit(0)

        refresh_pending_outcomes(conn)
        message = build_weekly_report(conn)

        if message:
            notifier.notify_typed(cfg, "weekly_report", message, "📊 דוח שבועי", "")
            schedule_guard.mark_sent_today(conn, "weekly")
            print("דוח שבועי נשלח.")
        else:
            print("אין מספיק התראות עם תוצאה השבוע - לא נשלח דוח.")
    finally:
        conn.close()
