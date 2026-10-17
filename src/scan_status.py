"""מצב הסורק לעמוד הבית (ui_v3): כמה זמן עבר מאז הסריקה האחרונה (scan_heartbeat), וסיווג פעיל/מאחר/לא פעיל.

ה-heartbeat נכתב כ-datetime *נאיבי* בשעון של מי שהריץ את הסריקה (בענן: UTC, מקומית: שעון ישראל), ואין בו אזור זמן -
לכן מנסים את שתי הפרשנויות ובוחרים את הקרובה ביותר לעכשיו שאינה בעתיד. ב-alerts.db המקומי הערך מתיישן (מתעדכן רק בעליית
הדשבורד) - לכן מעדיפים את העותק האחרון ב-origin/master (git fetch + git show), עם נפילה חזרה לקובץ המקומי.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import tempfile
from zoneinfo import ZoneInfo

LATE_MINUTES = 10   # יותר מזה = "הסורק מאחר"
DEAD_MINUTES = 30   # כמו התראת ההשהיה של המערכת (scan_heartbeat_gap_alert_minutes)

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def age_minutes(ts: str | None, now_utc: dt.datetime | None = None) -> float | None:
    """גיל ה-heartbeat בדקות. ts נאיבי: UTC (ריצת ענן) או שעון ישראל (ריצה מקומית) - נבחרת הפרשנות הקרובה ביותר שאינה בעתיד."""
    if not ts:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(ts))
    except Exception:
        return None
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    if parsed.tzinfo is not None:
        return max((now_utc - parsed).total_seconds() / 60, 0.0)
    candidates = []
    for tz in (dt.timezone.utc, ZoneInfo("Asia/Jerusalem")):
        delta = (now_utc - parsed.replace(tzinfo=tz)).total_seconds() / 60
        if delta >= -1:  # סובלנות של דקה לסטיית שעונים
            candidates.append(max(delta, 0.0))
    return min(candidates) if candidates else None


def classify(minutes: float | None) -> str:
    """'ok' | 'late' | 'dead' (בלי נתון = 'dead')."""
    if minutes is None or minutes >= DEAD_MINUTES:
        return "dead"
    if minutes > LATE_MINUTES:
        return "late"
    return "ok"


def _read_heartbeat(db_file: str) -> str | None:
    conn = sqlite3.connect(db_file)
    try:
        row = conn.execute("SELECT last_scan_ts FROM scan_heartbeat WHERE id = 1").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def latest_heartbeat(root_dir: str, local_db: str) -> str | None:
    """ה-heartbeat העדכני ביותר: מ-origin/master אם אפשר, אחרת מהקובץ המקומי."""
    try:
        subprocess.run(["git", "-C", root_dir, "fetch", "origin"], check=True, capture_output=True, timeout=20, **_NO_WINDOW)
        res = subprocess.run(
            ["git", "-C", root_dir, "show", "origin/master:alerts.db"], check=True, capture_output=True, timeout=30, **_NO_WINDOW,
        )
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(res.stdout)
            tmp_path = tmp.name
        try:
            return _read_heartbeat(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception:
        pass
    try:
        return _read_heartbeat(local_db)
    except Exception:
        return None
