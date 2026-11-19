"""בדיקות (בלי רשת, בלי טלגרם אמיתי): שמירה עמידה של נתוני בודק בריפו פרטי, וקוד גישה, וחיבור/שליחת טלגרם לבודקים.
הרצה: python -m unittest tests.test_user_sync -v"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import tester_telegram, user_sync


def _make_db(path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT)")
    c.execute("DELETE FROM watchlist")
    c.executemany("INSERT INTO watchlist VALUES (?)", [(r,) for r in rows])
    c.commit()
    c.close()


def _rows(path):
    c = sqlite3.connect(path)
    try:
        return sorted(r[0] for r in c.execute("SELECT ticker FROM watchlist"))
    finally:
        c.close()


class _Base(unittest.TestCase):
    def setUp(self):
        user_sync.reset_for_tests()
        user_sync._backend_override = user_sync.MemoryBackend()
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "user_tester.db")

    def tearDown(self):
        user_sync.reset_for_tests()


class Persistence(_Base):
    def test_data_survives_server_reset(self):
        self.assertEqual(user_sync.init_tester("michal", self.db), "none")  # בודק חדש, אין עדיין כלום בריפו
        _make_db(self.db, ["AAA.TA", "BBB.TA"])
        self.assertTrue(user_sync.push_if_changed("michal", self.db))
        # שרת מתאפס: הקובץ המקומי נעלם והמצב בתהליך מאופס
        os.remove(self.db)
        backend = user_sync._backend_override
        user_sync.reset_for_tests()
        user_sync._backend_override = backend
        self.assertEqual(user_sync.init_tester("michal", self.db), "pulled")
        self.assertEqual(_rows(self.db), ["AAA.TA", "BBB.TA"])

    def test_change_is_pushed_again_and_unchanged_is_not(self):
        user_sync.init_tester("michal", self.db)
        _make_db(self.db, ["AAA.TA"])
        self.assertTrue(user_sync.push_if_changed("michal", self.db))
        self.assertFalse(user_sync.push_if_changed("michal", self.db))  # בלי שינוי - בלי דחיפה
        _make_db(self.db, ["AAA.TA", "CCC.TA"])
        self.assertTrue(user_sync.push_if_changed("michal", self.db))
        data = user_sync._backend_override.get("data/michal/user.db")[0]
        out = os.path.join(self.tmp, "remote.db")
        open(out, "wb").write(data)
        self.assertEqual(_rows(out), ["AAA.TA", "CCC.TA"])

    def test_existing_local_data_is_uploaded_when_remote_empty(self):
        _make_db(self.db, ["OLD.TA"])  # נתוני הבודק מלפני המעבר
        self.assertEqual(user_sync.init_tester("michal", self.db), "none")
        self.assertTrue(user_sync.push_if_changed("michal", self.db))
        self.assertEqual(_rows(self.db), ["OLD.TA"])

    def test_failed_pull_never_pushes_and_never_overwrites_remote(self):
        user_sync.init_tester("michal", self.db)
        _make_db(self.db, ["REAL.TA"])
        user_sync.push_if_changed("michal", self.db)
        backend = user_sync._backend_override
        # אתחול מחדש + ההורדה נכשלת (רשת): לא נוגעים בקובץ המקומי הריק ולא דוחפים אותו
        user_sync.reset_for_tests()
        user_sync._backend_override = backend
        os.remove(self.db)
        _make_db(self.db, [])
        with mock.patch.object(backend, "get", side_effect=RuntimeError("network")):
            self.assertEqual(user_sync.init_tester("michal", self.db), "pull_failed")
        self.assertFalse(user_sync.push_if_changed("michal", self.db))
        self.assertEqual(_rows_remote(backend), ["REAL.TA"])

    def test_pull_happens_once_per_process(self):
        user_sync.init_tester("michal", self.db)
        _make_db(self.db, ["A.TA"])
        user_sync.push_if_changed("michal", self.db)
        _make_db(self.db, ["A.TA", "NEW.TA"])  # שינוי מקומי שטרם נדחף
        self.assertEqual(user_sync.init_tester("michal", self.db), "skipped")  # ריצה נוספת לא דורסת אותו
        self.assertEqual(_rows(self.db), ["A.TA", "NEW.TA"])

    def test_conflict_is_resolved_by_overwrite(self):
        user_sync.init_tester("michal", self.db)
        _make_db(self.db, ["A.TA"])
        user_sync.push_if_changed("michal", self.db)
        be = user_sync._backend_override
        be.files["data/michal/user.db"] = (be.files["data/michal/user.db"][0], "other-sha")  # נכתב ממקום אחר
        _make_db(self.db, ["A.TA", "B.TA"])
        self.assertTrue(user_sync.push_if_changed("michal", self.db))
        self.assertEqual(_rows_remote(be), ["A.TA", "B.TA"])

    def test_off_without_configuration(self):
        user_sync.reset_for_tests()  # בלי backend ובלי משתני סביבה
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USERS_REPO", None)
            os.environ.pop("USERS_REPO_TOKEN", None)
            self.assertEqual(user_sync.init_tester("michal", self.db), "off")


def _rows_remote(backend):
    out = tempfile.mktemp(suffix=".db")
    open(out, "wb").write(backend.get("data/michal/user.db")[0])
    return _rows(out)


class AccessCode(_Base):
    def test_code_roundtrip(self):
        rec, code = user_sync.new_user_record("מיכל")
        user_sync.write_json("users.json", {"users": {"michal": rec}}, None, "t")
        self.assertTrue(user_sync.verify_code("michal", code))
        self.assertTrue(user_sync.verify_code("michal", " " + code + " "))
        self.assertFalse(user_sync.verify_code("michal", "0000-0000-0000"))
        self.assertFalse(user_sync.verify_code("zeevi", code))
        self.assertFalse(user_sync.verify_code("michal", ""))
        self.assertNotIn(code, json.dumps(rec))  # הקוד עצמו לא נשמר


class _Resp:
    def __init__(self, code=200, payload=None):
        self.status_code, self._p = code, payload or {}

    def json(self):
        return self._p


class TelegramLinks(_Base):
    CFG = {"telegram": {"enabled": True, "bot_token": "TESTTOKEN", "chat_id": "1"}}

    def setUp(self):
        super().setUp()
        rec, _ = user_sync.new_user_record("מיכל")
        rec["link_token"] = "tok123"
        user_sync.write_json("users.json", {"bot_username": "bot", "users": {"michal": rec}}, None, "t")
        tester_telegram._cache.update(at=0.0, chats={})

    def _updates(self, *msgs):
        return _Resp(200, {"result": [{"update_id": 10 + i, "message": {"text": t, "chat": {"id": c}}} for i, (t, c) in enumerate(msgs)]})

    def test_start_links_chat_and_stop_unlinks(self):
        with mock.patch("requests.get", return_value=self._updates(("/start tok123", 555))), \
             mock.patch("requests.post", return_value=_Resp()) as post:
            self.assertEqual(tester_telegram.poll_links(self.CFG), 1)
            self.assertEqual(post.call_count, 1)  # הודעת אישור
        links, _ = user_sync.read_json("telegram_links.json", {})
        self.assertEqual(links["chats"], {"michal": 555})
        self.assertEqual(links["last_update_id"], 10)
        self.assertTrue(user_sync.telegram_status("michal")["connected"])
        self.assertIn("start=tok123", user_sync.telegram_status("michal")["link"])
        with mock.patch("requests.get", return_value=self._updates(("/stop", 555))), mock.patch("requests.post", return_value=_Resp()):
            tester_telegram.poll_links(self.CFG)
        self.assertEqual(user_sync.read_json("telegram_links.json", {})[0]["chats"], {})

    def test_wrong_token_and_random_text_ignored(self):
        with mock.patch("requests.get", return_value=self._updates(("/start nope", 1), ("שלום", 2), ("/start", 3))), \
             mock.patch("requests.post", return_value=_Resp()) as post:
            self.assertEqual(tester_telegram.poll_links(self.CFG), 0)
            self.assertEqual(post.call_count, 0)
        self.assertEqual(user_sync.read_json("telegram_links.json", {})[0]["chats"], {})

    def test_offset_is_sent_so_updates_are_not_reprocessed(self):
        user_sync.write_json("telegram_links.json", {"last_update_id": 41, "chats": {}}, None, "t")
        with mock.patch("requests.get", return_value=_Resp(200, {"result": []})) as get:
            tester_telegram.poll_links(self.CFG)
            self.assertEqual(get.call_args.kwargs["params"]["offset"], 42)

    def test_broadcast_sends_to_all_linked_and_survives_one_failure(self):
        user_sync.write_json("telegram_links.json", {"last_update_id": 0, "chats": {"a": 1, "b": 2, "c": 3}}, None, "t")
        calls = []

        def fake_post(url, json=None, timeout=None):
            calls.append(json["chat_id"])
            if json["chat_id"] == 2:
                raise RuntimeError("boom")
            return _Resp(200)

        with mock.patch("requests.post", side_effect=fake_post):
            self.assertEqual(tester_telegram.broadcast(self.CFG, "<b>x</b>"), 2)
        self.assertEqual(sorted(calls), [1, 2, 3])

    def test_noop_when_telegram_disabled_or_unconfigured(self):
        off = {"telegram": {"enabled": False, "bot_token": "T"}}
        with mock.patch("requests.post") as post, mock.patch("requests.get") as get:
            self.assertEqual(tester_telegram.broadcast(off, "x"), 0)
            self.assertEqual(tester_telegram.poll_links(off), 0)
            post.assert_not_called()
            get.assert_not_called()
        user_sync.reset_for_tests()
        os.environ.pop("USERS_REPO_TOKEN", None)
        with mock.patch("requests.post") as post:
            self.assertEqual(tester_telegram.broadcast(self.CFG, "x"), 0)
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
