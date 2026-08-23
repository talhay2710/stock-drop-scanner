"""אורכסטרציית סריקה - מחבר בין כל המודולים לסבב סריקה אחד."""
import logging
import datetime as dt

import pandas as pd
import requests

from . import constituents
from . import market_data
from . import analysis as analysis_mod
from . import strategy as strategy_mod
from . import fees as fees_mod
from . import store as store_mod
from . import notifier
from .config import db_path
from .market_hours import is_market_open

logger = logging.getLogger(__name__)


def run_startup_health_check(cfg: dict) -> None:
    """בדיקת בריאות חד-פעמית בהפעלה - yfinance וטלגרם - כדי שבעיה כמו ה-18.8.2026
    (cache עוגיות שבור של yfinance + DNS לא זמין לטלגרם) תתגלה מיד בלוג בהפעלה,
    לפני שהיא גורמת לתסמינים מבלבלים (נתונים ישנים, הודעות חסרות) שעות אחר כך
    בלי שאף אחד ישים לב לסיבה האמיתית. לא נכשלת/לא חוסמת את ההרצה - רק מתריעה."""
    problems = []

    try:
        test_price = market_data.fetch_current_price("AAPL")
        if test_price is None:
            problems.append("yfinance: לא הצליח לשלוף מחיר לדוגמה (AAPL) אחרי כל הניסיונות")
    except Exception as e:
        problems.append(f"yfinance: שגיאה - {e}")

    tg = cfg.get("telegram", {})
    if tg.get("enabled") and tg.get("bot_token") and "REPLACE_ME" not in tg.get("bot_token", ""):
        try:
            # getMe - endpoint קליל שרק מוודא טוקן+חיבור תקינים, בלי לשלוח הודעה
            resp = requests.get(f"https://api.telegram.org/bot{tg['bot_token']}/getMe", timeout=10)
            if not resp.ok:
                problems.append(f"טלגרם: תגובה לא תקינה ({resp.status_code})")
        except Exception as e:
            problems.append(f"טלגרם: שגיאת חיבור - {e}")

    if not problems:
        logger.info("בדיקת בריאות בהפעלה עברה בהצלחה (yfinance + טלגרם תקינים)")
        return

    logger.warning("בדיקת בריאות בהפעלה נכשלה: %s", " | ".join(problems))
    # מתריעים דרך הערוץ שכן עובד, אם יש כזה - כדי שהבעיה תגיע גם כשלא בודקים לוגים
    if not any(p.startswith("טלגרם") for p in problems):
        notifier.send_telegram(cfg, "⚠️ <b>בדיקת בריאות בהפעלה נכשלה</b>\n" + "\n".join(problems))


def run_scan(cfg: dict) -> list[dict]:
    """מריץ סבב סריקה עבור כל המדדים שהוגדרו ב-cfg['indices'], כל אחד בבדיקת
    שעות המסחר שלו בנפרד (למשל אפשר לסרוק TA35 בזמן שהשוק האמריקאי סגור)."""
    indices = cfg.get("indices") or ([cfg["index"]] if "index" in cfg else [])
    if not indices:
        raise ValueError("לא הוגדר אף מדד ב-config.yaml (indices)")

    conn = store_mod.get_conn(db_path(cfg))
    vix_level, _ = market_data.fetch_vix_level()
    all_results = []
    try:
        for index in indices:
            index = index.upper()
            if not is_market_open(index):
                logger.info("מחוץ לשעות המסחר של מדד %s - דילוג", index)
                continue
            try:
                all_results.extend(_scan_one_index(cfg, index, conn, vix_level))
            except Exception:
                logger.exception("שגיאה בסריקת מדד %s", index)
        try:
            check_holdings_gains(cfg, conn)
        except Exception:
            logger.exception("שגיאה בבדיקת עליות באחזקות")
        try:
            check_price_alerts(cfg, conn)
        except Exception:
            logger.exception("שגיאה בבדיקת התראות מחיר ידניות")
        try:
            check_reversal_confirmations(cfg, conn)
        except Exception:
            logger.exception("שגיאה בבדיקת אישור היפוך")
    finally:
        conn.close()
    return all_results


