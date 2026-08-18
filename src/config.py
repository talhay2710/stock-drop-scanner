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


def db_path(cfg: dict) -> str:
    p = cfg.get("alert_log_db", "alerts.db")
    if not os.path.isabs(p):
        p = os.path.join(ROOT_DIR, p)
    return p
