"""שליחת התראות: טלגרם + התראת דסקטופ (Windows toast)."""
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_SEND_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_EDIT_API = "https://api.telegram.org/bot{token}/editMessageText"


def _telegram_creds(cfg: dict) -> tuple[str, str] | None:
    tg = cfg.get("telegram", {})
    if not tg.get("enabled"):
        return None
    token = tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "")
    if not token or "REPLACE_ME" in token or not chat_id or "REPLACE_ME" in str(chat_id):
        logger.warning("טלגרם מוגדר כפעיל אך bot_token/chat_id לא הוגדרו ב-config.yaml - דילוג")
        return None
    return token, chat_id


# כל סוג הודעה שהמערכת שולחת - מוצג בסיידבר ("סוגי התראה") עם צ'קבוקס לכל
# אחד, כדי שאפשר יהיה לכבות סוגים ספציפיים בלי לכבות טלגרם כולו. ברירת מחדל
# (מפתח חסר ב-config.yaml) היא תמיד "מופעל" - תאימות לאחור, לא דורש שינוי
# ידני בקובץ קיים.
MESSAGE_TYPES = {
    "drop_alert": "ירידה חדה / מצטברת",
    "holdings_stop": "קרוב/חצה סטופ-לוס",
    "holdings_target": "קרוב/הגיע ליעד",
    "holdings_gain": "עלייה מהכניסה",
    "price_alert": "התראת מחיר ידנית",
    "reversal_alert": "סימני התאוששות",
    "morning_summary": "תמונת מצב - תחילת יום",
    "daily_summary": "סיכום יומי",
    "weekly_report": "דוח שבועי",
    "health_startup": "בדיקת בריאות בהפעלה",
    "health_heartbeat": "פער בסריקה האוטומטית",
    "health_dashboard": "בריאות הדשבורד הציבורי",
}


def is_message_type_enabled(cfg: dict, message_type: str) -> bool:
    return bool(cfg.get("telegram_message_types", {}).get(message_type, True))


def send_telegram_typed(cfg: dict, message_type: str, text: str) -> int | None:
    """כמו send_telegram, אבל בודק קודם שהסוג הזה לא כובה ב"סוגי התראה"
    בסיידבר - נקודת מעבר יחידה לכל שולחי ההודעות, כדי שכיבוי סוג לא ידרוש
    לגעת בכל מקום שבו הוא נשלח בפועל."""
    if not is_message_type_enabled(cfg, message_type):
        logger.info("דילוג על שליחת טלגרם - סוג '%s' כבוי בהגדרות", message_type)
        return None
    return send_telegram(cfg, text)


def send_telegram(cfg: dict, text: str) -> int | None:
    """שולח הודעת טלגרם חדשה, מחזיר את message_id שלה (לשימוש אפשרי בעריכה
    מאוחרת יותר, ראה edit_telegram) - או None אם השליחה נכשלה/מבוטלת."""
    creds = _telegram_creds(cfg)
    if not creds:
        return None
    token, chat_id = creds
    try:
        resp = requests.post(
            TELEGRAM_SEND_API.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("שליחת טלגרם נכשלה (%s): %s", resp.status_code, resp.text)
            return None
        return resp.json().get("result", {}).get("message_id")
    except Exception as e:
        logger.error("שגיאה בשליחת טלגרם: %s", e)
        return None


def edit_telegram(cfg: dict, message_id: int, text: str) -> bool:
    """עורך הודעת טלגרם קיימת (למשל כשמניה שכבר קיבלה התראה היום ממשיכה לרדת) -
    כדי לא להציף את הצ'אט בהודעות כפולות לאותה מניה. מחזיר True אם הצליח."""
    creds = _telegram_creds(cfg)
    if not creds:
        return False
    token, chat_id = creds
    try:
        resp = requests.post(
            TELEGRAM_EDIT_API.format(token=token),
            json={"chat_id": chat_id, "message_id": message_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("עריכת הודעת טלגרם נכשלה (%s): %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        logger.error("שגיאה בעריכת הודעת טלגרם: %s", e)
        return False


def send_desktop_notification(cfg: dict, title: str, message: str) -> None:
    dn = cfg.get("desktop_notifications", {})
    if not dn.get("enabled"):
        return
    try:
        from winotify import Notification
        toast = Notification(
            app_id="Stock Drop Scanner",
            title=title,
            msg=message,
            duration="long",
        )
        toast.show()
    except Exception as e:
        logger.error("שגיאה בשליחת התראת דסקטופ: %s", e)
