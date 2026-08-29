"""מוודא שהדשבורד הציבורי ב-Streamlit Cloud ער *וגם* בפועל תקין. אפליקציות
בחינם נרדמות אחרי תקופת חוסר פעילות ומציגות מסך "Zzzz" עם כפתור - ביקור
HTTP רגיל (כמו cron-job.org) רק מקבל את מסך השינה בחזרה ולא מעיר כלום, כי
ההערה דורשת לחיצה אמיתית (JavaScript). מריץ דפדפן אמיתי (Playwright) שמדמה
ביקור אנושי ולוחץ על הכפתור אם צריך. מיועד להרצה כל 20-30 דקות (ר.
.github/workflows/keep_dashboard_awake.yml) - לא תכוף כמו הסורק, כי זה רק
שומר על פעילות, לא בודק נתונים.

חשוב: זה גם מזהה קריסה אמיתית (חריגת פייתון באפליקציה עצמה), לא רק שינה -
מצב כזה לא נפתר ע"י לחיצה על כפתור ההתעוררות בכלל (הוא לא קיים במסך שגיאה),
ובלי הבדיקה הזו היה נשאר שקט לגמרי - הדשבורד המקומי קיבל היום בדיוק את
אותו סוג תיקון (watchdog שחשב שהכל בסדר כשזה לא), אז זו אותה בעיה בשכבה
אחרת. הבדיקה: אחרי ניסיון ההתעוררות (אם היה צריך), מוודאים שתוכן אמיתי של
האפליקציה נטען - אם לא, שולחים התראת טלגרם.
"""
import os
import sys

import requests
import yaml
from playwright.sync_api import sync_playwright

DASHBOARD_URL = "https://stock-drop-scanner-b2rrberutcyv4uaelcdigu.streamlit.app"
WAKE_BUTTON_TEXT = "Yes, get this app back up!"
APP_TITLE_TEXT = "סורק מניות"  # מופיע רק כשהאפליקציה בפועל טעונה ועובדת
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def _is_health_alert_enabled() -> bool:
    """קריאת config.yaml מינימלית, בלי תלות ב-src (הסקריפט הזה עצמאי בכוונה) -
    בודק את אותו מפתח "סוגי התראה" שהדשבורד/notifier.py משתמשים בו, כדי
    שכיבוי "בריאות הדשבורד הציבורי" בסיידבר יכבה גם את ההתראה הזו. נכשל
    לכיוון "מופעל" (לא חוסם) אם config.yaml חסר/לא קריא."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return bool(cfg.get("telegram_message_types", {}).get("health_dashboard", True))
    except Exception:
        return True


def _send_telegram_alert(message: str) -> None:
    if not _is_health_alert_enabled():
        print("סוג ההתראה 'בריאות הדשבורד הציבורי' כבוי בהגדרות - מדלג.")
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("אין פרטי טלגרם זמינים - לא ניתן לשלוח התראה.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"שליחת התראת טלגרם נכשלה: {e}")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(DASHBOARD_URL, timeout=30_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)

            wake_button = page.get_by_text(WAKE_BUTTON_TEXT, exact=False)
            if wake_button.count() > 0:
                print("הדשבורד ישן - לוחץ על כפתור ההתעוררות...")
                wake_button.first.click()
                # ההתעוררות בפועל לוקחת עד כדקה - ממתינים כאן כדי לוודא שהיא
                # באמת קרתה (ולא רק שהלחיצה נרשמה) לפני שממשיכים לבדיקה.
                page.wait_for_timeout(45_000)
            else:
                print("אין מסך שינה - בודק שהאפליקציה בפועל עולה תקין.")

            # התוכן האמיתי של האפליקציה (בניגוד למסך השינה, שמוצג ברמת ה-wrapper
            # החיצוני) חי בתוך iframe נפרד עם title="streamlitApp" - page.get_by_text
            # ברמת ה-page לא חודר לתוכו, וגם frame_locator("iframe") גנרי לא
            # מספיק כי יש בדף עוד iframe (סטטוס Streamlit Cloud) - נבדק בפועל
            # שבלי הבורר המדויק הזה הבדיקה תמיד "לא מוצאת" תוכן גם כשהאפליקציה
            # תקינה לגמרי - false positive מוחלט על קריסה.
            # wait_for (לא count() מיד) - נבדק בפועל שה-iframe לפעמים עוד לא
            # סיים לטעון תוכן תוך 3 שניות גם כשהאפליקציה לגמרי תקינה, מה שגרם
            # ל-false positive על "קריסה" בלי זה. wait_for מנסה שוב עד הזמן
            # המוגדר במקום למדוד פעם אחת ולהתייאש.
            title = page.frame_locator('iframe[title="streamlitApp"]').get_by_text(APP_TITLE_TEXT, exact=False)
            try:
                title.first.wait_for(state="attached", timeout=20_000)
                found = True
            except Exception:
                found = False

            if not found:
                print("האפליקציה לא מציגה תוכן תקין - יכולה להיות קריסה, לא רק שינה.")
                _send_telegram_alert(
                    "🔴 <b>הדשבורד הציבורי לא עולה כמו שצריך</b>\n"
                    "בדיקה אוטומטית לא מצאה תוכן תקין אחרי ניסיון עדכון - "
                    "יכול להיות שהאפליקציה קרסה (לא רק נרדמה, כפתור ההתעוררות לא עוזר במקרה כזה). "
                    "כדאי לבדוק ידנית ב-Streamlit Cloud."
                )
            else:
                print("האפליקציה עולה כרגיל.")
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"שגיאה בבדיקת/העירת הדשבורד: {e}")
        _send_telegram_alert(f"🔴 <b>בדיקת הדשבורד הציבורי נכשלה עם שגיאה טכנית</b>\n{e}")
        sys.exit(1)
