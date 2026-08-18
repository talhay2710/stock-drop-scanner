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


def sync_to_cloud(reason: str = "") -> bool:
    """מעדכן config.example.yaml מתוך config.yaml המקומי (בלי סודות), ודוחף
    אותו + alerts.db ל-git אם יש שינוי אמיתי. מחזיר True אם בפועל נדחף
    commit, False אם אין שינוי או שהסנכרון נכשל."""
    try:
        _write_example_config_from_local()
        _git = ["git", "-C", ROOT_DIR]
        subprocess.run(_git + ["add", "config.example.yaml", "alerts.db"],
                        check=True, capture_output=True, timeout=15)
        diff = subprocess.run(_git + ["diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if diff.returncode == 0:
            return False
        subprocess.run(_git + ["pull", "--rebase", "--quiet"], check=True, capture_output=True, timeout=20)
        msg = f"Sync from local: {reason}" if reason else "Sync from local"
        subprocess.run(_git + ["commit", "-m", msg], check=True, capture_output=True, timeout=15)
        subprocess.run(_git + ["push", "--quiet"], check=True, capture_output=True, timeout=30)
        return True
    except Exception as e:
        logger.warning("סנכרון לענן נכשל (%s): %s", reason, e)
        return False
