"""סיכומי טלגרם לבודקים (בוקר / יומי / שבועי) - צעד נפרד ב-scan.yml, אחרי הסיכומים של הבעלים. ר' src/tester_summaries.py.
לעולם לא נכשל: כשל כאן לא אמור להפיל את ריצת הסריקה."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config, db_path
from src.store import get_conn
from src import tester_summaries

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

if __name__ == "__main__":
    try:
        cfg = load_config()
        conn = get_conn(db_path(cfg))
        try:
            print(f"סיכומי בודקים: נשלחו {tester_summaries.run(cfg, conn)}")
        finally:
            conn.close()
    except Exception as e:
        print(f"סיכומי בודקים נכשלו ({type(e).__name__})")
