"""מריץ סבב סריקה בודד ויוצא. מיועד להרצה דרך Windows Task Scheduler
(ראה setup_task_scheduler.ps1) בשעות המסחר, כל כמה דקות.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config
from src.scanner import run_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    cfg = load_config()
    results = run_scan(cfg)
    if results:
        print(f"נשלחו {len(results)} התראות:")
        for r in results:
            print(f"  {r['ticker']}: {r['pct_change']:.1f}% - {r['overreaction_verdict']}")
    else:
        print("לא נמצאו מניות שחצו את הסף בסבב זה.")
