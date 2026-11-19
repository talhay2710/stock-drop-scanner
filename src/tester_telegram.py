"""התראות טלגרם לבודקים: חיבור (קישור אישי לבוט) ושליחת התראות קנייה חדשות מהסורק. אותו בוט של הבעלים, צ'אט נפרד לכל בודק.

חיבור: הבודק פותח את הקישור t.me/<בוט>?start=<link_token> (מוצג באתר שלו) ולוחץ Start; הסורק קורא את העדכונים (getUpdates) בכל ריצה,
מתאים את ה-token למשתמש ושומר את ה-chat_id ב-telegram_links.json בריפו הפרטי (הסורק הוא הכותב היחיד שלו). /stop מנתק.
כל פונקציה כאן לא זורקת: כשל בבודקים לעולם לא מפיל סריקה או משבש את ההתראות של הבעלים. לוגים בלי כתובות (הטוקן חלק מהכתובת)."""
import json
import logging
import os
import time

import requests

from . import user_sync

logger = logging.getLogger(__name__)

LINKS_PATH = "telegram_links.json"
_API = "https://api.telegram.org/bot{token}/{method}"
_RECIPIENTS_TTL = 60
_cache: dict = {"at": 0.0, "chats": {}}


def _token(cfg: dict) -> str | None:
    """טוקן הבוט לשליחה לבודקים. בלתי תלוי במתג "טלגרם" שלך (כיבוי טלגרם אצלך לא עוצר בודקים), ורק בסורק בענן (GitHub Actions):
    כך סריקה ידנית/מקומית מהמחשב שלך לא שולחת לבודקים עותק שני של מה שהסורק בענן כבר שולח."""
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("TESTER_BROADCAST") != "1":
        return None
    token = cfg.get("telegram", {}).get("bot_token", "")
    if not token or "REPLACE_ME" in token:
        return None
    return token


def _call(token: str, method: str, **payload):
    r = requests.post(_API.format(token=token, method=method), json=payload, timeout=15)
    return r


def _reply(token: str, chat_id, text: str) -> None:
    try:
        _call(token, "sendMessage", chat_id=chat_id, text=text)
    except Exception as e:
        logger.warning("תשובת טלגרם לבודק נכשלה (%s)", type(e).__name__)


def poll_links(cfg: dict) -> int:
    """קורא הודעות /start <token> ו-/stop שהבודקים שלחו לבוט ומעדכן את חיבורי הטלגרם. מחזיר כמה חיבורים התעדכנו."""
    token = _token(cfg)
    if not token or not user_sync.configured():
        return 0
    try:
        links, sha = user_sync.read_json(LINKS_PATH, {"last_update_id": 0, "chats": {}})
        users, _ = user_sync.read_json("users.json", {"users": {}})
        by_token = {u["link_token"]: uid for uid, u in users.get("users", {}).items() if u.get("link_token")}
        last = int(links.get("last_update_id", 0))
        resp = requests.get(_API.format(token=token, method="getUpdates"),
                            params={"offset": last + 1, "timeout": 0, "allowed_updates": json.dumps(["message"])}, timeout=15)
        if resp.status_code != 200:
            logger.warning("getUpdates נכשל (%s)", resp.status_code)  # 409 = מוגדר webhook
            return 0
        updates = resp.json().get("result", [])
        if not updates:
            return 0
        chats = dict(links.get("chats", {}))
        changed = 0
        for upd in updates:
            last = max(last, int(upd["update_id"]))
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat_id = (msg.get("chat") or {}).get("id")
            if chat_id is None:
                continue
            if text.startswith("/start "):
                uid = by_token.get(text.split(None, 1)[1].strip())
                if uid:
                    chats[uid] = chat_id
                    changed += 1
                    _reply(token, chat_id, f"✅ מחובר. תקבל כאן התראות קנייה חדשות מ-DipRadar ({users['users'][uid].get('name', uid)}). לניתוק: /stop")
            elif text == "/stop":
                gone = [uid for uid, c in chats.items() if c == chat_id]
                for uid in gone:
                    del chats[uid]
                    changed += 1
                if gone:
                    _reply(token, chat_id, "ההתראות נותקו. לחיבור מחדש - הקישור באתר.")
        # last_update_id נשמר גם כשלא היה שינוי, כדי לא לקרוא שוב את אותם עדכונים
        user_sync.write_json(LINKS_PATH, {"last_update_id": last, "chats": chats}, sha, "telegram links")
        _cache["at"] = 0.0
        return changed
    except Exception as e:
        logger.warning("עדכון חיבורי טלגרם של בודקים נכשל (%s)", type(e).__name__)
        return 0


