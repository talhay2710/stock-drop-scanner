"""משתמשי בודק אמיתיים: זהות (קוד גישה) ואחסון עמיד של user.db של כל בודק בריפו גיטהאב *פרטי*.

למה: שרת Streamlit Cloud מתאפס מדי פעם ומוחק כל קובץ מקומי; הריפו הציבורי של הפרויקט לא יכול להחזיק נתונים אישיים.
המבנה בריפו הפרטי (USERS_REPO, בפורמט owner/name; גישה עם USERS_REPO_TOKEN - טוקן fine-grained עם Contents: read/write לריפו הזה בלבד):
  users.json                 - רישום המשתמשים (נכתב רק ע"י manage_testers.py של הבעלים): {"users": {id: {name, salt, code_hash, link_token}}}
  telegram_links.json        - חיבורי טלגרם (נכתב רק ע"י הסורק בענן): {"last_update_id": n, "chats": {id: chat_id}}
  data/<id>/user.db          - נתוני הבודק (נכתב רק ע"י האתר של אותו בודק)
לכל קובץ כותב יחיד, כמו בפיצול ה-DB של הבעלים. אין כאן שום תלות ב-Streamlit (ניתן לבדיקה ובשימוש מהסורק).
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

API = "https://api.github.com"
_PBKDF2_ROUNDS = 200_000
PUSH_INTERVAL_SEC = 15
_THREAD_VERSION = 2  # להעלות בכל שינוי בלוגיקת הדחיפה (ר' start_background_push)


class Conflict(Exception):
    """הקובץ בריפו השתנה מאז שקראנו אותו (sha לא תואם)."""


# --------------------------------------------------------------------------- backend

class GitHubBackend:
    """GET/PUT של קובץ בודד דרך Contents API. get -> (bytes, sha) או None; put -> sha חדש (Conflict אם ה-sha לא עדכני)."""

    def __init__(self, repo: str, token: str, branch: str = "main"):
        self.repo, self.token, self.branch = repo, token, branch

    def _h(self, accept: str = "application/vnd.github+json") -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}

    def get(self, path: str):
        import requests
        url = f"{API}/repos/{self.repo}/contents/{path}"
        r = requests.get(url, headers=self._h(), params={"ref": self.branch}, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        meta = r.json()
        content = meta.get("content") or ""
        if content:
            return base64.b64decode(content), meta["sha"]
        raw = requests.get(url, headers=self._h("application/vnd.github.raw+json"), params={"ref": self.branch}, timeout=30)
        raw.raise_for_status()
        return raw.content, meta["sha"]

    def list(self, prefix: str) -> list:
        """קבצי תיקייה אחת: [(path, sha)]. תיקייה שלא קיימת = רשימה ריקה."""
        import requests
        r = requests.get(f"{API}/repos/{self.repo}/contents/{prefix}", headers=self._h(), params={"ref": self.branch}, timeout=20)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        items = r.json()
        return [(i["path"], i["sha"]) for i in items if i.get("type") == "file"] if isinstance(items, list) else []

    def delete(self, path: str, sha: str, message: str) -> None:
        import requests
        r = requests.delete(f"{API}/repos/{self.repo}/contents/{path}", headers=self._h(),
                            json={"message": message, "sha": sha, "branch": self.branch}, timeout=30)
        if r.status_code not in (200, 404):
            r.raise_for_status()

    def put(self, path: str, data: bytes, sha: str | None, message: str) -> str:
        import requests
        body = {"message": message, "content": base64.b64encode(data).decode(), "branch": self.branch}
        if sha:
            body["sha"] = sha
        r = requests.put(f"{API}/repos/{self.repo}/contents/{path}", headers=self._h(), json=body, timeout=30)
        if r.status_code in (409, 422):
            raise Conflict(path)
        r.raise_for_status()
        return r.json()["content"]["sha"]


class MemoryBackend:
    """לבדיקות: אותה ממשק, בזיכרון."""

    def __init__(self):
        self.files: dict[str, tuple[bytes, str]] = {}
        self._n = 0

    def get(self, path):
        return self.files.get(path)

    def list(self, prefix):
        return [(p, v[1]) for p, v in self.files.items() if p.startswith(prefix.rstrip("/") + "/")]

    def delete(self, path, sha, message):
        self.files.pop(path, None)

    def put(self, path, data, sha, message):
        cur = self.files.get(path)
        if (cur[1] if cur else None) != sha:
            raise Conflict(path)
        self._n += 1
        new = f"sha{self._n}"
        self.files[path] = (bytes(data), new)
        return new


_backend_override = None


def configured() -> bool:
    return bool(_backend_override or (os.environ.get("USERS_REPO") and os.environ.get("USERS_REPO_TOKEN")))


def backend():
    if _backend_override is not None:
        return _backend_override
    repo, token = os.environ.get("USERS_REPO", ""), os.environ.get("USERS_REPO_TOKEN", "")
    if not repo or not token:
        raise RuntimeError("USERS_REPO / USERS_REPO_TOKEN לא מוגדרים")
    return GitHubBackend(repo, token, os.environ.get("USERS_REPO_BRANCH", "main"))


# --------------------------------------------------------------------------- json files + registry

def read_json(path: str, default):
    got = backend().get(path)
    if got is None:
        return default, None
    return json.loads(got[0].decode("utf-8")), got[1]


def write_json(path: str, obj, sha, message: str) -> str:
    return backend().put(path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"), sha, message)


def update_json(path: str, mutate, message: str, default=None, retries: int = 3):
    """קריאה-שינוי-כתיבה עם ניסיון חוזר בהתנגשות. mutate(obj) -> obj חדש."""
    for _ in range(retries):
        obj, sha = read_json(path, {} if default is None else default)
        try:
            write_json(path, mutate(obj), sha, message)
            return
        except Conflict:
            continue
    raise Conflict(path)


def _hash_code(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.strip().encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS).hex()


def new_user_record(name: str) -> tuple[dict, str]:
    """רשומת משתמש חדשה + קוד הגישה בטקסט גלוי (מוצג לבעלים פעם אחת, לא נשמר)."""
    code = "-".join(secrets.token_hex(2) for _ in range(3))  # xxxx-xxxx-xxxx
    salt = secrets.token_hex(16)
    return {"name": name, "salt": salt, "code_hash": _hash_code(code, salt), "link_token": secrets.token_hex(8)}, code


def verify_code(user_id: str, code: str) -> bool:
    users, _ = read_json("users.json", {"users": {}})
    rec = users.get("users", {}).get(user_id)
    if not rec or not code or not code.strip():
        return False
    return hmac.compare_digest(_hash_code(code, rec["salt"]), rec["code_hash"])


# --------------------------------------------------------------------------- כניסה בקוד, והסרת משתמש

_LOGIN_MAX_FAILS = 8
_LOGIN_WINDOW_SEC = 600
_login_fails = getattr(sys, "_dipradar_login_fails", None)
if _login_fails is None:
    _login_fails = sys._dipradar_login_fails = {}


def attempt_login(user_id: str, code: str, now: float | None = None) -> str:
    """'ok' / 'bad' / 'locked'. אחרי 8 ניסיונות כושלים ב-10 דקות הכניסה של המשתמש הזה ננעלת (הגנה מניחושי קוד)."""
    now = time.time() if now is None else now
    fails = [t for t in _login_fails.get(user_id, []) if now - t < _LOGIN_WINDOW_SEC]
    _login_fails[user_id] = fails
    if len(fails) >= _LOGIN_MAX_FAILS:
        return "locked"
    if verify_code(user_id, code):
        _login_fails[user_id] = []
        return "ok"
    fails.append(now)
    return "bad"


def remove_user(user_id: str) -> dict:
    """מסיר בודק: הרשומה ב-users.json, החיבור בטלגרם, וכל הקבצים שלו (data/<id>/). הגרסאות הישנות נשארות בהיסטוריית git של הריפו
    (מחיקה מלאה = מחיקת הריפו כולו). מחזיר מה נמחק."""
    out = {"user": False, "telegram": False, "files": []}

    def _drop_user(obj):
        out["user"] = obj.get("users", {}).pop(user_id, None) is not None
        return obj

    def _drop_chat(obj):
        out["telegram"] = obj.get("chats", {}).pop(user_id, None) is not None
        return obj

    update_json("users.json", _drop_user, f"remove tester {user_id}", default={"users": {}})
    update_json("telegram_links.json", _drop_chat, f"unlink {user_id}", default={"last_update_id": 0, "chats": {}})
    for path, sha in backend().list(f"data/{user_id}"):
        backend().delete(path, sha, f"remove tester {user_id}")
        out["files"].append(path)
    return out


def telegram_status(user_id: str) -> dict:
    """לתצוגה באתר הבודק: {'connected': bool, 'link': קישור חיבור לבוט או ''}."""
    users, _ = read_json("users.json", {"users": {}})
    links, _ = read_json("telegram_links.json", {"chats": {}})
    rec = users.get("users", {}).get(user_id) or {}
    bot = users.get("bot_username", "")
    link = f"https://t.me/{bot}?start={rec['link_token']}" if bot and rec.get("link_token") else ""
    return {"connected": user_id in links.get("chats", {}), "link": link}


# העדפות התראות טלגרם של בודק: data/<id>/prefs.json (נכתב רק ע"י האתר של הבודק, נקרא ע"י הסורק). ברירת מחדל = קנייה בלבד.
PREFS_SIGNALS = ("buy", "wait", "avoid")
PREFS_INDICES = ("TA35", "TA125", "SP500", "NASDAQ100")  # כל המדדים שניתן לבחור; בפועל מגיעות התראות רק מאלה שהסורק בענן סורק
DEFAULT_INDICES = ("TA35", "TA125")
PREFS_DEFAULTS = {"enabled": True, "signals": ["buy"], "indices": list(DEFAULT_INDICES), "min_drop_pct": 0.0,
                  "multi_day": True, "min_multi_pct": 0.0, "reversal": False, "drop_alert": True,
                  "holdings_stop": True, "holdings_target": True, "holdings_gain": True, "holdings_hold_limit": True,
                  "price_alert": True, "morning_summary": False, "daily_summary": False, "weekly_report": False,
                  "fees": None, "holdings_thresholds": None}
THRESHOLD_KEYS = ("holdings_gain_alert_start_pct", "holdings_gain_alert_step_pct", "holdings_stop_warn_pct", "holdings_target_warn_pct")
PREFS_BOOL_KEYS = ("enabled", "multi_day", "reversal", "drop_alert", "holdings_stop", "holdings_target", "holdings_gain",
                   "holdings_hold_limit", "price_alert", "morning_summary", "daily_summary", "weekly_report")
FEE_KEYS = ("commission_pct", "commission_min", "capital_gains_tax_pct", "management_fee_annual_pct")


def _clean_fees(raw):
    """עמלות/מיסים של הבודק (לחישוב הנטו בהודעות שלו): רק שדות מספריים תקינים; מדינה בלי ערכים תקינים נשמטת."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for country in ("IL", "US"):
        rec = raw.get(country)
        if not isinstance(rec, dict):
            continue
        clean = {}
        for key in FEE_KEYS:
            try:
                value = float(rec[key])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= value <= (1000 if key == "commission_min" else 100):
                clean[key] = value
        if clean:
            out[country] = clean
    return out or None


