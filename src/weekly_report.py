"""דוח שבועי אסטרטגי: אילו סוגי סיבות-ירידה הצליחו יותר בשבוע האחרון, לפי
נתוני ה-backtest שכבר הצטברו - עוזר להבין לאילו התראות שווה להקשיב יותר.
"""
import datetime as dt
import sqlite3

import pandas as pd

from . import backtest
from .analysis import REASON_LABELS


def build_weekly_report(conn: sqlite3.Connection, days: int = 7) -> str | None:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    df = pd.read_sql_query(
        "SELECT * FROM alerts WHERE scan_date >= ? AND outcome IN ('hit_target', 'hit_stop', 'neither')",
        conn, params=(since,),
    )
    if df.empty:
        return None

    total = len(df)
    hits = (df["outcome"] == backtest.HIT_TARGET).sum()
    overall_rate = hits / total * 100

    df["reason_tag"] = df["reasons_json"].apply(backtest.primary_reason_tag)
    grouped = df.groupby("reason_tag")["outcome"].agg(
        total="count", hits=lambda s: (s == backtest.HIT_TARGET).sum()
    )
    grouped["rate"] = (grouped["hits"] / grouped["total"] * 100).round(0)
    grouped = grouped.sort_values("rate", ascending=False)

    lines = [
        f"📊 <b>דוח שבועי - {days} ימים אחרונים</b>",
        "",
        f"סה\"כ {total} התראות עם תוצאה, {hits} מתוכן הגיעו ליעד ({overall_rate:.0f}%)",
        "",
        "<b>שיעור הצלחה לפי סיבה:</b>",
    ]
    for tag, row in grouped.iterrows():
        label = REASON_LABELS.get(tag, tag)
        lines.append(f"• {label}: {row['hits']:.0f}/{row['total']:.0f} ({row['rate']:.0f}%)")

    return "\n".join(lines)
