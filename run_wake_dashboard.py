"""מוודא שהדשבורד הציבורי ב-Streamlit Cloud ער. אפליקציות בחינם נרדמות אחרי
תקופת חוסר פעילות ומציגות מסך "Zzzz" עם כפתור - ביקור HTTP רגיל (כמו
cron-job.org) רק מקבל את מסך השינה בחזרה ולא מעיר כלום, כי ההערה דורשת
לחיצה אמיתית (JavaScript). מריץ דפדפן אמיתי (Playwright) שמדמה ביקור אנושי
ולוחץ על הכפתור אם צריך. מיועד להרצה כל 20-30 דקות (ר' .github/workflows/keep_dashboard_awake.yml) -
לא תכוף כמו הסורק, כי זה רק שומר על פעילות, לא בודק נתונים.
"""
import sys

from playwright.sync_api import sync_playwright

DASHBOARD_URL = "https://stock-drop-scanner-b2rrberutcyv4uaelcdigu.streamlit.app"
WAKE_BUTTON_TEXT = "Yes, get this app back up!"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(DASHBOARD_URL, timeout=30_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)

            wake_button = page.get_by_text(WAKE_BUTTON_TEXT, exact=False)
            if wake_button.count() == 0:
                print("הדשבורד כבר ער - אין צורך בפעולה.")
                return

            print("הדשבורד ישן - לוחץ על כפתור ההתעוררות...")
            wake_button.first.click()
            # ההתעוררות בפועל לוקחת עד כדקה - ממתינים כאן כדי לוודא שהיא
            # באמת קרתה (ולא רק שהלחיצה נרשמה) לפני שהריצה מסתיימת.
            page.wait_for_timeout(45_000)
            print("בקשת ההתעוררות נשלחה.")
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"שגיאה בבדיקת/העירת הדשבורד: {e}")
        sys.exit(1)
