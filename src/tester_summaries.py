"""סיכומי טלגרם לבודקים: תמונת מצב בוקר, סיכום יומי ודוח שבועי - באותם חלונות זמן ובאותם בוני טקסט כמו אצל הבעלים
(daily_summary / weekly_report), רק עם האחזקות והמכירות של הבודק עצמו (נקראים מ-user.db שלו בריפו הפרטי).
"נשלח היום" נשמר ב-data/<id>/state.json (הכותב היחיד שלו הוא הסורק), כך שכל בודק מקבל כל סיכום פעם אחת ביום, ושליחה שנכשלה תנסה שוב.
רץ כצעד נפרד ב-scan.yml (run_tester_summaries.py) - בלי קשר לסיכומים שלך, כך ששום דבר כאן לא משפיע עליהם. לא זורק."""
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from . import schedule_guard, tester_holdings, tester_telegram, user_sync

logger = logging.getLogger(__name__)

# סוג -> (מפתח ההעדפה, חלון זמן (שעת התחלה, דקה, שעת סיום, דקה) לפי שעון ישראל, ימים)
KINDS = {
    "morning": ("morning_summary", (10, 30, 10, 45), schedule_guard.TRADING_WEEKDAYS),
    "daily": ("daily_summary", (18, 0, 18, 15), schedule_guard.TRADING_WEEKDAYS),
    "weekly": ("weekly_report", (15, 0, 15, 15), 6),  # ראשון
}


def _today() -> str:
    return dt.datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


def run(cfg: dict, conn, in_window=None, today: str | None = None) -> int:
    """שולח לבודקים המחוברים את הסיכומים שהגיע זמנם והם ביקשו. מחזיר כמה הודעות נשלחו."""
    in_window = in_window or schedule_guard.in_window
    today = today or _today()
    due = [k for k, (_p, win, wd) in KINDS.items() if in_window(*win, weekday=wd)]
    if not due or not user_sync.configured() or not tester_telegram._token(cfg):
        return 0
    cache: dict = {}
    sent = 0
    for uid, rec in dict(tester_telegram.recipients(cfg)).items():
        kinds = [k for k in due if rec["prefs"].get(KINDS[k][0])]
        if not kinds or not rec["prefs"].get("enabled", True):
            continue
        try:
            sent += _run_one(tester_holdings.with_overrides(cfg, rec["prefs"]), conn, uid, rec["chat_id"], kinds, today, cache)
        except Exception as e:
            logger.warning("סיכומים לבודק %s נכשלו (%s)", uid, type(e).__name__)
    return sent


def _holdings_for(conn, positions: list[dict]) -> list[dict]:
    """אחזקות הבודק בצורה ש-build_holdings_summary מצפה לה (כמו get_bought_holdings): הטיקר/שם/מדד מטבלת ההתראות."""
    if not positions:
        return []
    marks = ",".join("?" * len(positions))
    info = {r[0]: r for r in conn.execute(
        f"SELECT id, ticker, company_name, index_name FROM alerts WHERE id IN ({marks})", [p["alert_id"] for p in positions]).fetchall()}
    out = []
    for p in positions:
        row = info.get(p["alert_id"])
        if row:
            out.append({"id": p["alert_id"], "ticker": row[1], "company_name": row[2], "index_name": row[3],
                        "actual_entry_price": p["entry_price"], "actual_qty": p["qty"], "bought_at": p["bought_at"]})
    return out


def _morning_inputs(cfg: dict, cache: dict):
    if "morning" not in cache:
        import run_morning_summary as rms  # שתי פונקציות העזר שכבר קיימות אצל הבעלים (מדדים + בולטות)
        cache["morning"] = (rms._build_index_changes(cfg), rms._build_movers_by_index(cfg))
    return cache["morning"]


def _run_one(cfg: dict, conn, uid: str, chat_id, kinds: list, today: str, cache: dict) -> int:
    from .daily_summary import build_daily_summary, build_morning_summary
    from .holdings_summary import build_holdings_summary, enrich_closed_today_with_today_pnl
    from .weekly_report import build_weekly_report

    state, sha = tester_holdings.read_state(uid)
    done = dict(state.get("summaries", {}))
    todo = [k for k in kinds if done.get(k) != today]
    if not todo:
        return 0
    got = user_sync.backend().get(user_sync.remote_db_path(uid))
    data = tester_holdings.read_user_db(got[0], closed_on=today) if got else {"positions": [], "closed_today": []}
    holdings = _holdings_for(conn, data["positions"])
    sent = 0
    for kind in todo:
        if kind == "weekly":
            if "weekly" not in cache:
                cache["weekly"] = build_weekly_report(conn)
            message = cache["weekly"]
        elif kind == "morning":
            index_changes, movers = _morning_inputs(cfg, cache)
            message = build_morning_summary(today, index_changes, build_holdings_summary(conn, cfg, holdings), movers)
        else:
            closed = enrich_closed_today_with_today_pnl(list(data["closed_today"]))
            message = build_daily_summary(conn, today, build_holdings_summary(conn, cfg, holdings), closed_today=closed)
        if not message:
            done[kind] = today  # אין מה לדווח היום - לא מחשבים שוב בכל סריקה בתוך החלון
        elif tester_telegram.send_to(cfg, chat_id, message):
            done[kind] = today
            sent += 1
    if done != state.get("summaries", {}):
        state["summaries"] = done
        tester_holdings.save_state(uid, state, sha)
    return sent
