"""טעינת קובץ ההגדרות config.yaml."""
import os
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")
CONFIG_EXAMPLE_PATH = os.path.join(ROOT_DIR, "config.example.yaml")


def load_config(path: str = CONFIG_PATH) -> dict:
    # config.yaml מקומי (עם הטוקן האמיתי) לא קיים בסביבת ענן (GitHub Actions /
    # Streamlit Cloud) - שם config.example.yaml המחובר ל-git משמש בסיס, והסודות
    # (טוקן טלגרם וכו') מוזרקים ממשתני סביבה במקום מהקובץ. מקומית זה לא משתנה.
    load_path = path if os.path.exists(path) else CONFIG_EXAMPLE_PATH
    with open(load_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if bot_token:
        cfg.setdefault("telegram", {})["bot_token"] = bot_token
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if chat_id:
        cfg.setdefault("telegram", {})["chat_id"] = chat_id

    return cfg


def tester_mode() -> bool:
    """מצב בודק (TESTER_MODE=1 ב-Secrets של אפליקציה נפרדת בענן): האתר מתחיל נקי מהנתונים האישיים של הבעלים, הבודק מזין את שלו,
    ושום דבר לא נדחף לגיט. נתוני השוק/הסריקה (ההתראות) נשארים עדכניים."""
    return os.environ.get("TESTER_MODE", "").strip().lower() in ("1", "true", "yes")


def _tester_db(src: str) -> str:
    """עותק פרטי של alerts.db לבודק: אחזקות/עסקאות סגורות/מעקב/התראות מחיר של הבעלים נמחקים, והנתונים של הבודק עצמו נשמרים בו.
    כשהסריקות בענן מעדכנות את alerts.db המקורי - ממזגים אותו מחדש (נתוני סריקה מהמקור, נתוני הבודק מהעותק)."""
    import shutil
    import sqlite3
    from . import db_merge

    dst = os.path.join(ROOT_DIR, "alerts_tester.db")
    marker = dst + ".src"
    try:
        src_m = os.path.getmtime(src)
    except OSError:
        return src
    if not os.path.exists(dst):
        shutil.copyfile(src, dst)
        conn = sqlite3.connect(dst)
        try:
            conn.execute("UPDATE alerts SET bought=0, actual_entry_price=NULL, actual_qty=NULL, bought_at=NULL, holding_stop_price=NULL, "
                         "is_manual_trade=0, last_gain_alert_pct=NULL, stop_alert_active=0")
            for table in db_merge.USER_OWNED_TABLES:
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()
    else:
        try:
            last = float(open(marker).read())
        except Exception:
            last = 0.0
        if src_m > last:
            tmp = dst + ".tmp"
            db_merge.merge(src, dst, tmp)
            os.replace(tmp, dst)
    with open(marker, "w") as f:
        f.write(str(src_m))
    return dst


def db_path(cfg: dict) -> str:
    p = cfg.get("alert_log_db", "alerts.db")
    if not os.path.isabs(p):
        p = os.path.join(ROOT_DIR, p)
    if tester_mode():
        return _tester_db(p)
    return p
