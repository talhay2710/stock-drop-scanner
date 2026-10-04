"""בניית snapshot של אחזקות/מכירות-מהיום לשימוש בהודעות טלגרם (סיכום יומי,
תמונת מצב בוקר) - משותף בין run_daily_summary.py ל-run_morning_summary.py,
כדי שתיקון כאן (למשל בסיס נכון ל"שינוי היום") יחול על שתי ההודעות, לא רק
על אחת מהן (30.9.2026, בעקבות "run_morning_summary.py מגדיר לעצמו עותק כפול").
"""
import datetime as dt

from src import market_data, fees, constituents
from src.store import get_bought_holdings
from src.market_hours import israel_today


def build_holdings_summary(conn, cfg) -> list[dict]:
    """מחזיר רשימת dict-ים (אחת לכל אחזקה פתוחה) עם net_pnl/net_pct (מאז
    הכניסה, נטו אחרי עמלות) ו-today_pct/today_pnl (שינוי היום בלבד, ברוטו).
    """
    holdings = get_bought_holdings(conn)
    result = []
    for h in holdings:
        # today_df עובר כבר את תיקון-הטריות של market_data
        # (_fix_stale_rows_with_live_quote), ולכן עמיד יותר לכשל זמני מ-
        # fetch_current_price (קריאת .info בודדת, ללא נפילה חזרה). שולפים אותו
        # קודם כדי שיהיה לנו fallback אמין אם השליפה הבודדת נכשלת.
        today_df = market_data.fetch_universe_daily_changes([h["ticker"]])
        current = market_data.fetch_current_price(h["ticker"])
        if current is None and not today_df.empty:
            current = float(today_df.iloc[0]["last_close"])
        entry = h["actual_entry_price"]
        qty = h["actual_qty"]
        # אחזקה שנקנתה היום ממש - "שינוי היום" חייב להיות מול מחיר הכניסה,
        # לא מול סגירת אתמול (שלא הייתה רלוונטית לך בכלל לפני שקנית) - אותה
        # טעות בדיוק כמו enrich_closed_today_with_today_pnl למטה, רק הפוך:
        # קנייה, לא מכירה (30.9.2026, "לקחת בחשבון את המכירה ברווח?"). הדשבורד
        # כבר מטפל בזה (_using_entry_baseline2 ב-dashboard.py) - כאן גרסה
        # פשוטה יותר.
        bought_today = False
        if h.get("bought_at"):
            try:
                bought_today = dt.datetime.fromisoformat(h["bought_at"]).date() == israel_today()
            except Exception:
                pass

        if bought_today and current is not None and entry:
            baseline = entry
        elif not today_df.empty:
            _prev_close = today_df.iloc[0].get("prev_close")
            # prev_close_gap: ה"אתמול" הזה ישן ביום מסחר או יותר - אין לנו שינוי יומי
            # אמיתי, עדיף "אין נתון" מאחוז מנופח.
            baseline = float(_prev_close) if (
                _prev_close is not None and not (isinstance(_prev_close, float) and _prev_close != _prev_close)
                and not bool(today_df.iloc[0].get("prev_close_gap"))
            ) else None
        else:
            baseline = None

        today_pct = ((current - baseline) / baseline * 100) if (current is not None and baseline) else None
        today_pnl = (current - baseline) * qty if (current is not None and baseline) else None
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
            "net_pnl": net_pnl, "net_pct": net_pct, "today_pct": today_pct, "today_pnl": today_pnl,
            "ccy_symbol": {"ILS": 'ש"ח', "USD": "$"}.get(ccy, ccy),
        })
    return result


def enrich_closed_today_with_today_pnl(closed_today: list[dict]) -> list[dict]:
    """מוסיף today_pnl (שינוי המחיר היום בלבד, לא הרווח הכולל מאז הכניסה) לכל
    פוזיציה שנסגרה היום - כדי ש"מה התיק עשה היום" ב-daily_summary יוכל לכלול
    גם מכירות מהיום, לא רק אחזקות שעדיין פתוחות (30.9.2026, "לקחת בחשבון את
    המכירה ברווח?"). ברוטו, ללא עמלות - עקבי עם today_pnl של אחזקות פתוחות
    (build_holdings_summary למעלה), שגם הוא ברוטו טהור."""
    for c in closed_today:
        today_df = market_data.fetch_universe_daily_changes([c["ticker"]])
        c["today_pnl"] = None
        if today_df.empty:
            continue
        prev_close = today_df.iloc[0].get("prev_close")
        if prev_close is None or (isinstance(prev_close, float) and prev_close != prev_close):
            continue
        c["today_pnl"] = (c["exit_price"] - float(prev_close)) * c["qty"]
    return closed_today