def _gain_level(gain_pct: float, start_pct: float, step_pct: float) -> int | None:
    """רמת המדרגה הנוכחית (0, 1, 2...) שהעלייה כבר חצתה - None אם עוד לא הגיעה
    לסף ההתחלתי. למשל עם start=2, step=1: 2.3%->0, 3.9%->1, 5.0%->2 וכו'."""
    if gain_pct < start_pct:
        return None
    return int((gain_pct - start_pct) // step_pct)


def check_holdings_gains(cfg: dict, conn) -> None:
    """בודק את כל האחזקות שסומנו כ'נקנו בפועל' - אם מניה עלתה מספיק מעל מחיר
    הכניסה האמיתי שלך, שולח התראת טלגרם עם רווח נטו אמיתי. מתריע פעם אחת לכל
    מדרגת עלייה (start_pct, ואז כל step_pct נוספים) - לא מציף על כל בדיקה."""
    start_pct = abs(cfg.get("holdings_gain_alert_start_pct", 2.0))
    step_pct = abs(cfg.get("holdings_gain_alert_step_pct", 1.0)) or 1.0
    holdings = store_mod.get_bought_holdings(conn)
    if not holdings:
        return

    tickers = list({h["ticker"] for h in holdings})
    # מחיר עדכני אמיתי לכל טיקר בנפרד (regularMarketPrice) - לא ההורדה בבת אחת
    # (fetch_universe_daily_changes), שהתבררה כמפגרת לפעמים אחרי סשן המסחר האחרון.
    # מספר האחזקות קטן, אז קריאה בודדת לכל טיקר לא מכבידה
    price_map = {t: market_data.fetch_current_price(t) for t in tickers}
    # רק לגיבוי - תאריך הסגירה היומית (ההורדה בבת אחת), למקרה ש-regularMarketPrice
    # עצמו יהיה איכשהו ישן יותר מהכניסה שלך
    price_df = market_data.fetch_universe_daily_changes(tickers)
    close_date_map = dict(zip(price_df["ticker"], price_df["last_close_date"])) if not price_df.empty else {}

    for h in holdings:
        if h.get("index_name") and not is_market_open(h["index_name"]):
            continue
        current = price_map.get(h["ticker"])
        entry = h["actual_entry_price"]
        qty = h["actual_qty"]
        if current is None or not entry:
            continue

        bought_dt = None
        if h.get("bought_at"):
            try:
                bought_dt = dt.datetime.fromisoformat(h["bought_at"])
            except Exception:
                pass

        close_date = close_date_map.get(h["ticker"])
        if bought_dt is not None and close_date is not None and close_date < bought_dt.date():
            # הסגירה האחרונה שיש לנו היא עוד מלפני שקנית - עדיין אין נתון רלוונטי
            # להשוואה מול מחיר הכניסה שלך (זו לא "עלייה", זו סתם סגירה ישנה)
            continue

        display_name = h["company_name"] or h["ticker"]
        country_code = constituents.INDEX_COUNTRY_CODE.get(h["index_name"], "IL")
        ccy = constituents.INDEX_CURRENCY.get(h["index_name"], "ILS")
        ccy_symbol = CURRENCY_DISPLAY.get(ccy, ccy)

        gain_pct = (current / entry - 1) * 100
        level = _gain_level(gain_pct, start_pct, step_pct)
        last_alerted = h["last_gain_alert_pct"]
        last_level = _gain_level(last_alerted, start_pct, step_pct) if last_alerted is not None else None
        if level is not None and (last_level is None or level > last_level):
            holding_days = max((dt.date.today() - bought_dt.date()).days, 1) if bought_dt is not None else 1
            net = fees_mod.compute_net_result(
                country_code=country_code, buy_price=entry, sell_price=current,
                position_size_ccy=entry * (qty or 0), holding_days=holding_days, fees_cfg=cfg["fees"],
            )
            message = "\n".join([
                f"📈 <b>{display_name} עלתה {_signed(gain_pct, 1, '%')} מהכניסה שלך</b>",
                f"{h['ticker']}",
                "",
                "💡 <b>מחירים</b>",
                f"כניסה: {_format_price(entry, ccy, with_unit=False)}  |  "
                f"נוכחי: {_format_price(current, ccy, with_unit=False)}",
                f"מספר מניות: {qty:,.0f}",
                "",
                "💰 <b>נטו</b>",
                f"רווח נטו: {_signed(net.net_pnl)} {ccy_symbol}  ({_signed(net.net_return_pct, 1, '%')})",
            ])
            notifier.send_telegram(cfg, message)
            store_mod.update_gain_alert(conn, h["id"], gain_pct)

        _check_stop_proximity(cfg, conn, h, display_name, entry, current, ccy)
        _check_target_proximity(cfg, conn, h, display_name, entry, current, ccy)


STOP_LOSS_FACTOR = 0.97  # תואם לחישוב הסטופ באסטרטגיה (strategy.py) - כ-3% מתחת לכניסה
STOP_WARN_PCT = 2.0      # "מתקרב לסטופ" = במרחק הזה (%) או פחות מעל קו הסטופ
TARGET_WARN_PCT = 2.0    # "מתקרב ליעד" = במרחק הזה (%) או פחות מתחת ליעד


def _check_stop_proximity(cfg: dict, conn, h: dict, display_name: str, entry: float, current: float, ccy: str) -> None:
    """מתריע פעם אחת כשאחזקה מתקרבת (או כבר חצתה) את הסטופ-לוס המשוער שלה -
    3% מתחת למחיר הכניסה בפועל שלך, אותה מוסכמה בדיוק כמו בהצעת האסטרטגיה
    המקורית. לא מציף: מתריע פעם אחת בכניסה לאזור הסכנה, ומתאפס בשקט (בלי
    הודעה) רק כשהמחיר מתרחק בבירור בחזרה למעלה."""
    warn_pct = abs(cfg.get("holdings_stop_warn_pct", STOP_WARN_PCT))
    stop_price = h.get("holding_stop_price") or (entry * STOP_LOSS_FACTOR)
    distance_pct = (current - stop_price) / stop_price * 100
    was_active = bool(h.get("stop_alert_active"))

    if distance_pct > warn_pct:
        if was_active and distance_pct > warn_pct * 2:
            store_mod.update_stop_alert(conn, h["id"], False)
        return
    if was_active:
        return

    title = (
        f"🛑 <b>{display_name} חצתה את הסטופ שלך</b>" if current <= stop_price
        else f"🛑 <b>{display_name} מתקרבת לסטופ שלך</b>"
    )
    message = "\n".join([
        title,
        f"{h['ticker']}",
        "",
        f"מחיר נוכחי: {_format_price(current, ccy, with_unit=False)}",
        f"<b>הסטופ שלך: {_format_price(stop_price, ccy, with_unit=False)}</b>",
        f"נכנסת ב-{_format_price(entry, ccy, with_unit=False)}",
    ])
    notifier.send_telegram(cfg, message)
    store_mod.update_stop_alert(conn, h["id"], True)


def _check_target_proximity(cfg: dict, conn, h: dict, display_name: str, entry: float, current: float, ccy: str) -> None:
    """אותה לוגיקה בדיוק כמו _check_stop_proximity, בכיוון ההפוך - מתריע פעם
    אחת כשאחזקה מתקרבת (או כבר הגיעה) ליעד המכירה שלה. היעד מחושב דרך
    strategy.live_target_price - אותו מקור אמת בדיוק שהדשבורד משתמש בו
    לתצוגה, כדי ששניהם תמיד יראו את אותו יעד."""
    warn_pct = abs(cfg.get("holdings_target_warn_pct", TARGET_WARN_PCT))
    stop_price = h.get("holding_stop_price") or (entry * STOP_LOSS_FACTOR)
    target_price = strategy_mod.live_target_price(entry, stop_price, h.get("target_base"))
    distance_pct = (target_price - current) / target_price * 100
    was_active = bool(h.get("target_alert_active"))

    if distance_pct > warn_pct:
        if was_active and distance_pct > warn_pct * 2:
            store_mod.update_target_alert(conn, h["id"], False)
        return
    if was_active:
        return

    title = (
        f"🎯 <b>{display_name} הגיעה ליעד שלך!</b>" if current >= target_price
        else f"🎯 <b>{display_name} מתקרבת ליעד שלך</b>"
    )
    message = "\n".join([
        title,
        f"{h['ticker']}",
        "",
        f"מחיר נוכחי: {_format_price(current, ccy, with_unit=False)}",
        f"<b>היעד שלך: {_format_price(target_price, ccy, with_unit=False)}</b>",
        f"נכנסת ב-{_format_price(entry, ccy, with_unit=False)}",
    ])
    notifier.send_telegram(cfg, message)
    store_mod.update_target_alert(conn, h["id"], True)


def check_price_alerts(cfg: dict, conn) -> None:
    """בודק את כל התראות המחיר הידניות הפעילות - אם המניה חצתה את מחיר היעד
    בכיוון שביקשת (מעל/מתחת), שולח התראת טלגרם וסוגר את ההתראה (חד-פעמית,
    לא חוזרת על עצמה). זו לא התראת "ירידה חדה" של הסורק - היא פשוט "תגיד לי
    כשמניה X מגיעה למחיר Y", בלי קשר לניתוח תגובת-יתר."""
    alerts = store_mod.get_active_price_alerts(conn)
    if not alerts:
        return

    tickers = list({a["ticker"] for a in alerts})
    price_map = {t: market_data.fetch_current_price(t) for t in tickers}

    for a in alerts:
        current = price_map.get(a["ticker"])
        if current is None:
            continue
        target = a["target_price"]
        crossed = (current >= target) if a["direction"] == "above" else (current <= target)
        if not crossed:
            continue

        display_name = a["company_name"] or a["ticker"]
        ccy = constituents.INDEX_CURRENCY.get(a.get("index_name"), "ILS")
        direction_word = "מעל" if a["direction"] == "above" else "מתחת ל"
        message = "\n".join([
            f"🔔 <b>{display_name} הגיעה ל{direction_word}-{_format_price(target, ccy, with_unit=False)}</b>",
            f"{a['ticker']}",
            "",
            f"מחיר נוכחי: {_format_price(current, ccy, with_unit=False)}",
            f"מחיר יעד שקבעת: {_format_price(target, ccy, with_unit=False)}",
        ])
        notifier.send_telegram(cfg, message)
        store_mod.deactivate_price_alert(conn, a["id"], triggered=True)
        logger.info("התראת מחיר הופעלה: %s %s %s", a["ticker"], direction_word, target)


def check_reversal_confirmations(cfg: dict, conn) -> None:
    """עוקב אחרי התראות ירידה שנשלחו היום ומחפש סימן היפוך אמיתי - התאוששות של
    reversal_confirm_pct מהשפל שנרשם מאז ההתראה. לא מחליף את התראת הירידה
    המקורית (שממשיכה לצאת מיד, בלי שום עיכוב) - זו התראה נוספת ונפרדת, רק אם
    וכשיש התאוששות בפועל. מפסיק לעקוב ברגע שנשלחה (reversal_alert_sent),
    ומתאפס ממילא מחר (scan_date חדש)."""
    scan_date = dt.date.today().isoformat()
    pending = store_mod.get_pending_reversal_watches(conn, scan_date)
    if not pending:
        return

    reversal_pct = abs(cfg.get("reversal_confirm_pct", 3.0))

    for p in pending:
        current = market_data.fetch_current_price(p["ticker"])
        if current is None or current <= 0:
            continue

        prior_low = p.get("reversal_low_price")
        low = min(prior_low, current) if prior_low else current
        if low < (prior_low or low):
            store_mod.update_reversal_low(conn, p["id"], low)

        bounce_pct = (current - low) / low * 100
        if bounce_pct < reversal_pct:
            continue

        ccy = constituents.INDEX_CURRENCY.get(p.get("index_name"), "ILS")
        display_name = p.get("company_name") or p["ticker"]
        alert_time = p["scan_ts"][11:16] if p.get("scan_ts") and len(p["scan_ts"]) >= 16 else ""

        lines = [
            f"🔄 <b>{display_name} מראה סימני התאוששות</b>",
            f"{p['ticker']}",
            "",
            f"הירידה המקורית: {_signed(p['pct_change'], 1, '%')}"
            + (f" (התראה נשלחה ב-{alert_time})" if alert_time else ""),
            f"מחיר נוכחי: {_format_price(current, ccy, with_unit=False)} "
            f"(עלתה {_signed(bounce_pct, 1, '%')} מהשפל של היום)",
        ]
        if p.get("intraday_recovery_pct") is not None:
            lines.append(f"התאוששות תוך-יומית: {p['intraday_recovery_pct']:.0f}%")
        if p.get("entry_limit") and p.get("stop_loss") and p.get("target_base"):
            lines.append("")
            lines.append(
                f"כניסה מוצעת: {_format_price(p['entry_limit'], ccy, with_unit=False)} | "
                f"סטופ: {_format_price(p['stop_loss'], ccy, with_unit=False)} | "
                f"יעד: {_format_price(p['target_base'], ccy, with_unit=False)}"
            )

        notifier.send_telegram(cfg, "\n".join(lines))
        store_mod.mark_reversal_alert_sent(conn, p["id"])
        logger.info("התראת היפוך נשלחה: %s (%.1f%% מהשפל)", p["ticker"], bounce_pct)


def _scan_one_index(cfg: dict, index: str, conn, vix_level: float | None = None) -> list[dict]:
    threshold = abs(cfg["drop_threshold_pct"])
    country_code = constituents.INDEX_COUNTRY_CODE[index]
    is_israeli = country_code == "IL"
    currency = constituents.INDEX_CURRENCY[index]

    logger.info("שולף רשימת מניות עבור מדד %s", index)
    tickers = constituents.get_constituents(index)
    logger.info("נסרקות %d מניות (%s)", len(tickers), index)

    name_map = constituents.get_il_name_map(index) if is_israeli else constituents.get_us_name_map(index)

    df = market_data.fetch_universe_daily_changes(tickers)
    if df.empty:
        logger.warning("לא התקבלו נתוני מחיר עבור אף מניה (%s)", index)
        return []

    # אם מקור הנתונים מפגר (הסגירה האחרונה הזמינה ישנה יותר מיום המסחר האחרון
    # שאמור כבר להיות זמין) - pct_change לא באמת מייצג שינוי של אתמול/היום, אלא
    # השוואה בין שני ימים ישנים יותר. סורקים כאלה עלולים לגרום להתראות שגויות
    # (או להחמיץ ירידה אמיתית של אתמול) - מדלגים עליהם לגמרי במקום להתריע על נתון לא אמין.
    _stale_mask = df.apply(lambda r: market_data.is_data_stale(r["last_close_date"], r["ticker"]), axis=1)
    _n_stale = int(_stale_mask.sum())
    if _n_stale:
        logger.warning(
            "%d מניות דולגו (%s) - נתון המחיר האחרון הזמין ישן מדי (מקור הנתונים מפגר)",
            _n_stale, index,
        )
    df = df[~_stale_mask].copy()
    if df.empty:
        logger.warning("כל נתוני המחיר עבור %s התבררו כישנים מדי - דילוג על הסבב הזה", index)
        return []

    multi_day_window = cfg.get("multi_day_window_days", 3)
    multi_day_threshold = abs(cfg.get("multi_day_threshold_pct", 5.0))
    multi_day_enabled = cfg.get("multi_day_enabled", True)
    df["n_day_change"] = df["history"].apply(
        lambda h: market_data.compute_n_day_change_pct(h, multi_day_window)
    )

    scan_date = dt.date.today().isoformat()

    # אימות ירידה: מניה שחוצה את הסף בבת אחת, בלי שנראתה קודם אפילו קרוב אליו,
    # עלולה להיות תקלת ציטוט רגעית (טעות בקריאה בודדת, לא נתון מפגר - זה כבר
    # מטופל למעלה) ולא ירידה אמיתית. לכן ברגע שמניה נכנסת ל"אזור אזהרה"
    # (watch_buffer% לפני הסף), רושמים אותה כמועמדת; רק אם היא נראתה שם *גם*
    # בסריקה קודמת (כלומר נמשכת לפחות סבב סריקה אחד, כ-5 דקות) מתריעים בפועל
    # כשהיא מגיעה לסף עצמו. לא מוסיף עיכוב מעבר לסף שהגדרת - רק דורש שהוא לא
    # ייעלם כבר בסריקה הבאה.
    watch_buffer = abs(cfg.get("drop_confirm_watch_pct", 1.0))
    watch_threshold = max(threshold - watch_buffer, 0.0)
    confirmed = pd.Series(False, index=df.index)
    in_watch_zone = df["pct_change"] <= -watch_threshold
    for idx in df[in_watch_zone].index:
        cand_ticker = df.loc[idx, "ticker"]
        cand_pct = float(df.loc[idx, "pct_change"])
        if store_mod.get_watch_candidate(conn, cand_ticker, index, scan_date):
            confirmed.loc[idx] = True
        store_mod.upsert_watch_candidate(conn, cand_ticker, index, scan_date, cand_pct)

    single_day_flag = (df["pct_change"] <= -threshold) & confirmed
    if multi_day_enabled:
        multi_day_flag = df["n_day_change"] <= -multi_day_threshold
    else:
        multi_day_flag = pd.Series(False, index=df.index)
    flagged = df[single_day_flag | multi_day_flag].copy()
    flagged["is_multi_day_only"] = multi_day_flag[flagged.index] & ~single_day_flag[flagged.index]
    flagged["severity"] = flagged[["pct_change", "n_day_change"]].min(axis=1)

    logger.info("%d מניות חצו את סף הירידה (יומי/מצטבר) (%s)", len(flagged), index)
    if flagged.empty:
        return []

    index_change_pct = market_data.fetch_index_proxy_change(index)
    market_regime_tag, market_regime_label = market_data.classify_market_regime(index, vix_level)

    dedupe = cfg.get("dedupe_same_day", True)

    reference_position_size = cfg["position_size"].get(currency, 10000)
    max_position_size = cfg.get("max_position_size", {}).get(currency, reference_position_size * 3)
    account_size = cfg.get("account_size", {}).get(currency)
    risk_pct_per_trade = cfg.get("risk_pct_per_trade", 0.75)
    max_holding_days = cfg.get("assumed_holding_days", 5)

    results = []
    for _, row in flagged.sort_values("severity").iterrows():
        ticker = row["ticker"]

        if dedupe:
            prior_pct = store_mod.get_todays_alert_pct(conn, ticker, scan_date)
            if prior_pct is not None:
                # לא רק "החמיר בכלל" - חייב להחמיר בלפחות step_pct נוסף, אחרת
                # תנודות זעירות בין סריקות (כל 5 דק') מציפות בהתראות חוזרות על
                # אותה ירידה בפועל. אותה מוסכמה בדיוק כמו step_pct בהתראות עלייה
                # של אחזקות (check_holdings_gains).
                step_pct = abs(cfg.get("drop_alert_step_pct", 2.0)) or 2.0
                if row["pct_change"] > prior_pct - step_pct:
                    logger.info(
                        "דילוג על %s - הירידה לא החמירה ב-%.1f%% נוספים מאז ההתראה הקודמת היום",
                        ticker, step_pct,
                    )
                    continue

            # דדופ נוסף לפי תאריך הנתון עצמו (last_close_date), לא רק לפי scan_date -
            # כי מקור הנתונים לפעמים לא מתעדכן יום-יומיים ברציפות. בלי זה, ברגע
            # שמתחיל יום סריקה חדש (scan_date אחר) אבל הנתון עדיין אותו נתון בדיוק
            # מאתמול, המערכת הייתה שולחת שוב "התראה חדשה" על ירידה שכבר טופלה.
            # בניגוד לדדופ הרגיל (שמאפשר שליחה חוזרת אם הירידה החמירה תוך כדי יום
            # מסחר) - כאן מדלגים תמיד אם כבר נשלחה התראה על אותו last_close_date
            # בדיוק, כי הבדל קטן בציטוט (רעש בין קריאות) לא אומר שהמצב באמת השתנה.
            _close_date = row.get("last_close_date")
            if _close_date is not None:
                prior_pct_same_data = store_mod.get_alert_pct_for_close_date(conn, ticker, _close_date.isoformat())
                if prior_pct_same_data is not None:
                    logger.info(
                        "דילוג על %s - כבר נשלחה התראה על אותו נתון בדיוק (last_close_date=%s), "
                        "מקור הנתונים עדיין לא התעדכן", ticker, _close_date,
                    )
                    continue

        company_name = name_map.get(ticker)
        if not company_name and is_israeli:
            # קובץ הרכיבים לא צריך להיות חסר טיקר ישראלי פעיל - אם קרה, זה סימן
            # שהקובץ מיושן (ר' constituents.get_il_name_map). בכל מקרה, לא רוצים
            # שהטיקר הלטיני יחליק כ"שם חברה" בהודעה - עדיף placeholder בעברית.
            logger.warning("אין שם עברי לטיקר %s ברשימת הרכיבים - קובץ הרכיבים כנראה מיושן", ticker)
            company_name = "מניה ישראלית (שם לא זוהה)"

        volume_ratio = None
        if row.get("last_volume") and row.get("avg_volume_20d"):
            volume_ratio = row["last_volume"] / row["avg_volume_20d"]

        analysis = analysis_mod.classify_drop(
            ticker=ticker,
            yahoo_symbol=ticker,
            company_name=company_name,
            is_israeli=is_israeli,
            pct_change=row["pct_change"],
            close_history=row["history"],
            index_change_pct=index_change_pct,
            cfg=cfg,
            volume_ratio=volume_ratio,
            vix_level=vix_level,
            intraday_recovery_pct=row.get("intraday_recovery_pct"),
        )

        if analysis.reasons == ["ex_dividend"]:
            logger.info("דילוג על %s - הירידה מוסברת ע\"י ניתוק דיבידנד, לא ירידה אמיתית", ticker)
            continue

        if analysis.reasons == ["stock_split"]:
            logger.info("דילוג על %s - הירידה מוסברת ע\"י פיצול מניה, לא ירידה אמיתית", ticker)
            continue

        holding_days = _assumed_holding_days(analysis.overreaction_score, max_holding_days)

        is_multi_day_only = bool(row.get("is_multi_day_only"))

        atr = market_data.compute_atr(row.get("highs"), row.get("lows_series"), row["history"])

        # פרוקסי נזילות: נפח מסחר ממוצע יומי בערך (מטבע מקומי - ₪ ל-TASE, $ לארה"ב).
        # אין נתון spread אמיתי זמין בחינם, ראו הערה ב-strategy._liquidity_adjustment.
        avg_dollar_volume = (
            row["avg_volume_20d"] * row["last_close"] if row.get("avg_volume_20d") is not None else None
        )

        trade_idea = strategy_mod.suggest_strategy(
            last_close=row["last_close"],
            last_low=row.get("last_low"),
            recent_20d_low=row.get("recent_20d_low"),
            overreaction_score=analysis.overreaction_score,
            atr=atr,
            avg_dollar_volume=avg_dollar_volume,
        )

        if account_size:
            risk_amount = account_size * risk_pct_per_trade / 100.0
            position_size = fees_mod.compute_risk_based_position_size(
                entry_price=trade_idea.entry_limit,
                stop_price=trade_idea.stop_loss,
                risk_amount=risk_amount,
                reference_size=reference_position_size,
                max_size=max_position_size,
            )
        else:
            position_size = reference_position_size

        net_profit_scenario = fees_mod.compute_net_result(
            country_code=country_code,
            buy_price=trade_idea.entry_limit,
            sell_price=trade_idea.target_base,
            position_size_ccy=position_size,
            holding_days=holding_days,
            fees_cfg=cfg["fees"],
        )
        net_loss_scenario = fees_mod.compute_net_result(
            country_code=country_code,
            buy_price=trade_idea.entry_limit,
            sell_price=trade_idea.stop_loss,
            position_size_ccy=position_size,
            holding_days=holding_days,
            fees_cfg=cfg["fees"],
        )

        net_results = {"profit_scenario": net_profit_scenario, "loss_scenario": net_loss_scenario}

        prior_message_id = store_mod.get_todays_telegram_message_id(conn, ticker, scan_date)

        record = store_mod.build_record(scan_date, ticker, company_name, index, row, analysis, trade_idea, net_results)
        record["market_regime"] = market_regime_tag
        new_id = store_mod.save_alert(conn, record)
        sector_peers = store_mod.count_todays_sector_alerts(conn, analysis.sector, scan_date, exclude_ticker=ticker)

        message = _format_message(
            ticker, company_name, index, row, analysis, trade_idea,
            net_profit_scenario, net_loss_scenario, currency, position_size,
            multi_day_window, sector_peers, is_multi_day_only, market_regime_label,
        )

        edited = prior_message_id and notifier.edit_telegram(cfg, prior_message_id, message)
        if not edited:
            new_message_id = notifier.send_telegram(cfg, message)
            if new_message_id:
                store_mod.update_telegram_message_id(conn, new_id, new_message_id)

        if is_multi_day_only:
            desktop_title = f"📉 {ticker} ירדה מצטבר {row.get('n_day_change', 0):.1f}% ב-{multi_day_window} ימים"
        else:
            desktop_title = f"⚠ {ticker} ירדה {row['pct_change']:.1f}%"
        notifier.send_desktop_notification(
            cfg,
            title=desktop_title,
            message=analysis.reason_text[:250],
        )

        results.append({
            "ticker": ticker, "pct_change": row["pct_change"],
            "reason_text": analysis.reason_text, "overreaction_verdict": analysis.overreaction_verdict,
        })

    return results


def _assumed_holding_days(overreaction_score: int, max_days: int) -> int:
    """ימי החזקה משוערים (לצורך דמי הניהול היחסיים בחישוב הנטו) - נבחר דינמית
    לפי עוצמת אות תגובת-היתר: איתות חזק = ריבאונד צפוי מהיר יותר = פחות ימים,
    לעולם לא יותר מ-max_days (המטרה היא מימוש מהיר, לא החזקה ארוכה)."""
    if overreaction_score >= 70:
        return min(2, max_days)
    if overreaction_score >= 45:
        return min(3, max_days)
    return max_days


CURRENCY_DISPLAY = {"ILS": 'ש"ח', "USD": "$"}


def _signed(value: float, decimals: int = 0, suffix: str = "") -> str:
    """מספר עם סימן (+/-) שנשאר לפני המספר גם בתוך טקסט עברי (RTL) - עטוף ב-
    LRI/PDI (בידוד כיווניות LTR מפורש) כדי למנוע היפוך ויזואלי של הסימן.
    LRM (סימן בודד) לא היה מספיק אמין בטלגרם - ה-isolate חזק/עקבי יותר."""
    return f"⁦{value:+,.{decimals}f}{suffix}⁩"


def _format_price(value: float, currency: str, with_unit: bool = True) -> str:
    """מציג מחיר בפורמט שניתן להזין ישירות בהזמנת קנייה אצל הברוקר: לישראל
    באגורות ומעוגל למספר שלם (ככה TASE מציגה ומקבלת הזמנות בפועל, לא בש"ח
    עשרוני), לארה"ב בדולרים עם 2 ספרות אחרי הנקודה כמקובל."""
    if currency == "ILS":
        return f"{value*100:,.0f}" + (" אג'" if with_unit else "")
    return f"${value:,.2f}"


def _format_header_price(value: float, currency: str) -> str:
    """מחיר לכותרת בסוגריים: אגורות בלבד (לישראל), או $ רגיל (לארה"ב)."""
    if currency == "ILS":
        return f"({_format_price(value, currency)})"
    return f"(${value:,.2f})"


def _format_message(ticker, company_name, index, row, analysis, trade_idea,
                     net_profit, net_loss, currency, position_size,
                     multi_day_window=3, sector_peers=0, is_multi_day_only=False,
                     market_regime_label: str | None = None) -> str:
    """הודעה קצרה וממוקדת: מה קרה, למה (בקצרה), האם נראה תגובת יתר, והמלצת
    כניסה/יציאה עם התוצאה נטו - בלי לגלול. פרטים מלאים (חדשות, z-score/RSI
    וכו') זמינים בדשבורד."""
    display_name = company_name or ticker
    ccy = CURRENCY_DISPLAY.get(currency, currency)

    # אם ההתראה הופעלה רק בגלל הירידה המצטברת (לא ירידה יומית חדה) - השינוי היומי
    # לבדו יכול להיראות קטן או אפילו חיובי, ולכן חייבים לתייג את זה כבר בכותרת
    # עצמה, לא רק בשורה משנית - אחרת ההתראה נראית כאילו טעות/לא עקבית.
    header_tag = "📉 ירידה מצטברת" if is_multi_day_only else "⚠️"
    lines = [
        f"{header_tag} <b>{display_name} {_signed(row['pct_change'], 1, '%')} {_format_header_price(row['last_close'], currency)}</b>",
        f"{ticker} · מדד {index}",
        "",
    ]

    n_day_change = row.get("n_day_change")
    if is_multi_day_only and pd.notna(n_day_change):
        lines.append(
            f"📉 ירדה מצטבר {_signed(n_day_change, 1, '%')} ב-{multi_day_window} ימי מסחר אחרונים - "
            f"השינוי היום לבדו ({_signed(row['pct_change'], 1, '%')}) לא חצה את הסף היומי"
        )
    elif pd.notna(n_day_change) and abs(n_day_change) > abs(row["pct_change"]) * 1.3:
        lines.append(f"📉 ירידה מצטברת של {_signed(n_day_change, 1, '%')} ב-{multi_day_window} ימי מסחר אחרונים")

    if sector_peers >= 2 and analysis.sector:
        lines.append(
            f"⚠️ ריכוז סקטוריאלי: עוד {sector_peers} מניות מסקטור {analysis.sector} ירדו היום - "
            f"ייתכן אירוע רחב ולא הזדמנות ספציפית"
        )

    if market_regime_label:
        lines.append(f"מצב שוק כללי: {market_regime_label}")

    if analysis.residual_drop_pct is not None:
        lines.append(f"📌 ירידה עודפת (מעבר למדד/סקטור): {_signed(analysis.residual_drop_pct, 1, '%')}")

    if analysis.dist_from_ma50_pct is not None:
        lines.append(f"📌 מרחק מהממוצע הנע 50 יום: {_signed(analysis.dist_from_ma50_pct, 1, '%')}")

    lines.append(f"📌 {analysis.reason_text.split(' | ')[0]}")

    # שלושה ציונים נפרדים, כל אחד עונה על שאלה אחרת - לא ציון אחד מעורבב:
    # (1) האם זו בכלל תגובת יתר טכנית, (2) האם החברה מאחורי הירידה בריאה
    # פונדמנטלית, (3) ההמלצה הסופית - שילוב של שניהם (מחושבת ב-_classify_rebound,
    # לא כאן - כאן רק מציגים את שלושתם בנפרד במקום שורה אחת ממוזגת).
    # אייקון רמזור (🟢/🟡/🔴) לכל אחד משלושת הציונים - אותם ספי 70/45 שכבר
    # קובעים את ה-verdict המילולי ב-_score_overreaction, רק כצבע במקום מילים.
    if analysis.overreaction_score >= 70:
        _score1_light = "🟢"
    elif analysis.overreaction_score >= 45:
        _score1_light = "🟡"
    else:
        _score1_light = "🔴"
    lines.append(f"1️⃣ {_score1_light} ציון תגובת יתר: {analysis.overreaction_score}/{analysis_mod.MAX_OVERREACTION_SCORE}")

    _quality_light = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
        analysis.quality.tier if analysis.quality else None, "⚪"
    )
    if analysis.quality and analysis.quality.tier != "unknown":
        q = analysis.quality
        flags_part = f" - {q.flags[0]}" if q.flags else ""
        lines.append(f"2️⃣ {_quality_light} איכות פונדמנטלית: {q.tier_label} ({q.score}/100){flags_part}")
    else:
        lines.append(f"2️⃣ {_quality_light} איכות פונדמנטלית: לא ידוע (נתונים חסרים)")

    _rebound_emoji = analysis.rebound_label.split(" ", 1)[0]  # כבר 🟢/🟡/🔴 לפי A/B/C, ר' _classify_rebound
    lines.append(f"3️⃣ {_rebound_emoji} המלצת מסחר: סיווג {analysis.rebound_tier}")

    _liquidity_emoji = {"high": "💧", "medium": "🌊", "low": "🏜️", "unknown": "⚪"}
    if trade_idea.liquidity_tier in ("medium", "low"):
        lines.append(f"{_liquidity_emoji.get(trade_idea.liquidity_tier, '⚪')} {trade_idea.liquidity_note}")

    if analysis.has_headlines:
        links = ", ".join(
            f'<a href="{h["link"]}">{h.get("source", "חדשות")}</a>' if h.get("link") else h.get("source", "חדשות")
            for h in analysis.headlines[:3]
        )
        lines.append(f"📰 {len(analysis.headlines)} כתבות רלוונטיות: {links}")
    else:
        lines.append("📰 לא נמצאו חדשות רלוונטיות")

    target_gross_pct = (trade_idea.target_base / trade_idea.entry_limit - 1) * 100
    stop_gross_pct = (trade_idea.stop_loss / trade_idea.entry_limit - 1) * 100

    lines += [
        "",
        "🎯 <b>תרחיש עסקה</b>",
        f"כניסה (לימיט): {_format_price(trade_idea.entry_limit, currency, with_unit=False)}  |  "
        f"שינוי יומי: {_signed(row['pct_change'], 1, '%')}",
        f"יעד: {_format_price(trade_idea.target_base, currency, with_unit=False)}  ({_signed(target_gross_pct, 1, '%')})",
        f"סטופ: {_format_price(trade_idea.stop_loss, currency, with_unit=False)}  ({_signed(stop_gross_pct, 1, '%')})",
    ]
    if stop_gross_pct:
        lines.append(f"יחס סיכוי/סיכון: 1:{abs(target_gross_pct / stop_gross_pct):.1f}")
    lines += [
        f"אחזקה משוערת: {net_profit.holding_days} ימים",
        "",
        "💰 <b>נטו</b>",
        f"השקעה: {position_size:,.0f} {ccy}  ({net_profit.qty:.0f} מניות)",
        f"רווח ביעד: {_signed(net_profit.net_pnl)} {ccy}",
        f"הפסד בסטופ: {_signed(net_loss.net_pnl)} {ccy}",
    ]
    return "\n".join(lines)
