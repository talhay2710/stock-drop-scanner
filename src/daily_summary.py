"""סיכום יומי - הודעת טלגרם אחת בסוף יום המסחר: קודם סטטוס האחזקות שלך בפועל,
ואז רק ההתראות הכי בולטות מכל מדד (לא כל ההתראות של היום) - כדי שיהיה קריא
ומיקוד על מה שבאמת רלוונטי, במקום רשימה שטוחה של הכל.
"""
import datetime as dt
import sqlite3

from . import strategy as strategy_mod

INDEX_LABELS = {"SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "TA35": 'ת"א 35', "TA125": 'ת"א 125'}
REASON_UNCLEAR = "לא נמצאה סיבה ברורה"
# שורת תוכן אמיתית (לא רק \n/RLM סמויים) בסוף ההודעה - זה מה שבפועל תיקן
# (אומת בבדיקה חיה בטלגרם) את "בריחת" השורה האחרונה שמאלה. rstrip בלבד ו-RLM
# עוגן סמוי בסוף לא הספיקו - טלגרם צריך שהתוכן "האמיתי" האחרון לא יהיה
# הבולט/השורה עם ה-isolate שבסופה.
_FOOTER_LINE = "🤖 סורק מניות"


def _verdict_emoji(score: int) -> str:
    return "🟢" if score >= 70 else ("🟡" if score >= 45 else "🔴")


def _israeli_date(iso_date: str) -> str:
    """ISO (YYYY-MM-DD) -> פורמט ישראלי (DD/MM/YYYY), לתצוגה בהודעות טלגרם."""
    try:
        return dt.date.fromisoformat(iso_date).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso_date


def _signed(value: float, decimals: int = 1, suffix: str = "") -> str:
    """מספר עם סימן (+/-) שנשאר לפני המספר גם בתוך טקסט עברי (RTL) - עטוף ב-
    LRI/PDI (בידוד כיווניות LTR מפורש), לא רק LRM - LRM בודד התברר כלא אמין
    מספיק בטלגרם (ראו אותה הערה ב-scanner._signed; שם "נייס" "ברח" שמאלה)."""
    return f"⁦{value:+,.{decimals}f}{suffix}⁩"


def _isolate_rtl(text: str) -> str:
    """עוטף שם מניה (עברית) ב-RLI/PDI (בידוד כיווניות RTL מפורש) - כדי שיהיה
    run מבודד משלו, נפרד בבירור מה-LTR isolate הצמוד לו (_signed) לימינו.
    בלי זה, בשורות מסוימות (למשל "נייס" - שם קצר, 4 תווים) טלגרם מיזג את שני
    ה-runs הסמוכים בצורה שגרמה להיפוך סדר בין השם לאחוז. ה-RLM שבתחילת השורה
    (_rtl_line) לא נגע כאן בכוונה, כדי לא לשבור שוב את יישור ההודעה כולה -
    ה-RLM נשאר התו הראשון שטלגרם רואה כשהוא קובע כיוון/יישור לכל ההודעה."""
    return f"⁧{text}⁩"


def _rtl_line(text: str) -> str:
    """מוסיף RLM (סימן RTL, לא isolate) בתחילת השורה - ניסיון קודם עטף את כל
    השורה ב-RLI/PDI (isolate מלא) כדי לתקן שורה בודדת שבה "נייס" התהפכה עם
    האחוז, וזה אכן תיקן את סדר המילים - אבל שבר את יישור השורה כולה (isolate
    "מסתיר" את הטקסט העברי מהיוריסטיקה של טלגרם לקביעת כיוון/יישור הפסקה,
    שסורקת לפי התו החזק הראשון ב-stream הגולמי, לפני שנכנסים ל-isolate).
    RLM הוא סימן (לא isolate) - לא יוצר scope מבודד, רק מכריז RTL, ולכן לא
    אמור להסתיר את התוכן מהיוריסטיקה של טלגרם כמו שה-isolate עשה."""
    return f"‏{text}"


def _build_holdings_section(holdings: list[dict], closed_today: list[dict] | None = None) -> list[str]:
    """תיק בקצרה: שורת סיכום אחת (היום / מהכניסה) ושורה קצרה לכל אחזקה - שם ושינוי היום. closed_today משפיע על "היום"."""
    if not holdings and not closed_today:
        return []

    total_net = sum(h["net_pnl"] for h in holdings if h["net_pnl"] is not None)
    lines = ["💼 <b>התיק</b>"]
    today_values = [h["today_pnl"] for h in holdings if h.get("today_pnl") is not None]
    today_values += [c["today_pnl"] for c in (closed_today or []) if c.get("today_pnl") is not None]
    # שורה לכל סכום: היום, ושינוי כולל (מהכניסה)
    if today_values and len(today_values) == len(holdings) + len(closed_today or []):
        lines.append(f"היום {_signed(sum(today_values), 0)} ש\"ח")
    if holdings:
        lines.append(f"שינוי כולל {_signed(total_net, 0)} ש\"ח")
    lines.append("")
    for h in sorted(holdings, key=lambda h: h["net_pnl"] if h["net_pnl"] is not None else float("-inf"), reverse=True):
        emoji = "⚪" if h["net_pnl"] is None else ("🟢" if h["net_pnl"] >= 0 else "🔴")
        today = _signed(h["today_pct"], 1, "%") if h["today_pct"] is not None else "—"
        lines.append(f"{emoji} <b>{h['name']}</b>  {today}")
    lines.append("")
    return lines


def _build_closed_today_section(closed_today: list[dict]) -> list[str]:
    """עסקאות שנסגרו היום (מ-closed_trades) - שורה לכל מכירה, כדי שמכירה לא "תיעלם" מהסיכום."""
    if not closed_today:
        return []
    lines = ["💰 <b>נמכרו היום</b>"]
    for c in closed_today:
        name = c.get("company_name") or c["ticker"]
        net_pnl, net_pct = c.get("net_pnl"), c.get("net_pct")
        ccy_symbol = {"ILS": 'ש"ח', "USD": "$"}.get(c.get("currency"), c.get("currency") or "")
        if net_pnl is None or net_pct is None:
            lines.append(f"⚪ <b>{name}</b>")
            continue
        emoji = "🟢" if net_pnl >= 0 else "🔴"
        lines.append(f"{emoji} <b>{name}</b>  {_signed(net_pnl, 0)} {ccy_symbol}")
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
    """index_changes: {index_name: שינוי % של פרוקסי המדד} - שורה קצרה לכל מדד."""
    if not index_changes:
        return []
    lines = ["📊 <b>המדדים</b>"]
    for index_name, change in index_changes.items():
        label = INDEX_LABELS.get(index_name, index_name)
        if change is None:
            lines.append(f"⚪ {label}  —")
            continue
        emoji = "🟢" if change >= 0 else "🔴"
        lines.append(_rtl_line(f"{emoji} {_isolate_rtl(label)}  {_signed(change, 2, '%')}"))
    lines.append("")
    return lines


def _build_movers_section(movers_by_index: dict[str, list[dict]], top_n: int = 1) -> list[str]:
    """הכי עולה והכי יורדת בכל מדד (שורה לכל אחת) - תמונת מצב קצרה, לא קשור לסף התראה."""
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
            lines.append(_rtl_line(f"🟢 {_isolate_rtl(r['name'])}  {_signed(r['pct_change'], 1, '%')}"))
        for r in losers:
            lines.append(_rtl_line(f"🔴 {_isolate_rtl(r['name'])}  {_signed(r['pct_change'], 1, '%')}"))
        lines.append("")
    if not lines:
        return []
    return ["🔝 <b>בולטות</b>"] + lines


def build_morning_summary(
    scan_date: str, index_changes: dict[str, float | None], holdings: list[dict] | None,
    movers_by_index: dict[str, list[dict]], top_n_movers: int = 1,
) -> str | None:
    """'תחילת יום' בקצרה: מדדים, התיק (אותו חלק כמו בסיכום היומי) והמניות הבולטות. snapshot חי של המחירים ברגע השליחה.
    מחזיר None אם אין שום נתון."""
    if not index_changes and not holdings and not any(movers_by_index.values()):
        return None

    lines = [f"🌅 <b>תחילת יום</b> · {_israeli_date(scan_date)}", ""]
    lines.extend(_build_index_section(index_changes))
    lines.extend(_build_holdings_section(holdings or []))
    lines.extend(_build_movers_section(movers_by_index, top_n_movers))
    # שורה אחרונה בעברית רגילה: בלעדיה טלגרם מיישר את השורה האחרונה (שנגמרת במספר) שמאלה
    lines.append("נכון לפתיחת המסחר")
    return "\n".join(lines).rstrip()


def _build_quality_section(conn: sqlite3.Connection, scan_date: str) -> list[str]:
    """תקציר איכות נתונים: לכל מדד - כמה סריקות רצו היום, הפער הגדול ביותר ביניהן, וכמה מניות נפסלו לכל היותר בסריקה
    (נתון ישן / מחיר דל). מסתיר את עצמו כשאין נתונים (ימים שלפני שהרישום נוסף)."""
    try:
        rows = conn.execute(
            "SELECT index_name, scan_ts, stale, thin, total FROM scan_quality WHERE scan_date = ? ORDER BY scan_ts",
            (scan_date,),
        ).fetchall()
    except sqlite3.Error:
        return []
    if not rows:
        return []
    import datetime as _dt
    by_index: dict[str, list] = {}
    for r in rows:
        by_index.setdefault(r[0], []).append(r)
    lines = ["🩺 <b>איכות נתונים</b>"]
    for index_name, rs in by_index.items():
        stamps = []
        for r in rs:
            try:
                stamps.append(_dt.datetime.fromisoformat(r[1]))
            except ValueError:
                pass
        gap = max(((b - a).total_seconds() / 60 for a, b in zip(stamps, stamps[1:])), default=0)
        max_stale = max((r[2] or 0) for r in rs)
        max_thin = max((r[3] or 0) for r in rs)
        extra = []
        if max_stale:
            extra.append(f"נתון ישן עד {max_stale}")
        if max_thin:
            extra.append(f"מחיר דל עד {max_thin}")
        tail = f" · נפסלו (מקס' בסריקה): {', '.join(extra)}" if extra else ""
        lines.append(f"{INDEX_LABELS.get(index_name, index_name)}: {len(rs)} סריקות · פער מקס' {gap:.0f} דק'{tail}")
    lines.append("")
    return lines


def build_daily_summary(
    conn: sqlite3.Connection, scan_date: str,
    holdings: list[dict] | None = None, top_n_per_index: int = 2,
    closed_today: list[dict] | None = None,
) -> str | None:
    """בונה טקסט סיכום יומי: קודם האחזקות שלך, אחר כך מכירות שנסגרו היום ממש
    (אם היו), אחר כך top_n_per_index ההתראות הכי בולטות (לפי ציון תגובת-יתר)
    מכל מדד שנסרק, ולבסוף 1-2 מניות "לשים לב" ליום הבא (לא מתוך האחזקות
    שלך). מחזיר None אם אין התראות, אין אחזקות, ואין מכירות מהיום."""
    cur = conn.execute(
        "SELECT ticker, company_name, index_name, pct_change, scan_ts, intraday_recovery_pct, dist_from_ma50_pct, sector "
        "FROM alerts WHERE scan_date = ? AND index_name != 'SP500'",  # S&P לא מוצג בסיכום היומי
        (scan_date,),
    )
    columns = [c[0] for c in cur.description]
    rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    if not rows and not holdings and not closed_today:
        return None

    lines = [f"📅 <b>סיכום יומי</b> · {_israeli_date(scan_date)}", ""]
    lines.extend(_build_holdings_section(holdings or [], closed_today))
    lines.extend(_build_closed_today_section(closed_today or []))

    if rows:
        owned_tickers = {h["ticker"] for h in (holdings or [])}
        scored = []
        for r in rows:
            try:
                hour = int(str(r["scan_ts"])[11:13])
            except (ValueError, TypeError):
                hour = None
            score = strategy_mod.signal_score(
                r["index_name"], r["pct_change"], r["intraday_recovery_pct"], r["dist_from_ma50_pct"], r["sector"], hour,
            )[0]
            sig = (strategy_mod.SIGNAL_BUY if score >= strategy_mod.buy_min_score()
                   else strategy_mod.SIGNAL_WAIT if score >= strategy_mod.wait_min_score() else strategy_mod.SIGNAL_AVOID)
            scored.append((score, sig, r))
        counts = {s: sum(1 for t in scored if t[1] == s) for s in (strategy_mod.SIGNAL_BUY, strategy_mod.SIGNAL_WAIT, strategy_mod.SIGNAL_AVOID)}
        lines.append(f"🔎 <b>{len(rows)} התראות</b>")
        lines.append("  ·  ".join(f"{strategy_mod.SIGNAL_EMOJI[s]} {n}" for s, n in counts.items()))
        # הבולטת: הניקוד הגבוה ביותר (אחזקות שכבר ברשותך לא נספרות)
        best = [t for t in sorted(scored, key=lambda t: t[0], reverse=True) if t[2]["ticker"] not in owned_tickers][:1]
        for score, sig, r in best:
            name = r["company_name"] or r["ticker"]
            lines.append(f"הבולטת: <b>{name}</b> {_signed(r['pct_change'], 1, '%')}  ({max(score, 0)}/{strategy_mod.MAX_SIGNAL_SCORE})")
        lines.append("")

    return "\n".join(lines).rstrip()