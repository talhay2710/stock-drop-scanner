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


_MAX_PUSH_ATTEMPTS = 10

# בלי creationflags=CREATE_NO_WINDOW, כל קריאה ל-git.exe מהדשבורד המקומי
# (שרץ תחת pythonw.exe - ללא קונסולה משלו, ר' setup_task_scheduler_dashboard_watchdog.ps1)
# פותחת חלון קונסולה נפרד משלה - עד 4 חלונות שחורים על כל שמירת הגדרה אחת.
# לא רלוונטי בענן (Linux) - creationflags הוא פרמטר ספציפי ל-Windows בלבד.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _git_run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, **kwargs, **_NO_WINDOW)


def refresh_alerts_db_if_clean() -> bool:
    """מרענן את alerts.db המקומי מהעותק העדכני בענן - נקרא ממש לפני כל כתיבה
    חדשה לאחזקות (פתיחה/סגירת פוזיציה), כדי לצמצם את החלון שבו הקובץ המקומי
    יכול להיות לא-מסונכרן עם סריקות ענן שקרו במהלך היום (ר' תלונת המשתמש
    1.9.2026: הדשבורד הראה רק 1 מתוך 40 התראות של היום - כי run_dashboard.bat
    מושך מהענן פעם אחת בלבד, בעליית הדשבורד בבוקר, ולא שוב לאורך כל היום).

    רק אם *אין* כרגע שינוי מקומי לא-שמור בקובץ (git diff נקי) - אחרת יש סיכון
    למחוק עבודה שעוד לא הגיעה לענן (למשל sync קודם שנכשל בשקט), אז פשוט
    מדלגים ומשאירים את הקובץ כפי שהוא. מחזיר True אם רוענן בפועל."""
    _git = ["git", "-C", ROOT_DIR]
    try:
        diff = _git_run(_git + ["diff", "--quiet", "--", "alerts.db"], capture_output=True, timeout=15)
        if diff.returncode != 0:
            logger.warning("דילוג על רענון alerts.db - יש שינוי מקומי לא-שמור בקובץ")
            return False
        _git_run(_git + ["fetch", "origin"], check=True, capture_output=True, timeout=20)
        _git_run(_git + ["checkout", "origin/master", "--", "alerts.db"], check=True, capture_output=True, timeout=15)
        return True
    except Exception as e:
        stderr = getattr(e, "stderr", None)
        stderr_text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        logger.warning("רענון alerts.db מהענן נכשל: %s | stderr: %s", e, stderr_text)
        return False


def sync_to_cloud(reason: str = "", include_db: bool = False) -> str:
    """מעדכן config.example.yaml מתוך config.yaml המקומי (בלי סודות), ודוחף
    אותו ל-git אם יש שינוי אמיתי. מחזיר "pushed"/"no_change"/"failed" - לא
    bool, כדי שהקורא יוכל להבדיל "אין מה לסנכרן" מ"ניסה ונכשל".

    include_db=True דוחף גם את alerts.db (רק כשיש שינוי אחזקות אמיתי -
    פתיחה/סגירת פוזיציה - שחייב להגיע לענן). לא בברירת מחדל: גילינו בפועל
    (24.8.2026) שדחיפת alerts.db על כל שמירת הגדרה גרמה להתראות "שקט בסריקה"
    כוזבות - התהליך המקומי אף פעם לא מרענן את alerts.db שעל הדיסק אחרי
    שהדשבורד עלה בבוקר (רק ה-git ref מתעדכן ב-fetch/reset, לא הקובץ עצמו),
    אז דחיפה שלו שעות אחר כך שלחה ל-origin עותק ישן של scan_heartbeat
    (וכנראה גם stop_alert_active/target_alert_active) שדרס את מה שהבוט כתב
    בינתיים - זו אותה משפחת באג שכבר תועדה פעם קודם (20.8.2026, ר' תיעוד).

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
    paths = ["config.example.yaml", "alerts.db"] if include_db else ["config.example.yaml"]
    try:
        _write_example_config_from_local()
        _git_run(_git + ["add"] + paths, check=True, capture_output=True, timeout=15)
        diff = _git_run(_git + ["diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if diff.returncode == 0:
            return "no_change"

        msg = f"Sync from local: {reason}" if reason else "Sync from local"
        # "-- " + paths (לא "git commit -m msg" סתמי): commit בלי pathspec מצרף
        # את *כל* מה שכרגע ב-index, לא רק את מה שהתווסף כאן. גילינו בפועל
        # (26.8.2026) שזה גרם לכך ש-alerts.db "נתפס" בטעות ל-commit הזה (למרות
        # include_db=False) - כנראה נשאר staged משאריות של stash/rebase קודמים -
        # ודחף עותק ישן של alerts.db שדרס state של הבוט (stop_alert_active,
        # התראת-ירידה של היום), וגרם לו "לשכוח" שכבר התריע ולהתריע שוב על אותה
        # ירידה בדיוק (אלביט 4 פעמים, אנלייט פעמיים). ה-"-- " + paths מבטיח
        # שה-commit הזה יכיל את הנתיבים המיועדים בלבד, לא משנה מה עוד staged.
        _git_run(_git + ["commit", "-m", msg, "--"] + paths, check=True, capture_output=True, timeout=15)

        for attempt in range(1, _MAX_PUSH_ATTEMPTS + 1):
            push = _git_run(_git + ["push", "--quiet"], capture_output=True, timeout=45)
            if push.returncode == 0:
                return "pushed"
            logger.warning(
                "push נדחה (ניסיון %d/%d) - מסתנכרן מחדש עם origin: %s",
                attempt, _MAX_PUSH_ATTEMPTS, push.stderr.decode("utf-8", "replace").strip(),
            )
            _git_run(_git + ["fetch", "origin"], check=True, capture_output=True, timeout=20)
            _git_run(_git + ["reset", "--soft", "origin/master"], check=True, capture_output=True, timeout=15)
            _git_run(_git + ["commit", "-m", msg, "--"] + paths, check=True, capture_output=True, timeout=15)

        logger.warning("סנכרון לענן נכשל (%s): push נדחה %d פעמים ברציפות", reason, _MAX_PUSH_ATTEMPTS)
        return "failed"
    except Exception as e:
        stderr = getattr(e, "stderr", None)
        stderr_text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        logger.warning("סנכרון לענן נכשל (%s): %s | stderr: %s", reason, e, stderr_text)
        return "failed"
