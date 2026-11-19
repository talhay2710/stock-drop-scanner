"""זיהוי ירידות נפרד לכל בודק: אותם נתוני שוק שהסריקה שלך כבר שלפה (פעם אחת), אבל הסף, המדדים והסינון הם של הבודק עצמו.
שום דבר כאן לא נוגע בהתראות, במסד או בטלגרם שלך. המצב של כל בודק (מי כבר קיבל התראה, מי באזור אזהרה) נשמר ב-data/<id>/scan_state.json
בריפו הפרטי (הכותב היחיד שלו הוא הסורק). כל פונקציה לא זורקת החוצה: כשל בבודק אחד לא עוצר את האחרים ולא את הסריקה."""
import datetime as dt
import logging

import pandas as pd

from . import tester_telegram, user_sync

logger = logging.getLogger(__name__)

MIN_THRESHOLD_PCT = 0.5      # כמו המינימום בסיידבר; סף 0 היה מציף
MAX_SENDS_PER_TESTER = 15    # לכל ריצה, הגנה מהצפה
KEEP_SENT_DAYS = 5


def _state_path(uid: str) -> str:
    return f"data/{uid}/scan_state.json"


class Tester:
    def __init__(self, uid: str, chat_id, prefs: dict):
        self.uid, self.chat_id, self.prefs = uid, chat_id, prefs
        self._state = None
        self._sha = None
        self.dirty = False

    @property
    def state(self) -> dict:
        """נטען בעצלתיים (רק כשיש מדד פתוח לבודק), פעם אחת לריצה."""
        if self._state is None:
            try:
                raw, self._sha = user_sync.read_json(_state_path(self.uid), {})
            except Exception as e:
                logger.warning("קריאת מצב סריקה של בודק %s נכשלה (%s)", self.uid, type(e).__name__)
                raw, self._sha = {}, None
            self._state = raw if isinstance(raw, dict) else {}
            self._state.setdefault("init", [])
            self._state.setdefault("sent", {})
            self._state.setdefault("watch", {"date": None, "items": {}})
        return self._state


class Plan:
    """בודקים מחוברים שמקבלים התראות ירידה (טלגרם דלוק ושם סוג ההודעה פעיל), ואילו מדדים הם רוצים."""

    def __init__(self, testers: list[Tester]):
        self.testers = testers

    def indices(self) -> set[str]:
        return {i for t in self.testers for i in t.prefs.get("indices", [])}

    def for_index(self, index: str) -> list[Tester]:
        return [t for t in self.testers if index in t.prefs.get("indices", [])]


def build_plan(cfg: dict) -> Plan | None:
    """None = אין למי לשלוח (או מחוץ לענן / בלי הגדרת ריפו). לא זורק."""
    try:
        if not tester_telegram._token(cfg) or not user_sync.configured():
            return None
        testers = []
        for uid, rec in dict(tester_telegram.recipients(cfg)).items():
            p = rec["prefs"]
            if p.get("enabled", True) and p.get("drop_alert", True) and p.get("indices"):
                testers.append(Tester(uid, rec["chat_id"], p))
        return Plan(testers) if testers else None
    except Exception as e:
        logger.warning("בניית תכנית זיהוי לבודקים נכשלה (%s)", type(e).__name__)
        return None


def save_all(plan: Plan | None) -> None:
    if not plan:
        return
    for t in plan.testers:
        if t._state is None or not t.dirty:
            continue
        try:
            user_sync.write_json(_state_path(t.uid), t._state, t._sha, f"scan state: {t.uid}")
        except user_sync.Conflict:
            logger.warning("שמירת מצב סריקה של %s התנגשה - ננסה בסבב הבא", t.uid)
        except Exception as e:
            logger.warning("שמירת מצב סריקה של %s נכשלה (%s)", t.uid, type(e).__name__)


def _thr(prefs: dict, key: str) -> float:
    return max(MIN_THRESHOLD_PCT, float(prefs.get(key) or 0.0))