def _clean_thresholds(raw):
    """אחוזי ההתראה על אחזקות שהבודק קבע ב"מעקב אחזקות" (התחלת עלייה, מדרגה, קרבה לסטופ, קרבה ליעד)."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for key in THRESHOLD_KEYS:
        try:
            value = float(raw[key])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 < value <= 100:
            out[key] = value
    return out or None


def clean_prefs(raw) -> dict:
    """מתקן/משלים העדפות (גם מקובץ פגום או ידני) - תמיד מחזיר מבנה תקין."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(PREFS_DEFAULTS)
    if isinstance(raw.get("signals"), list):
        out["signals"] = [s for s in PREFS_SIGNALS if s in raw["signals"]]
    if isinstance(raw.get("indices"), list):
        out["indices"] = [i for i in PREFS_INDICES if i in raw["indices"]]
    for key in ("min_drop_pct", "min_multi_pct"):
        try:
            out[key] = max(0.0, min(50.0, float(raw.get(key, out[key]))))
        except (TypeError, ValueError):
            pass
    for key in PREFS_BOOL_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    out["fees"] = _clean_fees(raw.get("fees"))
    out["holdings_thresholds"] = _clean_thresholds(raw.get("holdings_thresholds"))
    return out


def prefs_from_cfg(cfg: dict, existing: dict | None = None) -> dict:
    """ההעדפות שהסורק מפעיל על הבודק, נגזרות מההגדרות שהוא עצמו קבע בסיידבר (אותו סיידבר כמו של הבעלים). שדות שאין להם
    מקבילה בסיידבר (רמת סיגנל) נשמרים מ-existing."""
    types = cfg.get("telegram_message_types", {}) or {}
    out = dict(existing or {})
    out.update({
        "enabled": bool((cfg.get("telegram") or {}).get("enabled", True)),
        "indices": list(cfg.get("indices") or ([cfg["index"]] if cfg.get("index") else DEFAULT_INDICES)),
        "min_drop_pct": cfg.get("drop_threshold_pct", 0.0),
        "multi_day": bool(cfg.get("multi_day_enabled", True)),
        "min_multi_pct": cfg.get("multi_day_threshold_pct", 0.0),
        "reversal": bool(types.get("reversal_alert", False)),
        "drop_alert": bool(types.get("drop_alert", True)),
        "holdings_stop": bool(types.get("holdings_stop", True)),
        "holdings_target": bool(types.get("holdings_target", True)),
        "holdings_gain": bool(types.get("holdings_gain", True)),
        "holdings_hold_limit": bool(types.get("holdings_hold_limit", True)),
        "price_alert": bool(types.get("price_alert", True)),
        "morning_summary": bool(types.get("morning_summary", False)),
        "daily_summary": bool(types.get("daily_summary", False)),
        "weekly_report": bool(types.get("weekly_report", False)),
        "fees": cfg.get("fees"),
        "holdings_thresholds": {k: cfg[k] for k in THRESHOLD_KEYS if k in cfg},
    })
    return clean_prefs(out)


