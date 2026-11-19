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
        # בדיקת ה-AppTest מוחקת וטוענת מחדש את מודולי src: תמיד עובדים מול המודולים הנוכחיים
        global user_sync, tester_telegram
        import importlib
        user_sync, tester_telegram = importlib.import_module("src.user_sync"), importlib.import_module("src.tester_telegram")
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


class AccessCodeAndRemoval(_Base):
    def setUp(self):
        super().setUp()
        rec, self.code = user_sync.new_user_record("מיכל")
        rec["link_token"] = "tok"
        user_sync.write_json("users.json", {"users": {"michal": rec, "zeevi": dict(rec)}}, None, "t")
        user_sync.write_json("telegram_links.json", {"last_update_id": 5, "chats": {"michal": 1, "zeevi": 2}}, None, "t")
        for u in ("michal", "zeevi"):
            user_sync._backend_override.put(f"data/{u}/user.db", b"db", None, "t")
            user_sync._backend_override.put(f"data/{u}/prefs.json", b"{}", None, "t")
        user_sync._login_fails.clear()

    def test_login_ok_bad_and_lockout(self):
        self.assertEqual(user_sync.attempt_login("michal", "0000-0000-0000", now=1000.0), "bad")
        self.assertEqual(user_sync.attempt_login("michal", self.code, now=1001.0), "ok")
        for i in range(8):
            self.assertEqual(user_sync.attempt_login("michal", "nope", now=2000.0 + i), "bad")
        self.assertEqual(user_sync.attempt_login("michal", self.code, now=2010.0), "locked")  # גם קוד נכון - נעול
        self.assertEqual(user_sync.attempt_login("zeevi", self.code, now=2010.0), "ok")         # נעילה לכל משתמש בנפרד
        self.assertEqual(user_sync.attempt_login("michal", self.code, now=2000.0 + 700), "ok")  # אחרי 10 דקות - משתחרר

    def test_remove_user_deletes_only_that_user(self):
        out = user_sync.remove_user("michal")
        self.assertTrue(out["user"] and out["telegram"])
        self.assertEqual(sorted(out["files"]), ["data/michal/prefs.json", "data/michal/user.db"])
        be = user_sync._backend_override
        self.assertEqual(list(user_sync.read_json("users.json", {})[0]["users"]), ["zeevi"])
        self.assertEqual(user_sync.read_json("telegram_links.json", {})[0]["chats"], {"zeevi": 2})
        self.assertEqual(be.list("data/michal"), [])
        self.assertEqual(len(be.list("data/zeevi")), 2)
        self.assertEqual(user_sync.read_json("telegram_links.json", {})[0]["last_update_id"], 5)

    def test_remove_unknown_user_is_harmless(self):
        out = user_sync.remove_user("nobody")
        self.assertEqual((out["user"], out["telegram"], out["files"]), (False, False, []))
        self.assertEqual(len(user_sync.read_json("users.json", {})[0]["users"]), 2)


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

    def test_default_prefs_are_buy_only(self):
        p = user_sync.clean_prefs({})
        w = tester_telegram.wants
        self.assertTrue(w(p, "drop", index="TA35", signal="buy", drop_pct=-3.2))
        self.assertFalse(w(p, "drop", index="TA35", signal="wait", drop_pct=-3.2))
        self.assertFalse(w(p, "drop", index="TA35", signal="avoid", drop_pct=-5))
        self.assertFalse(w(p, "reversal", index="TA35"))

    def test_prefs_filters(self):
        w = tester_telegram.wants
        p = user_sync.clean_prefs({"signals": ["buy", "wait"], "indices": ["TA125"], "min_drop_pct": 4.0,
                                   "multi_day": True, "min_multi_pct": 6.0, "reversal": True})
        self.assertTrue(w(p, "drop", index="TA125", signal="wait", drop_pct=-4.5))
        self.assertFalse(w(p, "drop", index="TA35", signal="buy", drop_pct=-9))       # מדד לא נבחר
        self.assertFalse(w(p, "drop", index="TA125", signal="buy", drop_pct=-3.5))    # מתחת לירידה המינימלית
        self.assertFalse(w(p, "drop", index="TA125", signal="avoid", drop_pct=-9))    # סיגנל לא נבחר
        self.assertTrue(w(p, "drop", index="TA125", signal="buy", drop_pct=-1, multi_day_only=True, n_day_pct=-7))
        self.assertFalse(w(p, "drop", index="TA125", signal="buy", drop_pct=-1, multi_day_only=True, n_day_pct=-5))
        self.assertTrue(w(p, "reversal", index="TA125"))
        self.assertFalse(w(p, "reversal", index="TA35"))
        off = user_sync.clean_prefs({"multi_day": False})
        self.assertFalse(w(off, "drop", index="TA35", signal="buy", drop_pct=-1, multi_day_only=True, n_day_pct=-9))

    def test_clean_prefs_repairs_garbage(self):
        p = user_sync.clean_prefs({"signals": ["buy", "hack"], "indices": "x", "min_drop_pct": "abc", "min_multi_pct": 999, "reversal": 1})
        self.assertEqual(p["signals"], ["buy"])
        self.assertEqual(p["indices"], ["TA35", "TA125"])
        self.assertEqual(p["min_drop_pct"], 0.0)
        self.assertEqual(p["min_multi_pct"], 50.0)
        self.assertTrue(p["reversal"])
        self.assertEqual(user_sync.clean_prefs(None), user_sync.clean_prefs({}))

    def test_prefs_roundtrip_and_per_recipient_broadcast(self):
        user_sync.write_json("telegram_links.json", {"last_update_id": 0, "chats": {"a": 1, "b": 2}}, None, "t")
        user_sync.write_prefs("b", {"signals": ["buy", "wait"], "indices": ["TA35", "TA125"]})
        self.assertEqual(user_sync.read_prefs("b")["signals"], ["buy", "wait"])
        self.assertEqual(user_sync.read_prefs("a")["signals"], ["buy"])  # אין קובץ = ברירת מחדל
        sent = []

        def fake_post(url, json=None, timeout=None):
            sent.append(json["chat_id"])
            return _Resp(200)

        with mock.patch("requests.post", side_effect=fake_post):
            tester_telegram._cache.update(at=0.0, chats={})
            n = tester_telegram.broadcast(self.CFG, "x", kind="drop", index="TA35", signal="wait", drop_pct=-3.5)
        self.assertEqual((n, sent), (1, [2]))  # רק b ביקש גם 'לחכות'

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


