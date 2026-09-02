"""שולח סיכום יומי אחד בטלגרם על כל ההתראות שנשלחו היום, עם מחיר עדכני מול
הכניסה/יעד/סטופ שהוצעו. מיועד להרצה פעם אחת ביום אחרי סגירת המסחר האמריקאי
(ראה setup_task_scheduler.ps1).
"""
import logging
import sys
import os
import ctypes
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ה-Task Scheduler מגדיר "להעיר את המחשב כדי להריץ" - אבל זה רק מעיר אותו
# כדי *להתחיל*, לא מונע ממנו לחזור לישון (Modern Standby) תוך כדי הריצה.
# נצפה בפועל: המחשב יצא משינה, המשימה התחילה, והמחשב חזר לישון תוך שנייה -
# הפייתון נהרג עוד לפני שהספיק לכתוב אפילו שורת לוג אחת. ES_SYSTEM_REQUIRED
# אומר ל-Windows "אל תירדם כל עוד אני רץ" - בלי זה, הנעילה על השעון בלבד לא מספיקה.
if sys.platform == "win32":
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

from src.config import load_config, db_path
from src.store import get_conn, get_bought_holdings, get_closed_trades_on_date
from src.daily_summary import build_daily_summary
from src import market_data, notifier, backtest, fees, constituents, schedule_guard
from src.market_hours import israel_today


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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log"), encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    # מיועד לרוץ ~18:00 שעון ישראל. שני שימושים אפשריים: (א) Task Scheduler
    # מקומי - אם המחשב היה כבוי בזמן המתוזמן, StartWhenAvailable מריץ את
    # המשימה שהוחמצה מיד כשהמחשב מתעורר, גם אם זה 3 לפנות בוקר. (ב) scan.yml
    # בענן - רץ כל 5 דק' ומזהה לבד מתי הגיע הזמן. חלון הזמן + "כבר נשלח היום"
    # מגנים משני התרחישים גם יחד - ר' src/schedule_guard.py.
    try:
        cfg = load_config()
        conn = get_conn(db_path(cfg))
        try:
            if not schedule_guard.in_window(18, 0, 18, 15, weekday=schedule_guard.TRADING_WEEKDAYS):
                print("דילוג - מחוץ לחלון הזמן של הסיכום היומי (~18:00 שעון ישראל).")
                sys.exit(0)
            if schedule_guard.already_sent_today(conn, "daily"):
                print("דילוג - כבר נשלח סיכום יומי היום.")
                sys.exit(0)

            today = israel_today().isoformat()
            holdings_summary = _build_holdings_summary(conn, cfg)
            closed_today = get_closed_trades_on_date(conn, today)
            message = build_daily_summary(conn, today, holdings_summary, closed_today=closed_today)

            updated = backtest.refresh_pending_outcomes(conn)
            if updated:
                print(f"עודכנו {updated} outcome-ים היסטוריים (לטרק-רקורד עתידי).")

            signals_resolved = backtest.resolve_signal_outcomes(conn)
            if signals_resolved:
                print(f"נפתרו {signals_resolved} אותות-צל (signal_log).")

            if message:
                notifier.notify_typed(cfg, "daily_summary", message, "📅 סיכום יומי", "")
                schedule_guard.mark_sent_today(conn, "daily")
                print("סיכום יומי נשלח.")
            else:
                print("אין התראות היום - לא נשלח סיכום.")
        finally:
            conn.close()
    finally:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
