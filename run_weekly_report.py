"""שולח דוח שבועי אחד בטלגרם: אילו סוגי סיבות-ירידה הצליחו יותר בשבוע האחרון.
מיועד להרצה פעם בשבוע (ראה setup_task_scheduler_weekly_report.ps1).
"""
import logging
import sys
import os
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config, db_path
from src.store import get_conn
from src.backtest import refresh_pending_outcomes
from src.weekly_report import build_weekly_report
from src import notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    # ר' run_daily_summary.py - אותה הגנה מפני הרצת-השלמה של Task Scheduler
    # בשעה לא סבירה, מותאמת לחלון הזמן של הדוח השבועי (~15:00).
    _now_hour = dt.datetime.now().hour
    if not (13 <= _now_hour <= 19):
        print(f"דילוג - הופעל בשעה לא סבירה לדוח שבועי ({_now_hour}:00), כנראה הרצת השלמה של Task Scheduler.")
        sys.exit(0)

    cfg = load_config()
    conn = get_conn(db_path(cfg))
    try:
        refresh_pending_outcomes(conn)
        message = build_weekly_report(conn)
    finally:
        conn.close()

    if message:
        notifier.send_telegram(cfg, message)
        print("דוח שבועי נשלח.")
    else:
        print("אין מספיק התראות עם תוצאה השבוע - לא נשלח דוח.")
