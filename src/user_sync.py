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
PREFS_INDICES = ("TA35", "TA125")  # המדדים שהסורק האוטומטי סורק בפועל
PREFS_DEFAULTS = {"signals": ["buy"], "indices": list(PREFS_INDICES), "min_drop_pct": 0.0,
                  "multi_day": True, "min_multi_pct": 0.0, "reversal": False}


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
    for key in ("multi_day", "reversal"):
        if key in raw:
            out[key] = bool(raw[key])
    return out


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


def pull(user_id: str, local_path: str) -> str:
    """פעם אחת לכל תהליך (אחרי כניסה מוצלחת): מוריד את user.db מהריפו. 'pulled' / 'none' (אין עדיין בריפו) / 'skipped'.
    כשאין עותק בריפו וקיים קובץ מקומי (נתוני הבודק מלפני המעבר) - הוא יידחף בסבב הבא ולא יידרס."""
    with _lock:
        if _state["pulled"]:
            return "skipped"
        got = backend().get(remote_db_path(user_id))
        if got is None:
            _state["pulled"] = True
            return "none"
        data, sha = got
        tmp = local_path + ".pull"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, local_path)
        _state.update(sha=sha, pushed_digest=_logical_digest(_snapshot(local_path)), pulled=True)
        return "pulled"


def push_if_changed(user_id: str, local_path: str) -> bool:
    """דוחף את user.db לריפו אם השתנה מאז הדחיפה האחרונה. מחזיר True אם נדחף. לא זורק (כשל רשת = ננסה בסבב הבא)."""
    with _lock:
        try:
            if not _state["pulled"]:
                return False  # לעולם לא דוחפים לפני שהורדנו: עותק מקומי ריק היה דורס את הנתונים השמורים בריפו
            if not os.path.exists(local_path):
                return False
            data = _snapshot(local_path)
            digest = _logical_digest(data)
            if digest == _state["pushed_digest"]:
                return False
            rp = remote_db_path(user_id)
            try:
                sha = backend().put(rp, data, _state["sha"], f"user data: {user_id}")
            except Conflict:
                # נכתב ממקום אחר (למשל עריכה ידנית של הבעלים): לוקחים את ה-sha העדכני וכותבים מעליו (הכותב היחיד הוא האתר הזה)
                cur = backend().get(rp)
                sha = backend().put(rp, data, cur[1] if cur else None, f"user data: {user_id}")
            _state.update(sha=sha, pushed_digest=digest)
            return True
        except Exception as e:
            logger.warning("דחיפת נתוני בודק %s נכשלה (ננסה שוב): %s", user_id, e)
            return False


def init_tester(user_id: str, local_path: str) -> str:
    """קריאה אחת בתחילת כל ריצה של אתר בודק (לפני פתיחת ה-DB): מוריד פעם אחת בתהליך ומפעיל דחיפה ברקע.
    כשההורדה נכשלת (רשת) לא מפעילים דחיפה ולא נוגעים בקובץ המקומי - הריצה הבאה תנסה שוב."""
    if not user_id or not configured():
        return "off"
    try:
        status = pull(user_id, local_path)
    except Exception as e:
        logger.warning("הורדת נתוני בודק %s נכשלה: %s", user_id, e)
        return "pull_failed"
    start_background_push(user_id, local_path)
    return status


def start_background_push(user_id: str, local_path: str, interval: int = PUSH_INTERVAL_SEC) -> None:
    """חוט רקע אחד לתהליך: דוחף שינויים כל כמה שניות - מכסה גם כתיבות מתוך fragment (שלא מריצים את סוף הסקריפט)."""
    with _lock:
        t = _state["thread"]
        if t is not None and t.is_alive():
            return

    def _loop():
        while True:
            time.sleep(interval)
            push_if_changed(user_id, local_path)

    t = threading.Thread(target=_loop, name="tester-user-db-push", daemon=True)
    with _lock:
        _state["thread"] = t
    t.start()


def reset_for_tests() -> None:
    global _backend_override
    _backend_override = None
    _state.update(sha=None, pushed_digest=None, pulled=False, thread=None)
