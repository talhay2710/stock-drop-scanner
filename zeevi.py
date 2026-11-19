"""נקודת כניסה לאפליקציית בודק בענן: מפעילה מצב בודק (אתר נקי מהנתונים האישיים של הבעלים) ואז מריצה את האתר הרגיל.
TESTER_USER = מזהה הבודק: הנתונים שלו נשמרים בריפו הפרטי (src/user_sync.py) והוא מקבל התראות טלגרם. דורש USERS_REPO ו-USERS_REPO_TOKEN
ב-Secrets של האפליקציה; בלעדיהם האתר עובד כמו קודם (נתונים זמניים). קובץ נפרד לכל בודק, כי Streamlit לא מאפשר שתי אפליקציות על אותו קובץ."""
import os
import runpy

os.environ["TESTER_MODE"] = "1"
os.environ["TESTER_USER"] = "zeevi"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.py"), run_name="__main__")
