"""מריץ Windows toast מקומי על כל התראה/סיכום חדשים - "מחליף" את התראות
הדסקטופ שהתפוצצו בשקט אחרי המעבר לסריקה-בענן-בלבד (14.9.2026, "גם לא ראיתי
התראות בדסקטופ"). הסריקה עצמה (scanner.py) עדיין רצה רק בענן (GitHub
Actions, לינוקס - אין שם winotify) - הקובץ הזה לא סורק שום דבר בעצמו, רק
בודק כל כמה דקות (Task Scheduler, ר' setup_task_scheduler_desktop_notify.ps1)
אם הגיעו שורות חדשות ל-alerts.db המקומי (אחרי git pull בטוח) לעומת בפעם
הקודמת, ומראה toast על כל אחת. אין כאן שום ניסיון-חוזר/סף/החלטה - כל זה כבר
קרה בענן; זה רק "מודיע על מה שכבר קרה".

מריץ פעם אחת ויוצא (לא לולאה) - מיועד להיקרא חוזר ונשנה ע"י Task Scheduler.
"""
import ctypes
import json
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config, db_path
from src.store import get_conn
from src import notifier

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT_DIR, ".desktop_notify_state.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(ROOT_DIR, "desktop_notify.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# מיפוי kind ב-summary_log -> (message_type ל"סוגי התראה", כותרת toast)
_SUMMARY_TOAST = {
    "morning": ("morning_summary", "🌅 תמונת מצב - תחילת יום נשלחה"),
    "daily": ("daily_summary", "📊 סיכום יומי נשלח"),
    "weekly": ("weekly_report", "📈 דוח שבועי נשלח"),
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    # CREATE_NO_WINDOW - בלעדיו, כל תת-תהליך קונסולה (git.exe) פותח לעצמו
    # חלון חדש משלו גם כש-pythonw.exe עצמו (ההורה) בלי קונסולה בכלל - זה
    # ה"חלון שחור קופץ לשנייה" (14.9.2026, נצפה בפועל אחרי רישום המשימה).
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True, timeout=30,
                           creationflags=creationflags)


def _git_pull_safely() -> None:
    """אותה טכניקה בדיוק שנעשית ידנית לאורך כל הסשן הזה כשעובדים על
    dashboard.py: alerts.db הוא קובץ בינארי שהדשבורד המקומי עצמו יכול לכתוב
    אליו בין ריצה לריצה (קנייה/מכירה) - stash -u -- לפני pull, ואם ה-pop
    מתנגש (בינארי, תמיד יתנגש) - הגרסה המקומית מנצחת (checkout --ours),
    כי זו בדיוק הסיבה שסטאשנו אותה מלכתחילה."""
    status = _run(["git", "status", "--short", "--", "alerts.db"]).stdout.strip()
    stashed = False
    if status:
        _run(["git", "stash", "push", "-u", "--", "alerts.db"])
        stashed = True

    pull = _run(["git", "pull", "--quiet"])
    if pull.returncode != 0:
        logger.warning("git pull נכשל: %s", pull.stderr.strip())

    if stashed:
        pop = _run(["git", "stash", "pop"])
        if pop.returncode != 0:
            _run(["git", "checkout", "--ours", "--", "alerts.db"])
            _run(["git", "add", "alerts.db"])
            _run(["git", "stash", "drop"])


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_alert_id": 0, "seen_summaries": []}


def _save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _notify_new_alerts(conn, cfg: dict, state: dict) -> None:
    rows = conn.execute(
        "SELECT id, ticker, company_name, pct_change FROM alerts WHERE id > ? ORDER BY id",
        (state["last_alert_id"],),
    ).fetchall()
    for row in rows:
        alert_id, ticker, name, pct_change = row
        state["last_alert_id"] = max(state["last_alert_id"], alert_id)
        if not notifier.is_message_type_enabled(cfg, "drop_alert"):
            continue
        title = f"📉 {name or ticker} ({ticker})"
        message = f"ירידה של {abs(pct_change):.1f}%" if pct_change is not None else "התראת ירידה חדשה"
        notifier.send_desktop_notification(cfg, title, message)
        logger.info("toast: %s - %s", title, message)


def _notify_new_summaries(conn, cfg: dict, state: dict) -> None:
    rows = conn.execute("SELECT kind, sent_date FROM summary_log").fetchall()
    seen = set(state.get("seen_summaries", []))
    for kind, sent_date in rows:
        key = f"{kind}:{sent_date}"
        if key in seen:
            continue
        seen.add(key)
        message_type, title = _SUMMARY_TOAST.get(kind, (None, None))
        if message_type and notifier.is_message_type_enabled(cfg, message_type):
            notifier.send_desktop_notification(cfg, title, "פרטים מלאים בטלגרם.")
            logger.info("toast: %s", title)
    state["seen_summaries"] = sorted(seen)


if __name__ == "__main__":
    if sys.platform == "win32":
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        cfg = load_config()
        if not cfg.get("desktop_notifications", {}).get("enabled"):
            logger.info("desktop_notifications כבוי בהגדרות - דילוג.")
            sys.exit(0)

        _git_pull_safely()

        state = _load_state()
        conn = get_conn(db_path(cfg))
        try:
            # רק אחרי שכבר יש last_alert_id אמיתי (לא בהרצה הראשונה) -
            # אחרת ההרצה הראשונה "מתריעה" על כל ההיסטוריה הקיימת בבת אחת.
            first_run = state["last_alert_id"] == 0 and not state.get("seen_summaries")
            if first_run:
                max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
                state["last_alert_id"] = max_id
                rows = conn.execute("SELECT kind, sent_date FROM summary_log").fetchall()
                state["seen_summaries"] = [f"{k}:{d}" for k, d in rows]
                logger.info("הרצה ראשונה - מסמן %d התראות ו-%d סיכומים קיימים כ'כבר נראו', בלי toast.",
                            max_id, len(rows))
            else:
                _notify_new_alerts(conn, cfg, state)
                _notify_new_summaries(conn, cfg, state)
        finally:
            conn.close()

        _save_state(state)
    finally:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