def read_local_prefs(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return clean_prefs(json.load(f))
    except Exception:
        return clean_prefs({})


def write_local_prefs(path: str, prefs: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean_prefs(prefs), f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def prefs_path(user_id: str) -> str:
    return f"data/{user_id}/prefs.json"


def read_prefs(user_id: str) -> dict:
    raw, _ = read_json(prefs_path(user_id), {})
    return clean_prefs(raw)


def write_prefs(user_id: str, prefs: dict) -> None:
    update_json(prefs_path(user_id), lambda _old: clean_prefs(prefs), f"prefs: {user_id}", default={})


def get_user(user_id: str) -> dict | None:
    users, _ = read_json("users.json", {"users": {}})
    return users.get("users", {}).get(user_id)


# --------------------------------------------------------------------------- user.db pull / push

def remote_db_path(user_id: str) -> str:
    return f"data/{user_id}/user.db"


# המצב חי ב-sys ולא במודול: dashboard.py מוחק את מודולי src בכל דחיפת קוד, ומצב שנאפס היה גורם להורדה חוזרת
# שדורסת שינויים מקומיים שטרם נדחפו.
_state = getattr(sys, "_dipradar_user_sync_state", None)
if _state is None:
    _state = sys._dipradar_user_sync_state = {"sha": None, "pushed_digest": None, "pulled": False, "thread": None}
_lock = getattr(sys, "_dipradar_user_sync_lock", None)
if _lock is None:
    _lock = sys._dipradar_user_sync_lock = threading.Lock()


def _snapshot(path: str) -> bytes:
    """עותק עקבי של קובץ ה-SQLite (backup API - בטוח גם כשחיבור אחר כותב באותו רגע)."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src, dst = sqlite3.connect(path), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _logical_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _remote_file(user_id: str, name: str) -> str:
    return f"data/{user_id}/{name}"


def _write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".pull"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _register_late_extras(user_id: str, extras: dict) -> None:
    """תהליך שכבר הוריד פעם (למשל גרסה קודמת של הקוד, שרצה בלי הקבצים הנוספים) ועכשיו מקבל קבצים נוספים לסנכרון:
    קובץ שקיים מקומית נשמר ויידחף (לא נדרס); קובץ שחסר מקומית יורד מהריפו אם קיים שם. נקרא תחת _lock."""
    have = _state.setdefault("extras", {})
    extra_state = _state.setdefault("extra_state", {})
    for name, path in extras.items():
        if name in have:
            continue
        r = backend().get(_remote_file(user_id, name))
        if os.path.exists(path):
            extra_state[name] = {"sha": r[1] if r else None, "digest": None}  # digest ריק = ידחף בסבב הבא
        elif r is not None:
            _write_atomic(path, r[0])
            extra_state[name] = {"sha": r[1], "digest": _logical_digest(r[0])}
        else:
            extra_state[name] = {"sha": None, "digest": None}
        have[name] = path


def pull(user_id: str, local_path: str, extras: dict | None = None) -> str:
    """פעם אחת לכל תהליך: מוריד את user.db (ו-extras = {שם קובץ בריפו: נתיב מקומי}, למשל config.yaml של הבודק) מהריפו.
    'pulled' / 'none' (אין עדיין בריפו) / 'skipped'. קובץ שאין עותק שלו בריפו וקיים מקומית (נתוני הבודק מלפני המעבר) - יידחף ולא יידרס.
    כל הקריאות מהרשת קורות לפני שנוגעים בקבצים: כשל באמצע לא משאיר מצב חצוי."""
    extras = dict(extras or {})
    with _lock:
        if _state["pulled"]:
            _register_late_extras(user_id, extras)
            return "skipped"
        got = backend().get(remote_db_path(user_id))
        extra_got = {name: backend().get(_remote_file(user_id, name)) for name in extras}
        status = "none"
        if got is not None:
            data, sha = got
            _write_atomic(local_path, data)
            _state.update(sha=sha, pushed_digest=_logical_digest(_snapshot(local_path)))
            status = "pulled"
        extra_state = {}
        for name, path in extras.items():
            r = extra_got[name]
            if r is None:
                extra_state[name] = {"sha": None, "digest": None}
            else:
                _write_atomic(path, r[0])
                extra_state[name] = {"sha": r[1], "digest": _logical_digest(r[0])}
        _state.update(pulled=True, extras=extras, extra_state=extra_state)
        return status


def _put_with_retry(rp: str, data: bytes, sha, message: str) -> str:
    try:
        return backend().put(rp, data, sha, message)
    except Conflict:
        # נכתב ממקום אחר (למשל עריכה ידנית של הבעלים): לוקחים את ה-sha העדכני וכותבים מעליו (הכותב היחיד הוא האתר הזה)
        cur = backend().get(rp)
        return backend().put(rp, data, cur[1] if cur else None, message)


def push_if_changed(user_id: str, local_path: str) -> bool:
    """דוחף לריפו את user.db ואת הקבצים הנוספים (config.yaml, prefs.json) אם השתנו מאז הדחיפה האחרונה. True אם נדחף משהו.
    לא זורק (כשל רשת = ננסה בסבב הבא)."""
    with _lock:
        try:
            if not _state["pulled"]:
                return False  # לעולם לא דוחפים לפני שהורדנו: עותק מקומי ריק היה דורס את הנתונים השמורים בריפו
            pushed = False
            if os.path.exists(local_path):
                data = _snapshot(local_path)
                digest = _logical_digest(data)
                if digest != _state["pushed_digest"]:
                    sha = _put_with_retry(remote_db_path(user_id), data, _state["sha"], f"user data: {user_id}")
                    _state.update(sha=sha, pushed_digest=digest)
                    pushed = True
            extra_state = _state.setdefault("extra_state", {})
            for name, path in (_state.get("extras") or {}).items():
                if not os.path.exists(path):
                    continue
                with open(path, "rb") as f:
                    data = f.read()
                digest = _logical_digest(data)
                st = extra_state.setdefault(name, {"sha": None, "digest": None})
                if digest == st["digest"]:
                    continue
                st["sha"] = _put_with_retry(_remote_file(user_id, name), data, st["sha"], f"{name}: {user_id}")
                st["digest"] = digest
                pushed = True
            return pushed
        except Exception as e:
            logger.warning("דחיפת נתוני בודק %s נכשלה (ננסה שוב): %s", user_id, e)
            return False


def init_tester(user_id: str, local_path: str, extras: dict | None = None) -> str:
    """קריאה אחת בתחילת כל ריצה של אתר בודק (לפני פתיחת ה-DB והגדרות): מוריד פעם אחת בתהליך ומפעיל דחיפה ברקע.
    כשההורדה נכשלת (רשת) לא מפעילים דחיפה ולא נוגעים בקבצים המקומיים - הריצה הבאה תנסה שוב."""
    if not user_id or not configured():
        return "off"
    try:
        status = pull(user_id, local_path, extras)
    except Exception as e:
        logger.warning("הורדת נתוני בודק %s נכשלה: %s", user_id, e)
        return "pull_failed"
    start_background_push(user_id, local_path)
    return status


def start_background_push(user_id: str, local_path: str, interval: int = PUSH_INTERVAL_SEC) -> None:
    """חוט רקע אחד לתהליך: דוחף שינויים כל כמה שניות - מכסה גם כתיבות מתוך fragment (שלא מריצים את סוף הסקריפט)."""
    with _lock:
        t = _state["thread"]
        # גרסת החוט: חוט שנוצר ע"י גרסת קוד ישנה ממשיך לרוץ עם הפונקציות הישנות (בלי הקבצים הנוספים) - גרסה חדשה פותחת חוט משלה
        if t is not None and t.is_alive() and _state.get("thread_version") == _THREAD_VERSION:
            return

    def _loop():
        while True:
            time.sleep(interval)
            push_if_changed(user_id, local_path)

    t = threading.Thread(target=_loop, name="tester-user-db-push", daemon=True)
    with _lock:
        _state["thread"] = t
        _state["thread_version"] = _THREAD_VERSION
    t.start()


def reset_for_tests() -> None:
    global _backend_override
    _backend_override = None
    _state.update(sha=None, pushed_digest=None, pulled=False, thread=None, extras={}, extra_state={})
