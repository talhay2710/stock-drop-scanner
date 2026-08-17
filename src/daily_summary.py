"""סיכום יומי - הודעת טלגרם אחת בסוף יום המסחר: קודם סטטוס האחזקות שלך בפועל,
ואז רק ההתראות הכי בולטות מכל מדד (לא כל ההתראות של היום) - כדי שיהיה קריא
ומיקוד על מה שבאמת רלוונטי, במקום רשימה שטוחה של הכל.
"""
import sqlite3

INDEX_LABELS = {"SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "TA35": 'ת"א 35', "TA125": 'ת"א 125'}
REASON_UNCLEAR = "לא נמצאה סיבה ברורה"


def _verdict_emoji(score: int) -> str:
    return "🟢" if score >= 70 else ("🟡" if score >= 45 else "🔴")


def _signed(value: float, decimals: int = 1, suffix: str = "") -> str:
    return f"‎{value:+,.{decimals}f}{suffix}"


def _build_holdings_section(holdings: list[dict]) -> list[str]:
    """holdings: רשימת dict-ים עם ticker, name, net_pnl, net_pct, ccy_symbol,
    today_pct (שינוי המניה היום בלבד, לא קשור לתאריך הקנייה). רק מה שקרה היום
    ואיפה זה עומד מול נקודת הכניסה - בלי היסטוריה/טרק-רקורד."""
    if not holdings:
        return []

    total_net = sum(h["net_pnl"] for h in holdings if h["net_pnl"] is not None)
    total_word = "ברווח" if total_net >= 0 else "בהפסד"
    lines = ["💼 <b>האחזקות שלך</b>", f"היום אתם {total_word} של {abs(total_net):,.0f} ש\"ח בסך הכל", ""]
    for h in sorted(holdings, key=lambda h: h["net_pnl"] if h["net_pnl"] is not None else float("-inf"), reverse=True):
        if h["net_pnl"] is None:
            lines.append(f"⚪ <b>{h['name']}</b> - אין כרגע מחיר עדכני")
            continue
        emoji = "🟢" if h["net_pnl"] >= 0 else "🔴"
        today_part = f"היום {_signed(h['today_pct'], 1, '%')}" if h["today_pct"] is not None else "אין נתון על היום"
        since_verb = "מעל" if h["net_pnl"] >= 0 else "מתחת ל"
        lines.append(
            f"{emoji} <b>{h['name']}</b> - {today_part}, {since_verb} נקודת הכניסה שלך "
            f"ב-{abs(h['net_pct']):.1f}% ({_signed(h['net_pnl'], 0)} {h['ccy_symbol']})"
        )
    lines.append("")
    return lines


def _build_watch_section(rows: list[dict], excluded_tickers: set[str], top_n: int = 2) -> list[str]:
    """1-2 מניות מכל ההתראות של היום, לפי ציון תגובת-יתר הכי גבוה - "שווה לשים
    לב" ליום המסחר הבא, עם הלימיט שהמערכת חישבה. לא כולל מה שכבר יש לך (owned)
    ולא מה שכבר הוזכר למעלה ב"הבולטות" (excluded_tickers כולל את שניהם)."""
    candidates = [r for r in rows if r["ticker"] not in excluded_tickers and r["overreaction_score"] >= 45]
    top = sorted(candidates, key=lambda r: r["overreaction_score"], reverse=True)[:top_n]
    if not top:
        return []

    lines = ["👀 <b>שווה לשים לב מחר</b>", ""]
    for r in top:
        display_name = r["company_name"] or r["ticker"]
        main_reason = (r["reason_text"] or "").split(" | ")[0]
        reason_part = f" - {main_reason}" if main_reason and main_reason != REASON_UNCLEAR else ""
        lines.append(
            f"{_verdict_emoji(r['overreaction_score'])} <b>{display_name}</b> ({r['ticker']}) "
            f"ירדה {abs(r['pct_change']):.1f}%{reason_part}. לימיט כניסה: {r['entry_limit']:,.2f}"
        )
    lines.append("")
    return lines


def _build_index_section(index_changes: dict[str, float | None]) -> list[str]:
    """index_changes: {index_name: שינוי % של פרוקסי המדד} - איך נפתח/עומד המסחר
    ברמת המדד עצמו, לפני שיורדים לרמת האחזקות/מניות בודדות."""
    if not index_changes:
        return []
    lines = ["📊 <b>המדדים</b>", ""]
    for index_name, change in index_changes.items():
        if change is None:
            lines.append(f"⚪ {INDEX_LABELS.get(index_name, index_name)} - אין נתון")
            continue
        emoji = "🟢" if change >= 0 else "🔴"
        lines.append(f"{emoji} {INDEX_LABELS.get(index_name, index_name)} {_signed(change, 2, '%')}")
    lines.append("")
    return lines


def _build_movers_section(movers_by_index: dict[str, list[dict]], top_n: int = 3) -> list[str]:
    """movers_by_index: {index_name: [{"ticker", "name", "pct_change"}, ...]} - שורה
    לכל מניה במדד, ללא מיון מוקדם. בוחר את top_n העולות וtop_n היורדות ביותר מכל
    מדד - תמונת מצב מיידית של מי זז הכי הרבה, לא קשור לסף התראה כלשהו."""
    lines: list[str] = []
    for index_name, rows in movers_by_index.items():
        if not rows:
            continue
        sorted_rows = sorted(rows, key=lambda r: r["pct_change"], reverse=True)
        gainers = sorted_rows[:top_n]
        losers = [r for r in sorted_rows[-top_n:] if r not in gainers]
        if not gainers and not losers:
            continue
        lines.append(f"<b>{INDEX_LABELS.get(index_name, index_name)}</b>")
        for r in gainers:
            lines.append(f"🟢 {r['name']} {_signed(r['pct_change'], 2, '%')}")
        for r in losers:
            lines.append(f"🔴 {r['name']} {_signed(r['pct_change'], 2, '%')}")
        lines.append("")
    if not lines:
        return []
    return ["🔝 <b>מניות בולטות</b>", ""] + lines


def build_morning_summary(
    scan_date: str, index_changes: dict[str, float | None], holdings: list[dict] | None,
    movers_by_index: dict[str, list[dict]], top_n_movers: int = 3,
) -> str | None:
    """בונה טקסט 'תמונת מצב - תחילת יום': איך נפתח המסחר ברמת המדד, אחר כך
    האחזקות שלך (אותו חלק בדיוק כמו בסיכום היומי), ולבסוף המניות הכי בולטות
    (עולות/יורדות) בכל מדד שנסרק. בניגוד ל-build_daily_summary זה לא מתבסס על
    טבלת alerts (התראות שכבר נשלחו) - זה snapshot חי של המחירים ברגע השליחה,
    לתחילת יום המסחר. מחזיר None אם אין שום נתון (לא מדדים, לא אחזקות, לא מניות בולטות)."""
    if not index_changes and not holdings and not any(movers_by_index.values()):
        return None

    lines = [f"🌅 <b>תמונת מצב - תחילת יום ({scan_date})</b>", ""]
    lines.extend(_build_index_section(index_changes))
    lines.extend(_build_holdings_section(holdings or []))
    lines.extend(_build_movers_section(movers_by_index, top_n_movers))
    return "\n".join(lines)


def build_daily_summary(
    conn: sqlite3.Connection, scan_date: str,
    holdings: list[dict] | None = None, top_n_per_index: int = 2,
) -> str | None:
    """בונה טקסט סיכום יומי: קודם האחזקות שלך, אחר כך top_n_per_index ההתראות
    הכי בולטות (לפי ציון תגובת-יתר) מכל מדד שנסרק, ולבסוף 1-2 מניות "לשים לב"
    ליום הבא (לא מתוך האחזקות שלך). מחזיר None אם אין התראות ואין אחזקות."""
    cur = conn.execute(
        "SELECT ticker, company_name, index_name, pct_change, overreaction_score, "
        "reason_text, entry_limit FROM alerts WHERE scan_date = ?",
        (scan_date,),
    )
    columns = [c[0] for c in cur.description]
    rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    if not rows and not holdings:
        return None

    owned_tickers = {h["ticker"] for h in (holdings or [])}

    lines = [f"📅 <b>סיכום יומי - {scan_date}</b>", ""]
    lines.extend(_build_holdings_section(holdings or []))

    if rows:
        by_index: dict[str, list[dict]] = {}
        for r in rows:
            by_index.setdefault(r["index_name"], []).append(r)

        shown_tickers = set(owned_tickers)
        lines.append(f"🔎 <b>ההתראות הבולטות ({len(rows)} סה\"כ)</b>")
        for index_name, idx_rows in by_index.items():
            top_rows = sorted(idx_rows, key=lambda r: r["overreaction_score"], reverse=True)[:top_n_per_index]
            lines.append("")
            lines.append(f"<b>{INDEX_LABELS.get(index_name, index_name)}</b>")
            for r in top_rows:
                display_name = r["company_name"] or r["ticker"]
                main_reason = (r["reason_text"] or "").split(" | ")[0]
                reason_part = f" - {main_reason}" if main_reason and main_reason != REASON_UNCLEAR else ""
                verb = "עלתה" if r["pct_change"] >= 0 else "ירדה"
                lines.append(f"{_verdict_emoji(r['overreaction_score'])} <b>{display_name}</b> {verb} {abs(r['pct_change']):.1f}%{reason_part}")
                shown_tickers.add(r["ticker"])
        lines.append("")

        lines.extend(_build_watch_section(rows, shown_tickers))

    return "\n".join(lines)
