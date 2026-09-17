"""עטיפת CLI דקה סביב src.db_merge.merge - נקראת מ-scan.yml (ר'
".github/workflows/scan.yml") אחרי דחיית push, כשצריך למזג את גרסת הבוט
מול origin הטרי. לוגיקת המיזוג עצמה גרה ב-src/db_merge.py (גם cloud_sync.py
של הדשבורד המקומי מייבא אותה משם, בכיוון ההפוך).

שימוש: python resolve_alerts_db_conflict.py <base> <user_data> <out>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.db_merge import merge

if __name__ == "__main__":
    base, user_data, out = sys.argv[1], sys.argv[2], sys.argv[3]
    merge(base, user_data, out)
    print(f"מוזג: {base} (בסיס) + {user_data} (בעלות משתמש) -> {out}")
