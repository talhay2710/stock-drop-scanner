"""התראות אחזקות לבודקים: אותם ארבעה סוגי התראה שיש לבעלים (קרוב/חצה סטופ, קרוב/הגיע ליעד, עלייה מהכניסה, החזקה מעל 3 ימי מסחר),
על האחזקות שהבודק הזין באתר שלו. הסורק קורא את user.db של כל בודק מהריפו הפרטי (קריאה בלבד - הכותב היחיד שלו הוא האתר של הבודק),
בודק מחירים חיים, ושומר את מצב ההתראות (כדי לא לחזור על אותה התראה) ב-data/<id>/state.json (הכותב היחיד שלו הוא הסורק).
הלוגיקה והטקסטים זהים לאלה של הבעלים ב-scanner.py; הקוד נפרד בכוונה - שום שינוי כאן לא נוגע בהתראות שלך.
כל פונקציה לא זורקת: כשל בבודק אחד לא עוצר את האחרים ולא את הסריקה."""
import datetime as dt
import logging
import os
import sqlite3
import tempfile

from . import constituents, fees as fees_mod, market_data, strategy as strategy_mod, tester_telegram, user_sync
from .market_hours import is_market_open, israel_today

logger = logging.getLogger(__name__)

HOLDING_TYPES = ("holdings_stop", "holdings_target", "holdings_gain", "holdings_hold_limit", "price_alert")


def _state_path(uid: str) -> str:
    return f"data/{uid}/state.json"