class TesterHoldings(_Base):
    """התראות אחזקות לבודק: בלי רשת ובלי טלגרם אמיתי (מחירים וטלגרם מוחלפים)."""
    _FEES = {"commission_pct": 0.3, "commission_min": 26.0, "currency": "ILS", "capital_gains_tax_pct": 25.0,
             "management_fee_annual_pct": 1.15}
    CFG = {"telegram": {"enabled": True, "bot_token": "T", "chat_id": "1"}, "fees": {"IL": _FEES, "US": _FEES}}

    def setUp(self):
        super().setUp()
        import datetime as dt
        from src import tester_holdings
        self.th = tester_holdings
        self.now = dt.datetime.now().replace(microsecond=0).isoformat()
        # מסד הסריקה: התראה אחת (id=7) על מניה בת"א
        self.scan = sqlite3.connect(":memory:")
        self.scan.execute("CREATE TABLE alerts (id INTEGER, ticker TEXT, company_name TEXT, index_name TEXT, target_base REAL)")
        self.scan.execute("INSERT INTO alerts VALUES (7, 'AAA.TA', 'אאא', 'TA35', NULL)")
        user_sync.write_json("telegram_links.json", {"last_update_id": 0, "chats": {"michal": 555}}, None, "t")
        tester_telegram._cache.update(at=0.0, chats={})

    def _put_user_db(self, rows, price_alerts=(), closed=()):
        path = os.path.join(tempfile.mkdtemp(), "u.db")
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE positions (alert_id INTEGER PRIMARY KEY, entry_price REAL, qty REAL, bought_at TEXT, stop_price REAL, is_manual INTEGER)")
        c.executemany("INSERT INTO positions VALUES (?,?,?,?,?,?)", rows)
        c.execute("CREATE TABLE price_alerts (id INTEGER PRIMARY KEY, ticker TEXT, company_name TEXT, index_name TEXT, target_price REAL, "
                  "direction TEXT, created_at TEXT, cancelled INTEGER NOT NULL DEFAULT 0)")
        c.executemany("INSERT INTO price_alerts VALUES (?,?,?,?,?,?,?,?)", price_alerts)
        c.execute("CREATE TABLE closed_trades (id INTEGER PRIMARY KEY, ticker TEXT, company_name TEXT, exit_at TEXT, exit_price REAL, qty REAL, "
                  "gross_pnl REAL, currency TEXT)")
        c.executemany("INSERT INTO closed_trades VALUES (?,?,?,?,?,?,?,?)", closed)
        c.commit()
        c.close()
        be = user_sync._backend_override
        cur = be.get("data/michal/user.db")
        with open(path, "rb") as fh:
            be.put("data/michal/user.db", fh.read(), cur[1] if cur else None, "t")

    def _run(self, price, types=None, now_open=True):
        sent = []

        def fake_post(url, json=None, timeout=None):
            sent.append(json["text"])
            return _Resp(200)

        types = types or set(self.th.HOLDING_TYPES)
        with mock.patch("requests.post", side_effect=fake_post),                 mock.patch("src.market_data.fetch_current_price", return_value=price),                 mock.patch.object(self.th, "is_market_open", return_value=now_open):
            self.th.check_one(self.CFG, self.scan, "michal", 555, types)
        return sent

    def test_stop_alert_once_then_rearms(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        self.assertEqual(len(self._run(96.0, {"holdings_stop"})), 1)   # בתוך 2% מהסטופ
        self.assertEqual(len(self._run(95.5, {"holdings_stop"})), 0)   # לא חוזר
        self.assertEqual(len(self._run(110.0, {"holdings_stop"})), 0)  # התרחק - מתאפס בשקט
        self.assertEqual(len(self._run(95.5, {"holdings_stop"})), 1)   # ושוב התראה
        state = user_sync.read_json("data/michal/state.json", {})[0]
        self.assertTrue(state["7"]["stop_alert_active"])

    def test_target_and_gain_alerts(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        msgs = self._run(104.0, {"holdings_target", "holdings_gain"})
        self.assertTrue(any("ליעד" in m for m in msgs) and any("עלתה" in m for m in msgs))
        self.assertEqual(self._run(104.0, {"holdings_target", "holdings_gain"}), [])  # אותה מדרגה לא חוזרת
        self.assertEqual(len(self._run(106.5, {"holdings_gain"})), 1)                   # מדרגה חדשה

    def test_disabled_types_do_nothing_and_keep_no_state(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        self.assertEqual(self._run(94.0, {"holdings_gain"}), [])
        self.assertEqual(user_sync.read_json("data/michal/state.json", {})[0], {})

    def test_failed_send_is_retried_next_run(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        with mock.patch("requests.post", return_value=_Resp(500)), mock.patch("src.market_data.fetch_current_price", return_value=94.0),                 mock.patch.object(self.th, "is_market_open", return_value=True):
            self.th.check_one(self.CFG, self.scan, "michal", 555, {"holdings_stop"})
        self.assertEqual(len(self._run(94.0, {"holdings_stop"})), 1)  # נשלח עכשיו, כי הכשל לא נרשם כנשלח

    def test_market_closed_and_missing_price_skip(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        self.assertEqual(self._run(94.0, now_open=False), [])
        self.assertEqual(self._run(None), [])

    def test_closed_position_state_is_dropped(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        self._run(94.0, {"holdings_stop"})
        self._put_user_db([])
        self._run(94.0)
        self.assertEqual(user_sync.read_json("data/michal/state.json", {})[0], {})

    def test_hold_limit_not_for_manual(self):
        old = "2026-11-01T10:00:00"
        self._put_user_db([(7, 100.0, 10.0, old, 95.0, 1)])
        self.assertEqual(self._run(100.5, {"holdings_hold_limit"}), [])
        self._put_user_db([(7, 100.0, 10.0, old, 95.0, 0)])
        self.assertEqual(len(self._run(100.5, {"holdings_hold_limit"})), 1)

    def test_price_alert_fires_once_and_skips_cancelled(self):
        pa = [(1, "AAA.TA", "אאא", "TA35", 110.0, "above", "2026-11-18", 0),
              (2, "AAA.TA", "אאא", "TA35", 50.0, "below", "2026-11-18", 1)]  # השנייה בוטלה
        self._put_user_db([], price_alerts=pa)
        self.assertEqual(self._run(100.0, {"price_alert"}), [])           # עוד לא חצתה
        msgs = self._run(111.0, {"price_alert"})
        self.assertEqual(len(msgs), 1)
        self.assertIn("מחיר יעד שקבעת", msgs[0])
        self.assertEqual(self._run(112.0, {"price_alert"}), [])           # חד-פעמית
        self.assertEqual(user_sync.read_json("data/michal/state.json", {})[0]["price_alerts_triggered"], [1])

    def test_price_alert_type_disabled(self):
        self._put_user_db([], price_alerts=[(1, "AAA.TA", "אאא", "TA35", 90.0, "below", "2026-11-18", 0)])
        self.assertEqual(self._run(80.0, {"holdings_stop"}), [])

    def test_check_testers_respects_prefs_and_survives_errors(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        user_sync.write_prefs("michal", {"holdings_stop": False, "holdings_target": False, "holdings_gain": False,
                                          "holdings_hold_limit": False})
        tester_telegram._cache.update(at=0.0, chats={})
        with mock.patch("requests.post") as post, mock.patch("src.market_data.fetch_current_price", return_value=94.0):
            self.assertEqual(self.th.check_testers(self.CFG, self.scan), 0)
            post.assert_not_called()
        with mock.patch.object(self.th, "check_one", side_effect=RuntimeError("boom")):
            tester_telegram._cache.update(at=0.0, chats={})
            user_sync.write_prefs("michal", {})
            self.assertEqual(self.th.check_testers(self.CFG, self.scan), 0)  # לא זורק


class TesterSummaries(TesterHoldings):
    """סיכומים לבודק: חלונות זמן, 'נשלח היום' פעם אחת, ניסיון חוזר בכשל, והעדפות (בלי רשת)."""

    def _go(self, due=("daily",), today="2026-11-19", send_ok=True, msg="סיכום"):
        from src import tester_summaries as ts
        self.ts = ts
        sent = []

        def fake_post(url, json=None, timeout=None):
            sent.append(json["text"])
            return _Resp(200 if send_ok else 500)

        wins = {k: v[1] for k, v in ts.KINDS.items()}
        in_window = lambda *a, **k: tuple(a) in {wins[d] for d in due}  # noqa: E731
        with mock.patch("requests.post", side_effect=fake_post), \
                mock.patch("src.daily_summary.build_daily_summary", return_value=msg), \
                mock.patch("src.daily_summary.build_morning_summary", return_value=msg), \
                mock.patch("src.weekly_report.build_weekly_report", return_value=msg), \
                mock.patch("src.holdings_summary.build_holdings_summary", return_value=[]), \
                mock.patch("src.holdings_summary.enrich_closed_today_with_today_pnl", side_effect=lambda c: c), \
                mock.patch.object(ts, "_morning_inputs", return_value=({}, {})):
            tester_telegram._cache.update(at=0.0, chats={})
            n = ts.run(self.CFG, self.scan, in_window=in_window, today=today)
        return n, sent

    def _prefs(self, **kw):
        user_sync.write_prefs("michal", kw)
        tester_telegram._cache.update(at=0.0, chats={})

    def test_default_prefs_send_no_summaries(self):
        self._put_user_db([])
        self.assertEqual(self._go(due=("morning", "daily", "weekly"))[0], 0)

    def test_daily_sent_once_per_day_and_again_next_day(self):
        self._put_user_db([])
        self._prefs(daily_summary=True)
        self.assertEqual(self._go()[0], 1)
        self.assertEqual(self._go()[0], 0)                      # אותו יום - לא שוב
        self.assertEqual(self._go(today="2026-11-20")[0], 1)    # יום חדש

    def test_outside_window_nothing(self):
        self._put_user_db([])
        self._prefs(daily_summary=True)
        self.assertEqual(self._go(due=())[0], 0)

    def test_failed_send_retries_and_each_kind_separate(self):
        self._put_user_db([])
        self._prefs(daily_summary=True, weekly_report=True, morning_summary=False)
        self.assertEqual(self._go(due=("daily",), send_ok=False)[0], 0)
        n, sent = self._go(due=("daily", "weekly"))
        self.assertEqual((n, len(sent)), (2, 2))                # היומי שנכשל נשלח עכשיו + השבועי
        self.assertEqual(self._go(due=("daily", "weekly"))[0], 0)

    def test_empty_report_is_marked_done_without_sending(self):
        self._put_user_db([])
        self._prefs(weekly_report=True)
        self.assertEqual(self._go(due=("weekly",), msg=None)[0], 0)
        self.assertEqual(user_sync.read_json("data/michal/state.json", {})[0]["summaries"], {"weekly": "2026-11-19"})

    def test_state_keys_survive_holding_check(self):
        self._put_user_db([(7, 100.0, 10.0, self.now, 95.0, 0)])
        self._prefs(daily_summary=True)
        self._go()
        self._run(96.0, {"holdings_stop"})  # בדיקת האחזקות לא מוחקת את "נשלח היום"
        state = user_sync.read_json("data/michal/state.json", {})[0]
        self.assertEqual(state["summaries"], {"daily": "2026-11-19"})
        self.assertTrue(state["7"]["stop_alert_active"])


try:
    from streamlit.testing.v1 import AppTest
except Exception:  # pragma: no cover
    AppTest = None


@unittest.skipIf(AppTest is None, "streamlit.testing לא זמין")
class LoginGateInApp(unittest.TestCase):
    """אתר בודק עם משתמש: בלי קוד תקין רואים רק מסך כניסה. GitHub מוחלף בתשובות מזויפות (ה-AppTest מוחק את מודולי src, לכן מחליפים את requests)."""

    def test_gate_blocks_until_correct_code(self):
        import base64
        user_sync.reset_for_tests()
        rec, code = user_sync.new_user_record("מיכל")
        users_json = json.dumps({"users": {"michal": rec}}).encode()

        class R:
            def __init__(self, status, payload=None):
                self.status_code, self._p, self.content = status, payload or {}, b""

            def json(self):
                return self._p

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

        def fake_get(url, *a, **k):
            if url.endswith("/contents/users.json"):
                return R(200, {"sha": "s", "content": base64.b64encode(users_json).decode()})
            return R(404)

        env = {"TESTER_MODE": "1", "TESTER_USER": "michal", "USERS_REPO": "x/y", "USERS_REPO_TOKEN": "t", "TESTER_LOGIN": "1"}
        with mock.patch.dict(os.environ, env), mock.patch("requests.get", side_effect=fake_get),                 mock.patch("requests.put", return_value=R(200, {"content": {"sha": "n"}})):
            at = AppTest.from_file(os.path.join(ROOT, "dashboard.py"), default_timeout=180)
            at.run()
            self.assertEqual([str(e.value)[:150] for e in at.exception], [])
            self.assertEqual(len(at.text_input), 1)  # רק מסך הכניסה
            at.text_input[0].set_value("0000-0000-0000")
            at.button[0].click()
            at.run()
            self.assertEqual(len(at.text_input), 1)
            self.assertTrue(any("קוד שגוי" in e.value for e in at.error))
            at.text_input[0].set_value(code)
            at.button[0].click()
            at.run()
            self.assertEqual([str(e.value)[:150] for e in at.exception], [])
            self.assertEqual(len(at.text_input), 0)  # עבר את השער
        user_sync.reset_for_tests()
        for name in os.listdir(ROOT):
            if name.startswith(("alerts_tester.db", "user_tester.db")):
                try:
                    os.remove(os.path.join(ROOT, name))
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
