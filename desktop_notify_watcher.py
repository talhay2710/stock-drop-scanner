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
from datetime import datetime
from zoneinfo import ZoneInfo

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
MAX_INDIVIDUAL_TOASTS = 5

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


def _sync_alerts_db(local_path: str) -> bool:
    """מעדכן את alerts.db המקומי מהענן בלי git pull: `git pull` נכשל כשהענף המקומי התפצל מ-origin (למשל שינויי ממשק שעוד לא עלו) או
    כשיש שינויים מקומיים, ואז ההתראות החדשות מהענן אף פעם לא מגיעות לכאן. כאן: fetch, ואז מיזוג ברמת עמודה (src/db_merge.py) של הקובץ
    מ-origin/master (נתוני הסריקה של הבוט) עם הקובץ המקומי (קנייה/מכירה/התראות מחיר שבבעלות הדשבורד) - אף צד לא דורס את השני."""
    from src import db_merge
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    fetch = _run(["git", "fetch", "--quiet", "origin"])
    if fetch.returncode != 0:
        logger.warning("git fetch נכשל: %s", fetch.stderr.strip())
        return False
    show = subprocess.run(["git", "show", "origin/master:alerts.db"], cwd=ROOT_DIR, capture_output=True, timeout=60, creationflags=creationflags)
    if show.returncode != 0 or not show.stdout:
        logger.warning("git show alerts.db נכשל: %s", show.stderr.decode("utf-8", "replace").strip())
        return False
    origin_tmp, merged_tmp = local_path + ".origin.tmp", local_path + ".merged.tmp"
    try:
        with open(origin_tmp, "wb") as f:
            f.write(show.stdout)
        db_merge.merge(origin_tmp, local_path, merged_tmp)
        os.replace(merged_tmp, local_path)
        return True
    except Exception as e:
        logger.warning("מיזוג alerts.db מהענן נכשל: %s", e)
        return False
    finally:
        for tmp in (origin_tmp, merged_tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


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


def _parse_ts(value):
    """זמן כ-datetime עם אזור זמן. שורות ישנות שמורות כזמן ישראל בלי tz."""
    try:
        ts = datetime.fromisoformat(str(value))
    except Exception:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=ZoneInfo("Asia/Jerusalem"))


def _notify_new_alerts(conn, cfg: dict, state: dict) -> None:
    rows = conn.execute(
        "SELECT id, ticker, company_name, pct_change, scan_ts FROM alerts WHERE id > ? ORDER BY id",
        (state["last_alert_id"],),
    ).fetchall()
    if rows:
        state["last_alert_id"] = max(state["last_alert_id"], rows[-1][0])
    # רק התראות שנוצרו מרגע ההפעלה של הערוץ (enabled_since נרשם בדשבורד בעת הפעלה) - לא היסטוריה
    since = _parse_ts(cfg.get("desktop_notifications", {}).get("enabled_since"))
    if since is not None:
        rows = [r for r in rows if (_parse_ts(r[4]) or since) >= since]
    rows = [r[:4] for r in rows]
    if not notifier.is_message_type_enabled(cfg, "drop_alert"):
        return
    # הגנה מהצפה: אם הצטברו הרבה התראות בבת אחת (למשל הפעלה מחדש אחרי הפסקה, או שחזור של alerts.db) - toast אחד מסכם
    # במקום עשרות, ורק על ההתראות האחרונות
    if len(rows) > MAX_INDIVIDUAL_TOASTS:
        notifier.send_desktop_notification(cfg, "📉 התראות ירידה חדשות", f"{len(rows)} התראות חדשות מאז הבדיקה האחרונה.")
        logger.info("toast מסכם: %d התראות חדשות (מעל הסף %d)", len(rows), MAX_INDIVIDUAL_TOASTS)
        return
    for row in rows:
        alert_id, ticker, name, pct_change = row
        title = f"📉 {name or ticker} ({ticker})"
        message = f"ירידה של {abs(pct_change):.1f}%" if pct_change is not None else "התראת ירידה חדשה"
        notifier.send_desktop_notification(cfg, title, message)
        logger.info("toast: %s - %s", title, message)


def _notify_new_summaries(conn, cfg: dict, state: dict) -> None:
    rows = conn.execute("SELECT kind, sent_date FROM summary_log").fetchall()
    seen = set(state.get("seen_summaries", []))
    fresh = [(k, d) for k, d in rows if f"{k}:{d}" not in seen]
    state["seen_summaries"] = sorted(seen | {f"{k}:{d}" for k, d in fresh})
    if len(fresh) > MAX_INDIVIDUAL_TOASTS:  # הצטברות (ר' _notify_new_alerts) - מדלגים על toast לכל סיכום ישן
        logger.info("%d סיכומים ישנים סומנו כנראו בלי toast (מעל הסף)", len(fresh))
        return
    for kind, sent_date in fresh:
        message_type, title = _SUMMARY_TOAST.get(kind, (None, None))
        if message_type and notifier.is_message_type_enabled(cfg, message_type):
            notifier.send_desktop_notification(cfg, title, "פרטים מלאים בטלגרם.")
            logger.info("toast: %s", title)


if __name__ == "__main__":
    if sys.platform == "win32":
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        cfg = load_config()
        _enabled = bool(cfg.get("desktop_notifications", {}).get("enabled"))
        if not _enabled:
            logger.info("desktop_notifications כבוי בהגדרות - דילוג (המצב מתעדכן בשקט).")

        _sync_alerts_db(db_path(cfg))

        state = _load_state()
        conn = get_conn(db_path(cfg))
        try:
            # רק אחרי שכבר יש last_alert_id אמיתי (לא בהרצה הראשונה) -
            # אחרת ההרצה הראשונה "מתריעה" על כל ההיסטוריה הקיימת בבת אחת.
            first_run = state["last_alert_id"] == 0 and not state.get("seen_summaries")
            if not _enabled:
                # כבוי: מסמנים הכל כ"נראה" בלי toast - אחרת הפעלה מחדש של ההגדרה "מציפה" בכל מה שהצטבר בזמן שהיה כבוי
                state["last_alert_id"] = max(state["last_alert_id"], conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0])
                state["seen_summaries"] = sorted({f"{k}:{d}" for k, d in conn.execute("SELECT kind, sent_date FROM summary_log").fetchall()} | set(state.get("seen_summaries", [])))
            elif first_run:
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
