"""נקודת כניסה לאפליקציית בודק בענן: מפעילה מצב בודק (אתר נקי מהנתונים האישיים של הבעלים) ואז מריצה את האתר הרגיל.
אין צורך להגדיר Secret - המצב נקבע כאן. קובץ נפרד לכל בודק, כי Streamlit לא מאפשר שתי אפליקציות על אותו קובץ."""
import os
import runpy

os.environ["TESTER_MODE"] = "1"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.py"), run_name="__main__")