def _rows(c, sql: str, params=()) -> list[dict]:
    try:
        cur = c.execute(sql, params)
    except sqlite3.Error:
        return []  # טבלה שעוד לא נוצרה אצל הבודק = אין נתונים
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def read_user_db(db_bytes: bytes, closed_on: str | None = None) -> dict:
    """קריאה בלבד של user.db של בודק: positions, price_alerts פעילות, ועסקאות שנסגרו ביום closed_on (אם ביקשו)."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(db_bytes)
        c = sqlite3.connect(tmp)
        try:
            return {
                "positions": _rows(c, "SELECT alert_id, entry_price, qty, bought_at, stop_price, is_manual FROM positions ORDER BY alert_id"),
                "price_alerts": _rows(c, "SELECT id, ticker, company_name, index_name, target_price, direction FROM price_alerts "
                                         "WHERE cancelled = 0 ORDER BY id"),
                "closed_today": _rows(c, "SELECT * FROM closed_trades WHERE substr(exit_at, 1, 10) = ? ORDER BY exit_at DESC", (closed_on,))
                if closed_on else [],
            }
        finally:
            c.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def read_state(uid: str):
    return user_sync.read_json(_state_path(uid), {})


def save_state(uid: str, state: dict, sha) -> None:
    try:
        user_sync.write_json(_state_path(uid), state, sha, f"state: {uid}")
    except user_sync.Conflict:
        logger.warning("שמירת מצב ההתראות של %s התנגשה - ננסה בסבב הבא", uid)


def with_fees(cfg: dict, fees: dict | None) -> dict:
    """עותק של cfg עם העמלות/מיסים של הבודק (ממוזגים מעל שלך) - לחישוב הרווח נטו בהודעות שלו."""
    if not fees:
        return cfg
    merged = {c: dict(v) for c, v in (cfg.get("fees") or {}).items()}
    for country, vals in fees.items():
        merged.setdefault(country, {}).update(vals)
    return {**cfg, "fees": merged}


def with_overrides(cfg: dict, prefs: dict) -> dict:
    """cfg של הבודק: העמלות והמיסים שלו, ואחוזי ההתראה על אחזקות שקבע בסיידבר ("מעקב אחזקות"), מעל ברירות המחדל שלך."""
    out = with_fees(cfg, prefs.get("fees"))
    thresholds = prefs.get("holdings_thresholds")
    return {**out, **thresholds} if thresholds else out


def check_testers(cfg: dict, conn) -> int:
    """בודק אחזקות של כל הבודקים המחוברים. conn = חיבור למסד הסריקה (alerts.db: שם הטיקר/המדד/היעד של כל התראה). מחזיר כמה הודעות נשלחו."""
    token = tester_telegram._token(cfg)
    if not token or not user_sync.configured():
        return 0
    sent = 0
    for uid, rec in dict(tester_telegram.recipients(cfg)).items():
        if not rec["prefs"].get("enabled", True):
            continue
        types = {t for t in HOLDING_TYPES if rec["prefs"].get(t, True)}
        if not types:
            continue
        try:
            sent += check_one(with_overrides(cfg, rec["prefs"]), conn, uid, rec["chat_id"], types)
        except Exception as e:
            logger.warning("בדיקת אחזקות של בודק %s נכשלה (%s)", uid, type(e).__name__)
    return sent


def check_one(cfg: dict, conn, uid: str, chat_id, types: set) -> int:
    from . import scanner as sc  # בזמן ריצה: scanner מייבא אותנו, אז לא ברמת המודול

    got = user_sync.backend().get(user_sync.remote_db_path(uid))
    if got is None:
        return 0
    data = read_user_db(got[0])
    positions, price_alerts = data["positions"], data["price_alerts"]
    state, state_sha = read_state(uid)
    keep = {str(p["alert_id"]) for p in positions} | {"summaries", "price_alerts_triggered"}
    new_state = {k: v for k, v in state.items() if k in keep}  # אחזקה שנסגרה - המצב שלה נמחק
    sent = 0
    if "price_alert" in types and price_alerts:
        sent += _check_price_alerts(cfg, uid, chat_id, price_alerts, new_state)
    if not positions:
        if new_state != state:
            save_state(uid, new_state, state_sha)
        return sent

    marks = ",".join("?" * len(positions))
    info = {r[0]: r for r in conn.execute(
        f"SELECT id, ticker, company_name, index_name, target_base FROM alerts WHERE id IN ({marks})",
        [p["alert_id"] for p in positions]).fetchall()}
    prices = {}
    for t in {info[p["alert_id"]][1] for p in positions if p["alert_id"] in info}:
        prices[t] = market_data.fetch_current_price(t)

    types = types - {"price_alert"}
    start_pct = abs(cfg.get("holdings_gain_alert_start_pct", 2.0))
    step_pct = abs(cfg.get("holdings_gain_alert_step_pct", 1.0)) or 1.0
    stop_warn = abs(cfg.get("holdings_stop_warn_pct", sc.STOP_WARN_PCT))
    target_warn = abs(cfg.get("holdings_target_warn_pct", sc.TARGET_WARN_PCT))

    for p in positions:
        row = info.get(p["alert_id"])
        if row is None:
            continue
        _, ticker, company, index_name, target_base = row
        current, entry, qty = prices.get(ticker), p["entry_price"], p["qty"]
        if index_name and not is_market_open(index_name):
            continue
        if current is None or not entry:
            continue
        key = str(p["alert_id"])
        st = dict(new_state.get(key, {}))
        name = company or ticker
        ccy = constituents.INDEX_CURRENCY.get(index_name, "ILS")
        country = constituents.INDEX_COUNTRY_CODE.get(index_name, "IL")
        stop_price = p.get("stop_price") or (entry * sc.STOP_LOSS_FACTOR)

        def send(text: str) -> bool:
            return tester_telegram.send_to(cfg, chat_id, text)

        bought_dt = None
        if p.get("bought_at"):
            try:
                bought_dt = dt.datetime.fromisoformat(p["bought_at"])
            except Exception:
                pass

        # עלייה מהכניסה
        if "holdings_gain" in types:
            gain_pct = (current / entry - 1) * 100
            level = sc._gain_level(gain_pct, start_pct, step_pct)
            last = st.get("last_gain_alert_pct")
            last_level = sc._gain_level(last, start_pct, step_pct) if last is not None else None
            if level is not None and (last_level is None or level > last_level):
                days = max((israel_today() - bought_dt.date()).days, 1) if bought_dt is not None else 1
                net = fees_mod.compute_net_result(country_code=country, buy_price=entry, sell_price=current,
                                                  position_size_ccy=entry * (qty or 0), holding_days=days, fees_cfg=cfg["fees"])
                sym = sc.CURRENCY_DISPLAY.get(ccy, ccy)
                if send("\n".join([
                    f"📈 <b>{name} עלתה {sc._signed(gain_pct, 1, '%')} מהכניסה שלך</b>", f"{ticker}", "",
                    "💡 <b>מחירים</b>",
                    f"כניסה: {sc._format_price(entry, ccy, with_unit=False)}  |  נוכחי: {sc._format_price(current, ccy, with_unit=False)}",
                    f"מספר מניות: {qty:,.0f}", "", "💰 <b>נטו</b>",
                    f"רווח נטו: {sc._signed(net.net_pnl)} {sym}  ({sc._signed(net.net_return_pct, 1, '%')})",
                ])):
                    st["last_gain_alert_pct"] = gain_pct
                    sent += 1

        # סטופ
        if "holdings_stop" in types:
            dist = strategy_mod.stop_distance_pct(current, stop_price)
            active = bool(st.get("stop_alert_active"))
            if dist > stop_warn:
                if active and dist > stop_warn * 2:
                    st["stop_alert_active"] = False
            elif not active:
                title = f"🛑 <b>{name} חצתה את הסטופ שלך</b>" if current <= stop_price else f"🛑 <b>{name} מתקרבת לסטופ שלך</b>"
                if send("\n".join([title, f"{ticker}", "", f"מחיר נוכחי: {sc._format_price(current, ccy, with_unit=False)}",
                                   f"<b>הסטופ שלך: {sc._format_price(stop_price, ccy, with_unit=False)}</b>",
                                   f"נכנסת ב-{sc._format_price(entry, ccy, with_unit=False)}"])):
                    st["stop_alert_active"] = True
                    sent += 1

        # יעד
        if "holdings_target" in types:
            target_price = strategy_mod.live_target_price(entry, stop_price, target_base)
            dist = strategy_mod.target_distance_pct(current, target_price)
            active = bool(st.get("target_alert_active"))
            if dist > target_warn:
                if active and dist > target_warn * 2:
                    st["target_alert_active"] = False
            elif not active:
                title = f"🎯 <b>{name} הגיעה ליעד שלך!</b>" if current >= target_price else f"🎯 <b>{name} מתקרבת ליעד שלך</b>"
                if send("\n".join([title, f"{ticker}", "", f"מחיר נוכחי: {sc._format_price(current, ccy, with_unit=False)}",
                                   f"<b>היעד שלך: {sc._format_price(target_price, ccy, with_unit=False)}</b>",
                                   f"נכנסת ב-{sc._format_price(entry, ccy, with_unit=False)}"])):
                    st["target_alert_active"] = True
                    sent += 1

        # החזקה מעל אופק האסטרטגיה (לא לאחזקה ידנית)
        if "holdings_hold_limit" in types and not st.get("hold_alert_sent") and not p.get("is_manual") and p.get("bought_at"):
            days_held = sc.trading_days_held(p["bought_at"], country)
            if days_held > strategy_mod.HOLD_MAX_DAYS:
                pnl = (current / entry - 1) * 100
                if send("\n".join([
                    f"⏰ <b>{name} מוחזקת {days_held} ימי מסחר</b>", f"{ticker}", "",
                    f"האסטרטגיה נבדקה על החזקה של עד {strategy_mod.HOLD_MAX_DAYS} ימי מסחר.",
                    f"מחיר נוכחי: {sc._format_price(current, ccy, with_unit=False)} ({sc._signed(pnl, 1, '%')} מהכניסה)",
                    f"נכנסת ב-{sc._format_price(entry, ccy, with_unit=False)}",
                ])):
                    st["hold_alert_sent"] = True
                    sent += 1

        if st:
            new_state[key] = st

    if new_state != state:
        save_state(uid, new_state, state_sha)
    return sent


def _check_price_alerts(cfg: dict, uid: str, chat_id, alerts: list[dict], new_state: dict) -> int:
    """התראות מחיר ידניות של הבודק: חד-פעמיות. מזהה שהופעלה נשמר ב-state (המסד של הבודק נכתב רק ע"י האתר שלו)."""
    from . import scanner as sc

    done = set(new_state.get("price_alerts_triggered", []))
    todo = [a for a in alerts if a["id"] not in done]
    if not todo:
        return 0
    prices = {t: market_data.fetch_current_price(t) for t in {a["ticker"] for a in todo}}
    sent = 0
    for a in todo:
        current = prices.get(a["ticker"])
        if current is None:
            continue
        target = a["target_price"]
        crossed = (current >= target) if a["direction"] == "above" else (current <= target)
        if not crossed:
            continue
        name = a["company_name"] or a["ticker"]
        ccy = constituents.INDEX_CURRENCY.get(a.get("index_name"), "ILS")
        word = "מעל" if a["direction"] == "above" else "מתחת ל"
        text = "\n".join([
            f"🔔 <b>{name} הגיעה ל{word}-{sc._format_price(target, ccy, with_unit=False)}</b>", f"{a['ticker']}", "",
            f"מחיר נוכחי: {sc._format_price(current, ccy, with_unit=False)}",
            f"מחיר יעד שקבעת: {sc._format_price(target, ccy, with_unit=False)}",
        ])
        if tester_telegram.send_to(cfg, chat_id, text):
            done.add(a["id"])
            sent += 1
    new_state["price_alerts_triggered"] = sorted(done)
    return sent