def recipients() -> dict:
    """{user_id: {"chat_id": ..., "prefs": {...}}} של בודקים מחוברים (מטמון קצר - לא קוראים מהריפו לכל התראה)."""
    if not user_sync.configured():
        return {}
    if time.time() - _cache["at"] < _RECIPIENTS_TTL:
        return _cache["chats"]
    try:
        links, _ = user_sync.read_json(LINKS_PATH, {"chats": {}})
        chats = {}
        for uid, chat_id in links.get("chats", {}).items():
            try:
                prefs = user_sync.read_prefs(uid)
            except Exception:
                prefs = user_sync.clean_prefs({})  # כשל בקריאת העדפות = ברירת מחדל, לא מפסיקים לשלוח
            chats[uid] = {"chat_id": chat_id, "prefs": prefs}
        _cache.update(at=time.time(), chats=chats)
    except Exception as e:
        logger.warning("קריאת נמעני טלגרם של בודקים נכשלה (%s)", type(e).__name__)
        _cache.update(at=time.time() - _RECIPIENTS_TTL + 10, chats={})  # ננסה שוב בעוד ~10 שניות, לא בכל התראה
    return _cache["chats"]


def wants(prefs: dict, kind: str = "drop", index=None, signal=None, drop_pct=None,
          multi_day_only: bool = False, n_day_pct=None) -> bool:
    """האם בודק עם ההעדפות האלה מקבל את ההתראה הזו. kind: 'drop' (התראת ירידה חדשה) או 'reversal' (סימני התאוששות)."""
    if not prefs.get("enabled", True):  # המתג "טלגרם" של הבודק עצמו
        return False
    if index is not None and index not in prefs["indices"]:
        return False
    if kind == "reversal":
        return bool(prefs["reversal"])
    if not prefs.get("drop_alert", True):
        return False
    if signal is not None and signal not in prefs["signals"]:
        return False
    if multi_day_only:
        return bool(prefs["multi_day"]) and abs(n_day_pct or 0) >= prefs["min_multi_pct"]
    return abs(drop_pct or 0) >= prefs["min_drop_pct"]


def send_to(cfg: dict, chat_id, text: str) -> bool:
    """שליחה לצ'אט אחד (HTML). True רק אם טלגרם אישר - הקורא מעדכן מצב התראה רק אז, כדי שכשל יתנסה שוב בסבב הבא."""
    token = _token(cfg)
    if not token:
        return False
    try:
        return _call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True).status_code == 200
    except Exception as e:
        logger.warning("שליחה לבודק נכשלה (%s)", type(e).__name__)
        return False


def broadcast(cfg: dict, text: str, **alert) -> int:
    """שולח הודעת HTML לבודקים המחוברים שההעדפות שלהם מתאימות להתראה (alert = הפרמטרים של wants). מחזיר כמה נשלחו.
    כשל אחד לא עוצר את האחרים."""
    token = _token(cfg)
    if not token:
        return 0
    sent = 0
    for uid, rec in dict(recipients()).items():
        if alert and not wants(rec["prefs"], **alert):
            continue
        try:
            r = _call(token, "sendMessage", chat_id=rec["chat_id"], text=text, parse_mode="HTML", disable_web_page_preview=True)
            if r.status_code == 200:
                sent += 1
            else:
                logger.warning("שליחה לבודק %s נכשלה (%s)", uid, r.status_code)
        except Exception as e:
            logger.warning("שליחה לבודק %s נכשלה (%s)", uid, type(e).__name__)
    return sent