def flag(df: pd.DataFrame, prefs: dict, state: dict, index: str, scan_date: str,
         watch_buffer: float = 1.0, baseline: bool = False) -> tuple[pd.DataFrame, bool]:
    """השורות שחצו את הסף של הבודק: ירידה יומית (אחרי אימות: נצפתה באזור האזהרה גם בסריקה קודמת) או מצטברת.
    מעדכן את אזור האזהרה ב-state. baseline=True (הרצה ראשונה למדד אצל הבודק): הכול נחשב מאומת, כדי שהקורא ירשום בשקט את מה שכבר ירד.
    מחזיר (עותק עם is_multi_day_only ו-severity, האם אזור האזהרה השתנה - כלומר צריך לשמור את המצב)."""
    watch = state["watch"]
    changed = False
    if watch.get("date") != scan_date:
        watch["date"], watch["items"] = scan_date, {}
        changed = True
    items = watch["items"]
    prefix = f"{index}:"
    before = {k for k in items if k.startswith(prefix)}

    false = pd.Series(False, index=df.index)
    thin = df["thin_print"].fillna(False).astype(bool) if "thin_print" in df.columns else false
    gapped = df["prev_close_gap"].fillna(False).astype(bool) if "prev_close_gap" in df.columns else false
    n_day = df["n_day_change"] if "n_day_change" in df.columns else pd.Series(float("nan"), index=df.index)

    thr, multi_thr = _thr(prefs, "min_drop_pct"), _thr(prefs, "min_multi_pct")
    in_zone = (df["pct_change"] <= -max(thr - abs(watch_buffer), 0.0)) & ~thin
    confirmed = false.copy()
    new_items = {}
    for idx in df[in_zone].index:
        key = f"{index}:{df.loc[idx, 'ticker']}"
        if baseline or key in items:
            confirmed.loc[idx] = True
        new_items[key] = float(df.loc[idx, "pct_change"])
    for key in before:
        items.pop(key)  # אזור האזהרה הוא "מי נראה בסבב האחרון", לא היסטוריה
    items.update(new_items)
    changed = changed or before != set(new_items)

    single = (df["pct_change"] <= -thr) & confirmed & ~gapped
    multi_on = bool(prefs.get("multi_day", True))
    gap_multi = gapped & (df["pct_change"] <= -multi_thr) if multi_on else false
    multi = ((n_day <= -multi_thr) | gap_multi) if multi_on else false
    out = df[(single | multi) & ~thin].copy()
    out["is_multi_day_only"] = (multi & ~single)[out.index]
    out["severity"] = out[["pct_change", "n_day_change"]].min(axis=1) if "n_day_change" in out.columns else out["pct_change"]
    return out.sort_values("severity"), changed


def sent_key(index: str, ticker: str) -> str:
    return f"{index}:{ticker}"


def already_sent(state: dict, index: str, ticker: str, close_date) -> bool:
    """אותה ירידה (אותו תאריך נתון) נשלחת לבודק פעם אחת בלבד."""
    got = state["sent"].get(sent_key(index, ticker))
    return got is not None and got == (close_date.isoformat() if hasattr(close_date, "isoformat") else str(close_date))


def mark_sent(t: Tester, index: str, ticker: str, close_date) -> None:
    t.state["sent"][sent_key(index, ticker)] = close_date.isoformat() if hasattr(close_date, "isoformat") else str(close_date)
    t.dirty = True


def prune(t: Tester, today: dt.date) -> None:
    keep = (today - dt.timedelta(days=KEEP_SENT_DAYS)).isoformat()
    sent = t.state["sent"]
    for k in [k for k, v in sent.items() if str(v) < keep]:
        del sent[k]
        t.dirty = True


def needs_baseline(t: Tester, index: str) -> bool:
    return index not in t.state["init"]


def finish_baseline(t: Tester, index: str) -> None:
    if index not in t.state["init"]:
        t.state["init"].append(index)
    t.dirty = True
