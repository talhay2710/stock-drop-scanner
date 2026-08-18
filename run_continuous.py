"""מריץ את הסורק בלולאה רציפה, כל scan_interval_minutes דקות. כל מדד ב-cfg['indices']
נבדק בנפרד מול שעות המסחר שלו (run_scan מדלג באופן פנימי על מדדים שהשוק שלהם סגור).
יש להשאיר את החלון הזה פתוח/רץ ברקע (למשל עם pythonw, או בטרמינל).
לחלופין ניתן להשתמש ב-run_scan_once.py + Windows Task Scheduler במקום קובץ זה.
"""
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config
from src.scanner import run_scan, run_startup_health_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_continuous")


def main():
    cfg = load_config()
    interval = cfg.get("scan_interval_minutes", 5) * 60
    indices = cfg.get("indices") or ([cfg["index"]] if "index" in cfg else [])
    logger.info("מתחיל סריקה רציפה עבור מדדים %s, כל %d דקות (בשעות מסחר בלבד)", indices, interval / 60)
    run_startup_health_check(cfg)

    while True:
        try:
            results = run_scan(cfg)
            logger.info("נשלחו %d התראות בסבב זה", len(results))
        except Exception:
            logger.exception("שגיאה בסבב הסריקה")
        time.sleep(interval)


if __name__ == "__main__":
    main()
