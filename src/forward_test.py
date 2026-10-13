"""מעקב קדימה (forward test) של ניקוד האסטרטגיה - משותף לדוח האימות השבועי (validate_strategy.py) ולכרטיס בדף הבית.

הניקוד והמשקלים הוקפאו ב-FREEZE_DATE: כל התראה מאותו תאריך ואילך היא מדגם בדיקה חדש לגמרי (שום משקל לא נקבע לפיו).
כאן רק קוראים את התוצאות - אין החלטות. ר' validate_strategy.py להסבר המלא של השיטה (טווחי סמך לפי ימים שלמים, נטו אחרי עמלות).
"""
import datetime as dt

import numpy as np
import pandas as pd

from . import post_alert, store, strategy as st, strategy_stats as ss
from .market_hours import is_trading_day, israel_today

FREEZE_DATE = "2026-10-08"
MIN_BLIND_DAYS = 40      # פחות מזה - רק מתארים, לא מחליטים
MIN_RESOLVED_SHOWN = 5   # פחות מזה - הכרטיס לא מציג אחוזים (רעש)


def position_size(cfg: dict) -> float:
    return float(cfg.get("position_size", {}).get("ILS", 5000.0))


def load_scored_alerts(conn) -> pd.DataFrame:
    """כל ההתראות הישראליות הלא-ידניות עם עמודת score - גם כאלה שעדיין אין להן תוצאות מדודות."""
    alerts = pd.read_sql_query(
        "SELECT * FROM alerts WHERE index_name IN ('TA35','TA125')" + store.exclusion_clause(), conn)
    alerts = alerts[alerts["is_manual_trade"].fillna(0) == 0].copy()
    hours = alerts["scan_ts"].astype(str).str[11:13].apply(lambda x: int(x) if x.isdigit() else None)
    alerts["score"] = [
        st.signal_score(r["index_name"], r["pct_change"], r["intraday_recovery_pct"], r["dist_from_ma50_pct"],
                        r["sector"], h)[0]
        for (_, r), h in zip(alerts.iterrows(), hours)
    ]
    return alerts


def load_merged(conn) -> pd.DataFrame:
    """התראות + תוצאות מאז ההתראה (5 דקות) - רק התראות שכבר יש להן שורת תוצאות (גם אם עדיין פתוחות)."""
    post_alert.ensure_table(conn)
    return load_scored_alerts(conn).merge(
        post_alert.load_outcomes(conn), left_on="id", right_on="alert_id", how="inner")


def load_evaluated(conn, target: float | None = None) -> pd.DataFrame:
    """התראות שנסגרו (הגיעו ליעד / סטופ / פג זמן) עם y (1=הגיע ליעד), ret (תשואה ברוטו %) ו-score."""
    merged = load_merged(conn)
    ev = post_alert.evaluate(merged, st.TARGET_PCT if target is None else target, st.HOLD_MAX_DAYS)
    ev = ev[ev["outcome"] != "pending"].copy()
    ev["y"] = (ev["outcome"] == "hit_target").astype(int)
    return ev


def trading_days_since(freeze_date: str = FREEZE_DATE, today: dt.date | None = None) -> int:
    today = today or israel_today()
    day, n = dt.date.fromisoformat(freeze_date), 0
    while day <= today:
        if is_trading_day("IL", day):
            n += 1
        day += dt.timedelta(days=1)
    return n


def summary(conn, cfg: dict, freeze_date: str = FREEZE_DATE, boot: int = 400) -> dict:
    """תקציר המדגם העיוור לקבוצת 🟢 (ציון 4+): כמה התראות, כמה נסגרו, הצלחה, ברוטו ונטו (+טווח סמך לנטו כשיש מספיק)."""
    scored = load_scored_alerts(conn)
    ev = load_evaluated(conn)
    pos = position_size(cfg)

    buy_all = scored[(scored["scan_date"] >= freeze_date) & (scored["score"] >= 4)]
    buy = ev[(ev["scan_date"] >= freeze_date) & (ev["score"] >= 4)]
    out = {
        "freeze_date": freeze_date, "position": pos,
        "days_elapsed": trading_days_since(freeze_date), "days_needed": MIN_BLIND_DAYS,
        "alerts": int(len(buy_all)), "resolved": int(len(buy)), "pending": int(len(buy_all) - len(buy)),
        "hits": int(buy["y"].sum()) if len(buy) else 0,
    }
    if len(buy) >= MIN_RESOLVED_SHOWN:
        net = buy["ret"].map(lambda r: ss.net_return_pct(r, pos, cfg["fees"]))
        out["hit_rate"] = float(buy["y"].mean() * 100)
        out["gross"] = float(buy["ret"].mean())
        out["net"] = float(net.mean())
        if buy["scan_date"].nunique() >= 5:
            lo, hi = ss.day_bootstrap_ci(buy.assign(_n=net), lambda g: g["_n"].mean(), B=boot)
            out["net_ci"] = (lo, hi)
    return out
