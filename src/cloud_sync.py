"""מסנכרן שינויים מקומיים (הגדרות + DB) לענן - commit+push אוטומטי ל-git, כדי
שהאתר הציבורי (Streamlit Cloud) יתעדכן כמעט מיידית בלי פעולה ידנית. נכשל
בשקט (רק מתעד אזהרה) אם אין רשת/git לא זמין - לא אמור להקריס פעולת דשבורד
רגילה כמו שמירת הגדרה או פתיחת פוזיציה."""
import logging
import os
import subprocess

import yaml

from .config import ROOT_DIR, CONFIG_PATH, CONFIG_EXAMPLE_PATH

logger = logging.getLogger(__name__)

_SECRET_KEYS = {"bot_token", "chat_id"}


def _write_example_config_from_local() -> None:
    import os
    if not os.path.exists(CONFIG_PATH):
        return
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    telegram = cfg.get("telegram", {})
    for key in _SECRET_KEYS:
        if key in telegram:
            telegram[key] = ""
    with open(CONFIG_EXAMPLE_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def sync_to_cloud(reason: str = "") -> str:
    """מעדכן config.example.yaml מתוך config.yaml המקומי (בלי סודות), ודוחף
    אותו + alerts.db ל-git אם יש שינוי אמיתי. מחזיר "pushed"/"no_change"/"failed" -
    לא bool, כדי שהקורא יוכל להבדיל "אין מה לסנכרן" מ"ניסה ונכשל" ולהראות
    למשתמש אזהרה במקרה השני (זה בדיוק מה שקרה בשקט יום קודם - כישלון push
    שאף אחד לא ראה עד שהמשתמש שם לב שהענן לא התעדכן).

    למה לא git pull --rebase: alerts.db הוא קובץ בינארי (SQLite) - git לא
    יודע למזג שינויים בינאריים, אז ברגע ששני commits נוגעים בו, rebase נתקע
    ("both modified") והפעולה נכשלת - גילינו בפועל (20.8.2026) שזה קרה שוב
    ושוב בלי שאף אחד שם לב, וגרם לאובדן state (למשל "כבר התרענו על זה") לאורך
    שעות.

    למה reset --soft ולא reset --hard: גילינו בפועל (21.8.2026) ש---hard
    הרס עבודה לא-קשורה שהייתה עדיין בעריכה (קוד שנערך ידנית ב-repo, לא
    committed) - כי --hard מוחק *את כל* השינויים הלא-שמורים ב-working tree,
    לא רק את alerts.db. reset --soft מזיז רק את מצביע ה-HEAD, לא נוגע כלל
    ב-working tree/אינדקס - בטוח לחלוטין מבחינת קבצים אחרים שנמצאים באמצע
    עריכה, וה-commit שלנו (עם alerts.db העדכני שלנו, כבר staged מהניסיון
    הקודם) פשוט נוצר מחדש מעל origin/master הטרי."""
    _git = ["git", "-C", ROOT_DIR]
    try:
        _write_example_config_from_local()
        subprocess.run(_git + ["add", "config.example.yaml", "alerts.db"],
                        check=True, capture_output=True, timeout=15)
        diff = subprocess.run(_git + ["diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if diff.returncode == 0:
            return "no_change"

        msg = f"Sync from local: {reason}" if reason else "Sync from local"
        subprocess.run(_git + ["commit", "-m", msg], check=True, capture_output=True, timeout=15)

        for attempt in range(1, 6):
            push = subprocess.run(_git + ["push", "--quiet"], capture_output=True, timeout=45)
            if push.returncode == 0:
                return "pushed"
            logger.warning("push נדחה (ניסיון %d) - מסתנכרן מחדש עם origin", attempt)
            subprocess.run(_git + ["fetch", "origin"], check=True, capture_output=True, timeout=20)
            subprocess.run(_git + ["reset", "--soft", "origin/master"], check=True, capture_output=True, timeout=15)
            subprocess.run(_git + ["commit", "-m", msg], check=True, capture_output=True, timeout=15)

        logger.warning("סנכרון לענן נכשל (%s): push נדחה 5 פעמים ברציפות", reason)
        return "failed"
    except Exception as e:
        stderr = getattr(e, "stderr", None)
        stderr_text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        logger.warning("סנכרון לענן נכשל (%s): %s | stderr: %s", reason, e, stderr_text)
        return "failed"
