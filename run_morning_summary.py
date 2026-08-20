"""שולח הודעת טלגרם אחת בתחילת יום המסחר (כ-10 דקות אחרי פתיחת ת"א): תמונת מצב
מיידית - האחזקות שלך והמניות הכי בולטות (עולות/יורדות) בכל מדד שנסרק. בניגוד
לסיכום היומי (run_daily_summary.py, שמבוסס על התראות שנשלחו באותו יום) זה
snapshot חי של המחירים ברגע השליחה. מיועד להרצה פעם אחת ביום ~10:10
(ראה setup_task_scheduler_morning_summary.ps1).
"""
import logging
import sys
import os
import ctypes
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ר' run_daily_summary.py להסבר המלא על הצורך ב-ES_SYSTEM_REQUIRED כאן -
# אותה בעיה בדיוק (Task Scheduler מעיר את המחשב כדי *להתחיל*, לא מונע ממנו
# לחזור לישון תוך כדי הריצה).
if sys.platform == "win32":
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

from src.config import load_config, db_path
from src.store import get_conn, get_bought_holdings
from src.daily_summary import build_morning_summary
from src import market_data, notifier, fees, constituents, schedule_guard


def _build_holdings_summary(conn, cfg) -> list[dict]:
    holdings = get_bought_holdings(conn)
    result = []
    for h in holdings:
        # today_df עובר כבר את תיקון-הטריות של market_data
        # (_fix_stale_rows_with_live_quote), ולכן עמיד יותר לכשל זמני מ-
        # fetch_current_price (קריאת .info בודדת, ללא נפילה חזרה). שולפים אותו
        # קודם כדי שיהיה לנו fallback אמין אם השליפה הבודדת נכשלת.
        today_df = market_data.fetch_universe_daily_changes([h["ticker"]])
        today_pct = float(today_df.iloc[0]["pct_change"]) if not today_df.empty else None
        current = market_data.fetch_current_price(h["ticker"])
        if current is None and not today_df.empty:
            current = float(today_df.iloc[0]["last_close"])
        entry = h["actual_entry_price"]
        qty = h["actual_qty"]
        ccy = constituents.INDEX_CURRENCY.get(h.get("index_name"), "ILS")
        country_code = constituents.INDEX_COUNTRY_CODE.get(h.get("index_name"), "IL")

        days_held = 1
        if h.get("bought_at"):
            try:
                bought_dt = dt.datetime.fromisoformat(h["bought_at"])
                days_held = max((dt.datetime.now() - bought_dt).days, 0) + 1
            except Exception:
                pass

        net_pnl, net_pct = None, None
        if current is not None and entry:
            net = fees.compute_net_result(
                country_code=country_code, buy_price=entry, sell_price=current,
                position_size_ccy=entry * qty, holding_days=max(days_held, 1), fees_cfg=cfg["fees"],
            )
            net_pnl, net_pct = net.net_pnl, net.net_return_pct

        result.append({
            "ticker": h["ticker"], "name": h["company_name"] or h["ticker"],
            "net_pnl": net_pnl, "net_pct": net_pct, "today_pct": today_pct,
            "ccy_symbol": {"ILS": 'ש"ח', "USD": "$"}.get(ccy, ccy),
        })
    return result


def _build_movers_by_index(cfg) -> dict[str, list[dict]]:
    movers_by_index: dict[str, list[dict]] = {}
    for index_name in (cfg.get("indices") or []):
        tickers = constituents.get_constituents(index_name)
        df = market_data.fetch_universe_daily_changes(tickers)
        if df.empty:
            continue
        name_map = (
            constituents.get_il_name_map(index_name) if index_name.upper() in ("TA35", "TA125")
            else constituents.get_us_name_map(index_name)
        )
        movers_by_index[index_name] = [
            {"ticker": r["ticker"], "name": name_map.get(r["ticker"], r["ticker"]), "pct_change": r["pct_change"]}
            for _, r in df.iterrows()
        ]
    return movers_by_index


def _build_index_changes(cfg) -> dict[str, float | None]:
    return {
        index_name: market_data.fetch_index_proxy_change(index_name)
        for index_name in (cfg.get("indices") or [])
    }


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    # ר' run_daily_summary.py - אותה הגנה מפני שליחה בשעה/פעם לא נכונה (הרצת-
    # השלמה מקומית של Task Scheduler, או ריצות חוזרות של scan.yml בענן),
    # מותאמת לחלון הזמן של דוח הבוקר (~10:30 שעון ישראל).
    try:
        cfg = load_config()
        conn = get_conn(db_path(cfg))
        try:
            if not schedule_guard.in_window(10, 30, 10, 45, weekday=schedule_guard.TRADING_WEEKDAYS):
                print("דילוג - מחוץ לחלון הזמן של דוח הבוקר (~10:30 שעון ישראל).")
                sys.exit(0)
            if schedule_guard.already_sent_today(conn, "morning"):
                print("דילוג - כבר נשלח דוח בוקר היום.")
                sys.exit(0)

            holdings_summary = _build_holdings_summary(conn, cfg)

            index_changes = _build_index_changes(cfg)
            movers_by_index = _build_movers_by_index(cfg)
            message = build_morning_summary(
                dt.date.today().isoformat(), index_changes, holdings_summary, movers_by_index,
            )

            if message:
                notifier.send_telegram(cfg, message)
                schedule_guard.mark_sent_today(conn, "morning")
                print("תמונת מצב בוקר נשלחה.")
            else:
                print("אין נתונים - לא נשלח דוח בוקר.")
        finally:
            conn.close()
    finally:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
