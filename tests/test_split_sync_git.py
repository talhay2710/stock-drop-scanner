"""DB_SPLIT_PLAN.md 12.א.1: הוכחה שבפריסת split דחיפת המשתמש (user.db, מ-cloud_sync) ודחיפת הסורק (alerts.db, מ-ci_commit_alerts_db.sh)
לא מתנגשות ולא דורסות זו את זו. הכול על repo זמני: origin bare + שני clones (דשבורד מקומי + סורק בענן). לא נוגע ב-repo האמיתי.
הרצה: python -m unittest tests.test_split_sync_git -v"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import cloud_sync, store

CI_SCRIPT = os.path.join(ROOT, "ci_commit_alerts_db.sh")
_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0"}


def _bash() -> str | None:
    # ב-Windows: דווקא ה-bash של Git (לא ה-bash.exe של WSL ב-System32)
    for p in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if p and os.path.exists(p) and "system32" not in p.lower():
            return p
    return None


def git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=_ENV)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout.strip()


def add_row(db_path, table, value):
    c = sqlite3.connect(db_path)
    c.execute(f"CREATE TABLE IF NOT EXISTS {table} (v TEXT)")
    c.execute(f"INSERT INTO {table} VALUES (?)", (value,))
    c.commit()
    c.close()


def rows_at(repo, rev, path, table):
    """התוכן של קובץ SQLite כפי שהוא ב-rev (לא בדיסק)."""
    blob = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, env=_ENV, check=True).stdout
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with open(tmp, "wb") as f:
        f.write(blob)
    c = sqlite3.connect(tmp)
    try:
        return sorted(r[0] for r in c.execute(f"SELECT v FROM {table}"))
    finally:
        c.close()
        os.remove(tmp)


@unittest.skipUnless(shutil.which("git") and _bash(), "צריך git ו-bash")
class SplitSyncTwoClones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="splitsync_")
        self.origin = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", self.origin], check=True, env=_ENV)
        seed = os.path.join(self.tmp, "seed")
        subprocess.run(["git", "clone", "-q", self.origin, seed], check=True, env=_ENV, capture_output=True)
        git(seed, "checkout", "-q", "-b", "master")
        add_row(os.path.join(seed, "alerts.db"), "scan", "s0")
        add_row(os.path.join(seed, "user.db"), "wl", "u0")
        with open(os.path.join(seed, "config.example.yaml"), "w", encoding="utf-8") as f:
            f.write("db_layout: split\n")
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "push", "-q", "-u", "origin", "master")
        self.dash = os.path.join(self.tmp, "dash")
        self.scan = os.path.join(self.tmp, "scan")
        for d in (self.dash, self.scan):
            subprocess.run(["git", "clone", "-q", self.origin, d], check=True, env=_ENV, capture_output=True)
        with open(os.path.join(self.dash, "config.yaml"), "w", encoding="utf-8") as f:  # רק מחשב הבעלים (יש config.yaml) דוחף
            f.write("db_layout: split\ntelegram: {bot_token: x, chat_id: y}\n")
        self.scan_tmp = os.path.join(self.tmp, "scan_tmpdir")
        os.makedirs(self.scan_tmp)
        self._prev_layout = store.layout()
        store.set_layout("split")
        self.patches = [
            mock.patch.object(cloud_sync, "ROOT_DIR", self.dash),
            mock.patch.object(cloud_sync, "CONFIG_PATH", os.path.join(self.dash, "config.yaml")),
            mock.patch.object(cloud_sync, "CONFIG_EXAMPLE_PATH", os.path.join(self.dash, "config.example.yaml")),
            mock.patch.object(cloud_sync, "tester_mode", return_value=False),
            mock.patch.dict(os.environ, {k: v for k, v in _ENV.items() if k.startswith("GIT_")}),  # זהות ל-git של cloud_sync
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        store.set_layout(self._prev_layout)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- עזרים ---
    def scanner_run(self, value, pull=True, layout="split"):
        """ריצת סורק: כותב ל-alerts.db ומריץ את צעד ה-commit האמיתי של ה-workflows."""
        if pull:  # כמו actions/checkout בתחילת כל ריצה
            git(self.scan, "pull", "-q", "--rebase")
        add_row(os.path.join(self.scan, "alerts.db"), "scan", value)
        r = subprocess.run([_bash(), CI_SCRIPT], cwd=self.scan, capture_output=True, text=True,
                           env={**_ENV, "DB_LAYOUT": layout, "TMPDIR": self.scan_tmp})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def scanner_commit_only(self, value):
        """הסורק כבר התחייב מקומית (לפני push) - כדי לייצר מירוץ דטרמיניסטי."""
        add_row(os.path.join(self.scan, "alerts.db"), "scan", value)

    def user_action(self, value):
        add_row(os.path.join(self.dash, "user.db"), "wl", value)
        return cloud_sync.sync_to_cloud("watchlist changed", include_db=True)

    def assert_origin(self, scan_rows, user_rows):
        self.assertEqual(rows_at(self.origin, "master", "alerts.db", "scan"), sorted(scan_rows))
        self.assertEqual(rows_at(self.origin, "master", "user.db", "wl"), sorted(user_rows))

    def assert_no_conflict_left(self, repo):
        self.assertFalse(os.path.exists(os.path.join(repo, ".git", "rebase-merge")))
        self.assertFalse(os.path.exists(os.path.join(repo, ".git", "rebase-apply")))
        self.assertEqual(git(repo, "diff", "--name-only", "--diff-filter=U"), "")

    # --- תרחישים ---
    def test_user_push_rejected_because_scanner_pushed_first(self):
        """המשתמש התחייב, ובדיוק לפני ה-push שלו הסורק דחף alerts.db -> push נדחה -> ניסיון חוזר מצליח, שני השינויים נשמרים."""
        real = cloud_sync._git_run
        fired = []

        def racing(args, **kw):
            if "push" in args and not fired:
                fired.append(1)
                self.scanner_run("s1")
            return real(args, **kw)

        with mock.patch.object(cloud_sync, "_git_run", side_effect=racing):
            self.assertEqual(self.user_action("u1"), "pushed")
        self.assertTrue(fired)
        self.assert_origin(["s0", "s1"], ["u0", "u1"])
        # הקובץ המקומי של הדשבורד לא "חזר" לגרסה ישנה, וה-alerts.db שלו תואם ל-origin (רוענן ב-retry)
        self.assertEqual(git(self.dash, "status", "--porcelain", "--", "alerts.db", "user.db"), "")
        self.assert_no_conflict_left(self.dash)
        # הסורק ממשיך: דחיפה נוספת שלו מעל ה-push של המשתמש
        self.scanner_run("s2")
        self.assert_origin(["s0", "s1", "s2"], ["u0", "u1"])

    def test_scanner_push_rejected_because_user_pushed_first(self):
        """הסורק עובד על בסיס ישן, המשתמש דוחף user.db -> push הסורק נדחה -> pull --rebase רגיל, בלי קונפליקט."""
        git(self.scan, "pull", "-q", "--rebase")
        self.scanner_commit_only("s1")
        self.assertEqual(self.user_action("u1"), "pushed")
        r = subprocess.run([_bash(), CI_SCRIPT], cwd=self.scan, capture_output=True, text=True,
                           env={**_ENV, "DB_LAYOUT": "split", "TMPDIR": self.scan_tmp})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Push rejected", r.stdout)
        self.assertNotIn("conflict", r.stdout + r.stderr)
        self.assert_origin(["s0", "s1"], ["u0", "u1"])
        self.assert_no_conflict_left(self.scan)
        # ההיסטוריה ליניארית (אין merge commits)
        self.assertEqual(git(self.origin, "rev-list", "--merges", "master"), "")

    def test_scanner_never_pushes_user_db(self):
        git(self.scan, "pull", "-q", "--rebase")
        add_row(os.path.join(self.scan, "user.db"), "wl", "BAD")  # נגיעה מקרית של הסורק ב-user.db
        out = self.scanner_run("s1", pull=False)
        self.assertIn("user.db was modified", out)
        self.assert_origin(["s0", "s1"], ["u0"])

    def test_dashboard_never_pushes_alerts_db(self):
        add_row(os.path.join(self.dash, "alerts.db"), "scan", "LOCAL_STALE")
        git(self.dash, "add", "alerts.db")  # גם כשהוא staged בטעות
        self.assertEqual(self.user_action("u1"), "pushed")
        self.assert_origin(["s0"], ["u0", "u1"])

    def test_refresh_takes_scan_from_origin_and_keeps_local_user_db(self):
        self.scanner_run("s1")
        add_row(os.path.join(self.dash, "user.db"), "wl", "u_local")  # שינוי משתמש שעוד לא נדחף
        add_row(os.path.join(self.dash, "alerts.db"), "scan", "junk")  # שינוי מקומי ב-alerts.db (לא מקור אמת ב-split)
        self.assertTrue(cloud_sync.refresh_alerts_db_if_clean())
        c = sqlite3.connect(os.path.join(self.dash, "alerts.db"))
        self.assertEqual(sorted(r[0] for r in c.execute("SELECT v FROM scan")), ["s0", "s1"])
        c.close()
        c = sqlite3.connect(os.path.join(self.dash, "user.db"))
        self.assertEqual(sorted(r[0] for r in c.execute("SELECT v FROM wl")), ["u0", "u_local"])
        c.close()

    def test_legacy_branch_still_pushes(self):
        """המתג עדיין legacy בענן: ה-workflows עכשיו קוראים לסקריפט - הענף הישן חייב להמשיך לדחוף כרגיל."""
        out = self.scanner_run("s1", layout="legacy")
        self.assertIn("db_layout: legacy", out)
        self.assertEqual(rows_at(self.origin, "master", "alerts.db", "scan"), ["s0", "s1"])

    def test_no_change_no_commit(self):
        git(self.scan, "pull", "-q", "--rebase")
        before = git(self.origin, "rev-parse", "master")
        r = subprocess.run([_bash(), CI_SCRIPT], cwd=self.scan, capture_output=True, text=True, env={**_ENV, "DB_LAYOUT": "split"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("No change", r.stdout)
        self.assertEqual(git(self.origin, "rev-parse", "master"), before)

    def test_parallel_pushes_lose_nothing(self):
        """שני "מחשבים" דוחפים במקביל באמת (threads), כמה סבבים - בסוף origin מכיל את כל השורות של שניהם."""
        n = 4
        errors = []

        def dashboard():
            try:
                for i in range(n):
                    self.assertEqual(self.user_action(f"u{i + 1}"), "pushed")
            except Exception as e:  # noqa: BLE001
                errors.append(f"dashboard: {e!r}")

        def scanner():
            try:
                for i in range(n):
                    self.scanner_run(f"s{i + 1}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"scanner: {e!r}")

        threads = [threading.Thread(target=dashboard), threading.Thread(target=scanner)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=300)
        self.assertEqual(errors, [])
        self.assert_origin(["s0"] + [f"s{i + 1}" for i in range(n)], ["u0"] + [f"u{i + 1}" for i in range(n)])
        self.assertEqual(git(self.origin, "rev-list", "--merges", "master"), "")
        self.assert_no_conflict_left(self.dash)
        self.assert_no_conflict_left(self.scan)


if __name__ == "__main__":
    unittest.main()
