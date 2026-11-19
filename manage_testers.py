"""ניהול בודקים (לבעלים, מהמחשב שלו): הוספת בודק לריפו הפרטי, רשימה, וקישור הטלגרם שלו.
דורש משתני סביבה USERS_REPO (owner/name של הריפו הפרטי) ו-USERS_REPO_TOKEN (טוקן עם Contents read/write לריפו הזה בלבד).

  python manage_testers.py add michal "מיכל"   # יוצר משתמש; מדפיס קוד גישה (פעם אחת - נשמר רק גיבוב) וקישור טלגרם
  python manage_testers.py list                # משתמשים וסטטוס חיבור טלגרם
  python manage_testers.py link michal         # מדפיס שוב את קישור הטלגרם (BOT_USERNAME מ-config.yaml/סביבה)
"""
import os
import sys

from src import user_sync


def _bot_username() -> str:
    name = os.environ.get("BOT_USERNAME", "")
    if name:
        return name.lstrip("@")
    try:
        import requests
        import yaml
        cfg = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"), encoding="utf-8"))
        r = requests.get(f"https://api.telegram.org/bot{cfg['telegram']['bot_token']}/getMe", timeout=15)
        return r.json()["result"]["username"]
    except Exception:
        return "<BOT_USERNAME>"


def _link(token: str) -> str:
    users, _ = user_sync.read_json("users.json", {})
    return f"https://t.me/{users.get('bot_username') or _bot_username()}?start={token}"


def cmd_add(user_id: str, name: str) -> None:
    user_id = user_id.strip().lower()
    users, sha = user_sync.read_json("users.json", {"users": {}})
    if user_id in users["users"]:
        sys.exit(f"המשתמש {user_id} כבר קיים")
    rec, code = user_sync.new_user_record(name)
    users["users"][user_id] = rec
    bot = _bot_username()
    if not bot.startswith("<"):
        users["bot_username"] = bot  # האתרים של הבודקים מציגים ממנו את קישור החיבור (אין להם גישה לטוקן הבוט)
    user_sync.write_json("users.json", users, sha, f"add tester {user_id}")
    print(f"נוצר: {user_id} ({name})\nקוד גישה (מוצג פעם אחת): {code}\nקישור טלגרם: {_link(rec['link_token'])}")


def cmd_list() -> None:
    users, _ = user_sync.read_json("users.json", {"users": {}})
    links, _ = user_sync.read_json("telegram_links.json", {"chats": {}})
    for uid, u in sorted(users["users"].items()):
        print(f"{uid}\t{u.get('name', '')}\ttelegram={'מחובר' if uid in links.get('chats', {}) else 'לא מחובר'}")


def cmd_link(user_id: str) -> None:
    rec = user_sync.get_user(user_id.strip().lower())
    if not rec:
        sys.exit("משתמש לא קיים")
    print(_link(rec["link_token"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not user_sync.configured():
        sys.exit("חסרים USERS_REPO / USERS_REPO_TOKEN")
    if a[:1] == ["add"] and len(a) >= 2:
        cmd_add(a[1], a[2] if len(a) > 2 else a[1])
    elif a[:1] == ["list"]:
        cmd_list()
    elif a[:1] == ["link"] and len(a) == 2:
        cmd_link(a[1])
    else:
        sys.exit(__doc__)
