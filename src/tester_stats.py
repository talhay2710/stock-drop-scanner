"""מונה כניסות פשוט לאתרי הבודקים (מצב TESTER_MODE בלבד).

סופר *כניסות* (פתיחת האתר בדפדפן, פעם אחת לכל session) - בלי שום פרט אישי: לא כתובת IP, לא שם, לא תוכן.
נשמר בקובץ קטן בתוך המכולה של האפליקציה, ולכן מתאפס כשהמכולה מתאתחלת (אחרי כ-12 שעות ללא שימוש, או פריסה מחדש) -
מראה "כניסות מאז הכניסה הראשונה אחרי ההפעלה". הצפייה: להוסיף ?stats=1 לכתובת האתר. כניסה עם stats=1 לא נספרת."""
import datetime as dt
import json
import os

from .config import ROOT_DIR
from .market_hours import israel_now

_FILE = os.path.join(ROOT_DIR, "tester_visits.json")


def _load() -> dict:
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "total" in data:
            return data
    except Exception:
        pass
    return {"started": israel_now().isoformat(timespec="seconds"), "total": 0, "last": None, "days": {}}


def record_visit() -> None:
    """רושם כניסה אחת. כל כשל נבלע - מונה לא אמור להפיל את האתר."""
    try:
        data = _load()
        now = israel_now()
        data["total"] = int(data.get("total", 0)) + 1
        data["last"] = now.isoformat(timespec="seconds")
        day = now.strftime("%Y-%m-%d")
        data.setdefault("days", {})
        data["days"][day] = int(data["days"].get(day, 0)) + 1
        tmp = _FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _FILE)
    except Exception:
        pass


def summary_text() -> str:
    data = _load()

    def fmt(iso):
        try:
            return dt.datetime.fromisoformat(iso).strftime("%d.%m %H:%M")
        except Exception:
            return "—"

    days = data.get("days", {})
    per_day = " · ".join(f"{d[8:10]}.{d[5:7]}: {n}" for d, n in sorted(days.items())[-7:]) or "—"
    return (
        f"כניסות מאז הכניסה הראשונה ({fmt(data.get('started'))}): {data.get('total', 0)} · "
        f"כניסה אחרונה: {fmt(data.get('last'))} · לפי יום: {per_day}"
    )
