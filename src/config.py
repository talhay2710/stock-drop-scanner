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

    from . import store  # פריסת הנתונים (legacy/split) נקבעת פעם אחת לכל תהליך, מההגדרות (או DB_LAYOUT)
    store.configure_layout(cfg)
    return cfg


def tester_mode() -> bool:
    """מצב בודק (TESTER_MODE=1 ב-Secrets של אפליקציה נפרדת בענן): האתר מתחיל נקי מהנתונים האישיים של הבעלים, הבודק מזין את שלו,
    ושום דבר לא נדחף לגיט. נתוני השוק/הסריקה (ההתראות) נשארים עדכניים."""
    return os.environ.get("TESTER_MODE", "").strip().lower() in ("1", "true", "yes")


_TESTER_CLEAR_BOUGHT_SQL = ("UPDATE alerts SET bought=0, actual_entry_price=NULL, actual_qty=NULL, bought_at=NULL, holding_stop_price=NULL, "
                            "is_manual_trade=0, last_gain_alert_pct=NULL, stop_alert_active=0")
_tester_verified_src_mtime: float | None = None  # פעם אחת לכל גרסת מקור בתהליך: בדיקת זיהום (ר' _tester_contaminated)


def _tester_contaminated(src: str, dst: str) -> bool:
    """האם העותק של הבודק מכיל נתונים אישיים של הבעלים (עסקה סגורה/אחזקה זהות למקור). קורה אם יצירת העותק נקטעה אחרי ההעתקה
    ולפני הניקוי - אז העותק נשאר "גולמי" ולא נוקה לעולם (נמצא בפועל ב-17.11.2026 באתר של זאבי). נתוני בודק אמיתיים לעולם לא יזהו למקור.
    כל שגיאה בבדיקה = נחשב מזוהם (בצד הבטוח לפרטיות: בונים מחדש)."""
    import sqlite3
    conn = sqlite3.connect(dst)
    try:
        conn.execute("ATTACH DATABASE ? AS src", (src,))
        n = conn.execute("SELECT COUNT(*) FROM closed_trades c JOIN src.closed_trades s "
                         "ON c.ticker=s.ticker AND c.entry_at=s.entry_at AND c.exit_at=s.exit_at").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM alerts a JOIN src.alerts s ON a.id=s.id "
                         "WHERE a.bought=1 AND s.bought=1 AND a.bought_at=s.bought_at").fetchone()[0]
        return (n + m) > 0
    except Exception:
        return True
    finally:
        conn.close()


def _tester_build(src: str, dst: str) -> None:
    """בונה עותק נקי אטומית: מעתיקים ומנקים בקובץ זמני, ורק אז מחליפים - כך אף פעם לא נשאר עותק חצי-מנוקה."""
    import shutil
    import sqlite3
    from . import db_merge

    tmp = dst + ".new"
    shutil.copyfile(src, tmp)
    conn = sqlite3.connect(tmp)
    try:
        conn.execute(_TESTER_CLEAR_BOUGHT_SQL)
        for table in db_merge.USER_OWNED_TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, dst)


def _tester_db(src: str) -> str:
    """עותק פרטי של alerts.db לבודק: אחזקות/עסקאות סגורות/מעקב/התראות מחיר של הבעלים נמחקים, והנתונים של הבודק עצמו נשמרים בו.
    כשהסריקות בענן מעדכנות את alerts.db המקורי - ממזגים אותו מחדש (נתוני סריקה מהמקור, נתוני הבודק מהעותק)."""
    global _tester_verified_src_mtime
    import sqlite3
    from . import db_merge

    dst = os.path.join(ROOT_DIR, "alerts_tester.db")
    marker = dst + ".src"
    try:
        src_m = os.path.getmtime(src)
    except OSError:
        return src
    if _tester_verified_src_mtime == src_m and os.path.exists(dst):
        return dst
    if not os.path.exists(dst) or _tester_contaminated(src, dst):
        _tester_build(src, dst)
    else:
        try:
            with open(marker) as _mf:
                last = float(_mf.read())
        except Exception:
            last = 0.0
        if src_m > last:
            tmp = dst + ".tmp"
            db_merge.merge(src, dst, tmp)
            # התראות חדשות שנוספו במקור אחרי יצירת העותק: merge משאיר להן את סימוני הקנייה של הבעלים - מנקים
            conn = sqlite3.connect(tmp)
            try:
                conn.execute("ATTACH DATABASE ? AS t", (dst,))
                conn.execute(_TESTER_CLEAR_BOUGHT_SQL + " WHERE id NOT IN (SELECT id FROM t.alerts)")
                conn.commit()
            finally:
                conn.close()
            os.replace(tmp, dst)
    with open(marker, "w") as f:
        f.write(str(src_m))
    _tester_verified_src_mtime = src_m
    return dst


def db_path(cfg: dict) -> str:
    p = cfg.get("alert_log_db", "alerts.db")
    if not os.path.isabs(p):
        p = os.path.join(ROOT_DIR, p)
    if tester_mode():
        return _tester_db(p)
    return p
