"""ממזג שני עותקים מתנגשים של alerts.db אחרי דחיית git push - נקרא גם
מ-resolve_alerts_db_conflict.py (scan.yml, ר' ".github/workflows/scan.yml")
וגם מ-cloud_sync.py (הדשבורד המקומי), משני הכיוונים: מי שכן "מנצח" בהתנגשות
(base) ומי שרק העמודות/טבלאות בבעלות המשתמש שלו נלקחות (user_data) מתחלפים
בין השניים - ר' merge() למטה.

לפני 17.9.2026 הפתרון היה 'הבוט תמיד מנצח' - העתקת קובץ מלאה של הגרסה של
הבוט מעל origin/master הטרי, בלי שום מיזוג. זה עבד טוב כשההתנגשות היחידה
האפשרית הייתה בין שתי ריצות סריקה (concurrency: group מבטיח שהן לא רצות
במקביל, אז בפועל זה כמעט אף פעם לא קרה) - אבל ברגע שההתנגשות היא מול פעולת
משתמש אמיתית בדשבורד (קנייה/מכירה/התראת מחיר/רשימת מעקב), 'תמיד מנצחים' פירושו
שהבוט דורס בשקט נתונים אמיתיים של המשתמש. זה בדיוק מה שקרה: סגירת פוזיציית
נייס ב-17.9.2026 11:50 נדרסה 20 שניות אחר כך ע"י ריצת סריקה שכבר הייתה
"באמצע" עם עותק ישן - ואז כל ריצה נוספת (14 בסה"כ) המשיכה לגרור את הגרסה
הישנה, כי היא נעשתה הבסיס (HEAD) לכל commit הבא.

הפתרון: לא קובץ שלם, אלא מיזוג ברמת עמודה/טבלה - עמודות/טבלאות בבעלות
בלעדית של הדשבורד (קנייה/מכירה/התראות מחיר/רשימת מעקב - ר' USER_OWNED_ALERT_COLS
ו-USER_OWNED_TABLES למטה) תמיד נלקחות מהצד שמסומן כ-user_data, לא משנה מה
ה-base "חושב" שהן צריכות להיות. כל השאר (נתוני הסריקה עצמה - ציונים, התראות
טלגרם שכבר נשלחו, דגלי דה-דופ) נשאר כפי שה-base קובע - זה תמיד "מנצח" שם,
כי רק הבוט כותב לשם בכלל.
"""
import shutil
import sqlite3

# עמודות ב-alerts שרק הדשבורד (פעולת משתמש אינטראקטיבית) כותב אליהן - אף פעם
# לא נכתבות ע"י scan.yml/run_scan_once.py/run_daily_summary.py/run_weekly_report.py.
# ר' src/store.py: mark_as_bought, unmark_as_bought, update_holding_stop_price.
USER_OWNED_ALERT_COLS = [
    "bought", "actual_entry_price", "actual_qty", "bought_at",
    "holding_stop_price", "is_manual_trade",
]

# טבלאות שרק הדשבורד כותב אליהן בכלל - ר' src/store.py: save_closed_trade,
# add_price_alert/deactivate_price_alert, add_watchlist_item/remove_watchlist_item.
USER_OWNED_TABLES = ["closed_trades", "price_alerts", "watchlist"]


def merge(base_path: str, user_data_path: str, out_path: str) -> None:
    """base_path - הצד ש'מנצח' לכל מה שהוא לא בעלות-משתמש (למשל: הבוט מול
    ריצת סריקה אחרת, או origin הטרי מול הדשבורד המקומי). user_data_path -
    הצד שרק העמודות/טבלאות בבעלות המשתמש שלו נלקחות ממנו ומוחלות מעל base."""
    shutil.copy(base_path, out_path)
    out = sqlite3.connect(out_path)
    user_data = sqlite3.connect(user_data_path)
    user_data.row_factory = sqlite3.Row

    set_clause = ", ".join(f"{c} = ?" for c in USER_OWNED_ALERT_COLS)
    for row in user_data.execute(f"SELECT id, {', '.join(USER_OWNED_ALERT_COLS)} FROM alerts"):
        row = dict(row)
        alert_id = row.pop("id")
        out.execute(
            f"UPDATE alerts SET {set_clause} WHERE id = ?",
            [row[c] for c in USER_OWNED_ALERT_COLS] + [alert_id],
        )

    for table in USER_OWNED_TABLES:
        out.execute(f"DELETE FROM {table}")
        cols = [r[1] for r in user_data.execute(f"PRAGMA table_info({table})")]
        col_list = ", ".join(cols)
        placeholders = ", ".join("?" for _ in cols)
        for row in user_data.execute(f"SELECT {col_list} FROM {table}"):
            out.execute(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", row)

    out.commit()
    out.close()
    user_data.close()
