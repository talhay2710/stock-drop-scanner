"""טעינת קובץ ההגדרות config.yaml."""
import os
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def db_path(cfg: dict) -> str:
    p = cfg.get("alert_log_db", "alerts.db")
    if not os.path.isabs(p):
        p = os.path.join(ROOT_DIR, p)
    return p
