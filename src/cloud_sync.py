"""מסנכרן שינויים מקומיים (הגדרות + DB) לענן - commit+push אוטומטי ל-git, כדי
שהאתר הציבורי (Streamlit Cloud) יתעדכן כמעט מיידית בלי פעולה ידנית. נכשל
בשקט (רק מתעד אזהרה) אם אין רשת/git לא זמין - לא אמור להקריס פעולת דשבורד
רגילה כמו שמירת הגדרה או פתיחת פוזיציה."""
import logging
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
    שאף אחד לא ראה עד שהמשתמש שם לב שהענן לא התעדכן)."""
    try:
        _write_example_config_from_local()
        _git = ["git", "-C", ROOT_DIR]
        subprocess.run(_git + ["add", "config.example.yaml", "alerts.db"],
                        check=True, capture_output=True, timeout=15)
        diff = subprocess.run(_git + ["diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if diff.returncode == 0:
            return "no_change"
        # git pull --rebase דורש עץ עבודה נקי - חייב לבצע commit *לפני* ה-pull,
        # לא אחריו (הפוך ממה שהיה כאן וגרם לכשלון "uncommitted changes").
        msg = f"Sync from local: {reason}" if reason else "Sync from local"
        subprocess.run(_git + ["commit", "-m", msg], check=True, capture_output=True, timeout=15)
        # --autostash: אם יש עוד קבצים לא-קשורים ב-working tree שהשתנו (למשל
        # קוד שנערך במקביל), rebase לא נכשל בגללם - הם מוסטשים אוטומטית
        # ומוחזרים אחרי, ולא רק alerts.db/config.example.yaml שכבר ב-commit.
        subprocess.run(_git + ["pull", "--rebase", "--autostash", "--quiet"], check=True, capture_output=True, timeout=20)
        subprocess.run(_git + ["push", "--quiet"], check=True, capture_output=True, timeout=45)
        return "pushed"
    except Exception as e:
        stderr = getattr(e, "stderr", None)
        stderr_text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        logger.warning("סנכרון לענן נכשל (%s): %s | stderr: %s", reason, e, stderr_text)
        return "failed"
