"""עיצוב v3 ("Ivory + Radar") - פונקציות טהורות שבונות HTML/SVG, בלי תלות ב-Streamlit (נבדקות ב-tests/test_core.py).

המקור לכל מבנה ועיצוב: המוקאפים שאושרו טאב-אחר-טאב (ר' project_site_redesign_studio). כל ה-HTML מוחזר כמחרוזת *בלי שורות ריקות
ובלי הזחה בתחילת שורה* - אחרת מרקדאון של Streamlit שובר את בלוק ה-HTML (שורה ריקה) או הופך אותו לקוד (הזחה).
"""
from __future__ import annotations

import html
import math
import re

CCY_SYMBOL = {"ILS": "₪", "USD": "&#36;"}


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


_STOP_SHORT = {"בית", "הון", "קרן", "ים", "בע\"מ", "חב'"}
_GENERIC_FIRST = {"בנק", "קבוצת", "חברת", "הבנק", "בית", "קרן", "The", "Bank"}


def short_name(name) -> str:
    """שם מניה מקוצר: מילה אחת ("אלביט מערכות" -> "אלביט", "Intel Corporation" -> "Intel").
    אם המילה הראשונה כללית (בנק, קבוצת...) לוקחים גם את השנייה ("בנק הפועלים")."""
    text = str(name if name is not None else "").strip()
    if not text:
        return ""
    words = re.split(r"\s+", text)
    first = words[0].strip(",.;")
    if first in _GENERIC_FIRST and len(words) > 1:
        return f"{first} {words[1].strip(',.;')}"
    # שם עברי שמורכב מאותיות מילוליות קצרות ("איי סי אל", "אי בי אי") - לוקחים את כולן ולא רק "איי"
    if len(first) <= 3 and re.search(r"[֐-׿]", first):
        out = [first]
        for w in words[1:]:
            w = w.strip(",.;")
            if len(w) <= 3 and w not in _STOP_SHORT and re.search(r"[֐-׿]", w):
                out.append(w)
            else:
                break
        return " ".join(out)
    return first


def num(text) -> str:
    """מספר/אחוז כיחידה LTR מבודדת - הסימן (+/-/%) נשאר צמוד למספר גם בתוך טקסט עברי."""
    return f'<span class="num">{esc(text)}</span>'


def signed(value: float, decimals: int = 0, suffix: str = "") -> str:
    return f"{value:+,.{decimals}f}{suffix}"


def plain(value: float, decimals: int = 0, suffix: str = "") -> str:
    return f"{value:,.{decimals}f}{suffix}"


def snum(value: float, decimals: int = 0, suffix: str = "") -> str:
    """מספר עם סימן, צבוע לפי הסימן: מינוס אדום, פלוס ירוק (כלל כללי באתר)."""
    return f'<span class="{cls_for(value)}">{num(signed(value, decimals, suffix))}</span>'


def cls_for(value: float | None) -> str:
    if value is None:
        return ""
    return "up" if value >= 0 else "down"


def head(title: str, side: str = "") -> str:
    return f'<div class="head"><div class="h2">{esc(title)}</div>{side}</div>'


def fmt_countdown(minutes: int) -> str:
    """כמו ב-JS של המוקאפ: 'יום ו־3 שעות' / '3 שעות ו־12 דקות' / '12 דקות' (יחיד: שעה/דקה/יום)."""
    minutes = max(int(minutes), 0)
    d, rem = divmod(minutes, 1440)
    h, m = divmod(rem, 60)
    hs = "שעה" if h == 1 else f"{h} שעות"
    if d > 0:
        return ("יום" if d == 1 else f"{d} ימים") + " ו־" + hs
    if h > 0:
        return hs + " ו־" + ("דקה" if m == 1 else f"{m} דקות")
    return "דקה" if m == 1 else f"{m} דקות"


# ───────────────────────── עמוד הבית ─────────────────────────

def notice(name: str, gap_pct: float, is_target: bool) -> str:
    """שורת התראה אחת: אחזקה שחצתה סטופ (אדום) או יעד (ירוק). בלי כותרת "דורש תשומת לב"."""
    what = "עברה את היעד" if is_target else "חצתה את הסטופ-לוס"
    color = "var(--gain)" if is_target else "var(--loss)"
    return (
        f'<div class="notice"><i style="background:{color}"></i>'
        f'<span><b>{esc(short_name(name))}</b> {what} ב־{num(f"{abs(gap_pct):.1f}%")}</span></div>'
    )


def portfolio_strip(value: float, count: int, pnl: float, pnl_pct: float,
                    day_change: float | None, day_pct: float | None, ccy: str, day_label: str = "שינוי יומי") -> str:
    sym = CCY_SYMBOL.get(ccy, esc(ccy))
    cells = [
        f'<div><small>שווי תיק</small><strong>{num(plain(value))}&nbsp;{sym}'
        f'<em style="color:var(--dim)">{num(count)} אחזקות</em></strong></div>',
        f'<div><small>רווח/הפסד</small><strong class="{cls_for(pnl)}">{num(signed(pnl))}&nbsp;{sym}'
        f'<em>{num(signed(pnl_pct, 1, "%"))}</em></strong></div>',
    ]
    if day_change is not None and day_pct is not None:
        cells.append(
            f'<div><small>{esc(day_label)}</small><strong class="{cls_for(day_change)}">{num(signed(day_change))}&nbsp;{sym}'
            f'<em>{num(signed(day_pct, 1, "%"))}</em></strong></div>'
        )
    return f'{head("התיק שלי")}<div class="kpi">{"".join(cells)}</div>'


_RING = (
    '<svg viewBox="0 0 420 420" aria-hidden="true"><g fill="var(--rule)" fill-opacity=".07">'
    '<circle cx="210" cy="210" r="196"/><circle cx="210" cy="210" r="147"/><circle cx="210" cy="210" r="98"/>'
    '<circle cx="210" cy="210" r="49"/></g><g fill="none" stroke="var(--dash)" stroke-width="2.5" stroke-linecap="round">'
    '<circle cx="210" cy="210" r="196" opacity=".5"/><circle cx="210" cy="210" r="147" opacity=".42"/>'
    '<circle cx="210" cy="210" r="98" opacity=".34"/><circle cx="210" cy="210" r="49" opacity=".26"/></g>'
    '<g class="sweep"><line x1="210" y1="210" x2="350" y2="70" stroke="var(--accent)" stroke-width="4.5" stroke-linecap="round" opacity=".9"/>'
    '<circle cx="350" cy="70" r="21" fill="var(--accent)" fill-opacity=".14"/><circle cx="350" cy="70" r="11" fill="var(--accent)"/></g></svg>'
)


def scanner_radar(state: str, minutes: float | None) -> str:
    """הרדאר העצמאי = מצב הסורק. state: ok | late | dead (ר' src/scan_status.py)."""
    title = {"ok": "הסורק פעיל", "late": "הסורק מאחר", "dead": "הסורק לא פעיל"}[state]
    dot = {"ok": "var(--gain)", "late": "var(--loss)", "dead": "var(--dot-off)"}[state]
    if minutes is None:
        ago = "אין נתון על הסריקה האחרונה"
    else:
        m = int(minutes)
        ago = "סריקה אחרונה " + ("הרגע" if m == 0 else ("לפני דקה" if m == 1 else (f"לפני {m} דקות" if m < 120 else f"לפני {m // 60} שעות")))
    return (
        f'<div class="radar-solo {"" if state == "ok" else state}">{_RING}'
        f'<div class="scan" role="status"><span class="scan-t"><i class="dot" style="background:{dot}"></i><b>{title}</b></span>'
        f'<small>{ago}</small></div></div>'
    )


def top_zone(notice_html: str, strip_html: str, radar_html: str) -> str:
    return f'<div class="topzone"><div class="topmain">{notice_html}<div style="height:44px"></div>{strip_html}</div>{radar_html}</div>'


# רדאר האחזקות: ציר אחד באחוזי רווח/הפסד (שמאל = הפסד, ימין = רווח), טבעות ב־3/6/9%, 17.67px לאחוז
_CX = _CY = 190.0
_PX_PER_PCT = 53.0 / 3.0
_R_MAX = 172.0


def _spread(n: int, lo: float, hi: float) -> list[float]:
    if n <= 0:
        return []
    if n == 1:
        return [(lo + hi) / 2]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def radar_positions(rows: list[dict]) -> list[dict]:
    """מוסיף לכל שורה x/y/label_y/out לפי pnl_pct ו-stop_pct האישי (ההילה האדומה = חצתה את הסטופ של עצמה)."""
    losers = sorted([r for r in rows if r["pnl_pct"] < 0], key=lambda r: -r["pnl_pct"])
    winners = sorted([r for r in rows if r["pnl_pct"] >= 0], key=lambda r: -r["pnl_pct"])
    placed = []
    for group, lo, hi in ((losers, 128.0, 235.0), (winners, 50.0, -50.0)):
        for r, ang in zip(group, _spread(len(group), lo, hi)):
            rad = min(abs(r["pnl_pct"]) * _PX_PER_PCT, _R_MAX)
            theta = math.radians(ang)
            x = _CX + rad * math.cos(theta)
            y = _CY - rad * math.sin(theta)
            stop = r.get("stop_pct")
            out = stop is not None and r["pnl_pct"] < stop
            placed.append({**r, "x": x, "y": y, "out": out, "below": y > 300})
    return placed


def holdings_radar(rows: list[dict]) -> str:
    placed = radar_positions(rows)
    halo = "paint-order:stroke; stroke:var(--bg); stroke-width:5px; stroke-linejoin:round"
    dots = []
    for p in placed:
        label = esc(short_name(p["name"]))
        ly = p["y"] - (24 if p["out"] else 16)  # תמיד מעל הנקודה (אחידות); מעל ההילה כשיש הילה
        if p["out"]:
            dots.append(
                f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="8" fill="var(--loss)" stroke="none"/>'
                f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="15" fill="none" stroke="var(--loss)" opacity=".55"/>'
                f'<text x="{p["x"]:.0f}" y="{ly:.0f}" fill="var(--loss)" font-size="14" font-weight="600">{label}</text>'
            )
        else:
            dots.append(
                f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="6" fill="var(--ink)" stroke="none"/>'
                f'<text x="{p["x"]:.0f}" y="{ly:.0f}" fill="var(--ink)">{label}</text>'
            )
    n_out = sum(1 for p in placed if p["out"])
    aria = "רדאר אחזקות לפי רווח והפסד. צד שמאל הפסד, צד ימין רווח." + (f" {n_out} אחזקות חצו את הסטופ שלהן." if n_out else "")
    return (
        f'<figure class="plot"><svg style="overflow:visible" viewBox="0 0 380 392" role="img" aria-label="{esc(aria)}">'
        '<circle cx="190" cy="190" r="53" fill="none" stroke="var(--rule)"/><circle cx="190" cy="190" r="106" fill="none" stroke="var(--rule)"/>'
        '<circle cx="190" cy="190" r="158" fill="none" stroke="var(--rule)"/>'
        '<line x1="190" y1="14" x2="190" y2="366" stroke="var(--rule)"/><line x1="14" y1="190" x2="366" y2="190" stroke="var(--rule)"/>'
        '<path d="M190 14 A176 176 0 0 0 190 366" fill="none" stroke="var(--loss)" stroke-width="1" stroke-dasharray="4 5" opacity=".35"/>'
        '<path d="M190 137 A53 53 0 0 1 190 243" fill="none" stroke="var(--gain)" stroke-width="1.5" stroke-dasharray="4 5"/>'
        '<g style="direction:ltr; unicode-bidi:bidi-override; paint-order:stroke; stroke:var(--bg); stroke-width:4px; stroke-linejoin:round" '
        'font-size="10" font-family="IBM Plex Mono, monospace" text-anchor="middle">'
        '<text x="137" y="185" fill="var(--loss)">-3%</text><text x="84" y="185" fill="var(--loss)">-6%</text><text x="32" y="185" fill="var(--loss)">-9%</text>'
        '<text x="243" y="185" fill="var(--gain)">+3%</text><text x="296" y="185" fill="var(--gain)">+6%</text><text x="348" y="185" fill="var(--gain)">+9%</text></g>'
        f'<text x="222" y="130" text-anchor="middle" style="{halo}; stroke-width:6px" fill="var(--gain)" font-size="13" font-weight="600" font-family="Heebo, sans-serif">יעד</text>'
        '<circle cx="190" cy="190" r="2.5" fill="var(--dim)"/>'
        f'<g style="{halo}" text-anchor="middle" font-family="Heebo, sans-serif" font-size="13">{"".join(dots)}</g></svg></figure>'
    )


def holdings_rows(rows: list[dict]) -> str:
    out = []
    for r in sorted(rows, key=lambda r: -r["pnl_pct"]):
        is_out = r.get("stop_pct") is not None and r["pnl_pct"] < r["stop_pct"]
        daily = r.get("daily_pct")
        if daily is None:
            daily_html = '<span class="st"></span>'
        else:
            daily_html = f'<span class="st {cls_for(daily)}">{num(signed(daily, 1, "%"))} היום</span>'
        out.append(
            f'<div class="row{" out" if is_out else ""}"><span class="nm" title="{esc(r["name"])}">{esc(short_name(r["name"]))}</span>'
            f'<span class="pl {cls_for(r["pnl_pct"])}">{num(signed(r["pnl_pct"], 1, "%"))}</span>{daily_html}</div>'
        )
    return '<div class="rows"><div class="cap">רווח/הפסד מנקודת הקנייה</div>' + "".join(out) + "</div>"


def holdings_section(rows: list[dict]) -> str:
    return f'<section class="block">{head("אחזקות")}<div class="hold">{holdings_radar(rows)}{holdings_rows(rows)}</div></section>'


def intraday_chart(series: list[tuple[str, list[float]]], times: list[str], portfolio_label: str, bench_label: str) -> str:
    """series: [(label, values)] - הראשון התיק (קו מלא), השני המדד (מקווקו). times: תוויות הציר (5 נקודות)."""
    all_vals = [v for _, vals in series for v in vals]
    if not all_vals:
        return ""
    # ציר Y לפי הטווח בפועל (כולל 0) - לא סימטרי סביב האפס, כדי שהגרף ימלא את האזור ולא יישאר חלל ריק מתחתיו
    lo, hi = min(min(all_vals), 0.0), max(max(all_vals), 0.0)
    if hi - lo < 0.1:
        lo, hi = lo - 0.05, hi + 0.05
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    H, TOP, SPAN = 150, 8, 134

    def yv(v: float) -> float:
        return TOP + (hi - v) / (hi - lo) * SPAN

    def pts(vals: list[float]) -> str:
        n = len(vals)
        return " ".join(f"{(i * 900 / max(n - 1, 1)):.1f},{yv(v):.1f}" for i, v in enumerate(vals))

    y0 = yv(0.0)
    # קו ה-0% רק כשהוא באמת בתוך הגרף; כשהוא צמוד לתחתית הוא נראה כמו קו הפרדה מעל השעות - את ההפרדה נותן הקו שמתחת לשעות
    show_zero = y0 < TOP + SPAN - 18
    zero_line = f'<line x1="0" y1="{y0:.1f}" x2="900" y2="{y0:.1f}" stroke="var(--rule)"/>' if show_zero else ""

    lines = (
        f'<polyline vector-effect="non-scaling-stroke" points="{pts(series[0][1])}" fill="none" stroke="var(--accent)" stroke-width="2"/>'
    )
    if len(series) > 1:
        lines += (
            f'<polyline vector-effect="non-scaling-stroke" points="{pts(series[1][1])}" fill="none" stroke="var(--dash)" '
            'stroke-width="1.5" stroke-dasharray="6 5"/>'
        )
    legend = f'<div class="legend"><span>{esc(portfolio_label)}<i></i></span><span>{esc(bench_label)}<i class="d"></i></span></div>'
    ticks = "".join(f"<span>{esc(t)}</span>" for t in times)
    return (
        f'<section class="block">{head("תשואה תוך-יומית", legend)}<div class="chart">{f'<span class="zero" style="top:{y0 - 17:.0f}px; transform:none">0%</span>' if show_zero else ""}'
        f'<svg viewBox="0 0 {900} {H}" preserveAspectRatio="none" role="img" aria-label="{esc(portfolio_label)} מול {esc(bench_label)}">'
        f'{zero_line}{lines}</svg><div class="times">{ticks}</div></div></section>'
    )


def hours_section(markets: list[dict]) -> str:
    """markets: [{name, open: bool, minutes: int}] - 'פתוח'/'סגור' + 'נסגר/נפתח בעוד ...'."""
    items = []
    for m in markets:
        stt = '<span class="stt up">השוק פתוח</span>' if m["open"] else '<span class="stt">השוק סגור</span>'
        cd = ("נסגר בעוד " if m["open"] else "נפתח בעוד ") + fmt_countdown(m["minutes"])
        items.append(f'<div class="li"><span>{esc(m["name"])}</span><span class="mk">{stt}<small class="cd">{cd}</small></span></div>')
    return f'<div class="hours">{head("זמני מסחר")}{"".join(items)}</div>'


def news_section(items: list[dict]) -> str:
    rows = []
    for it in items:
        title = esc(it.get("title") or "")
        src = esc(it.get("source") or "")
        link = it.get("link")
        inner = f'<div>{title}</div><small>{src}</small>'
        if link:
            rows.append(f'<a class="nw" href="{esc(link)}" target="_blank" rel="noopener">{inner}</a>')
        else:
            rows.append(f'<div class="nw">{inner}</div>')
    body = "".join(rows) if rows else '<div class="nw"><small>לא נמצאו חדשות כרגע.</small></div>'
    return f'<div class="news">{head("חדשות כלכליות")}{body}</div>'


def hours_and_news(hours_html: str, news_html: str) -> str:
    return f'<div class="cols">{hours_html}{news_html}</div>'


def home_footer() -> str:
    return '<div class="foot"><span>DipRadar</span><span>נתונים: Yahoo Finance</span></div>'


# ───────────────────────── CSS משותף ─────────────────────────

COMPONENT_CSS = """
        .v3h { --bg:var(--v3-bg); --ink:var(--v3-ink); --dim:var(--v3-dim); --rule:var(--v3-rule); --accent:var(--v3-accent);
               --gain:var(--v3-gain); --loss:var(--v3-loss); --hover:var(--v3-hover); --surface:var(--v3-surface);
               --rule-strong:var(--v3-rule-strong); --dash:var(--v3-dash); --dot-off:var(--v3-dot-off); --font-mono:'IBM Plex Mono',ui-monospace,monospace;
               color:var(--ink); font-variant-numeric:tabular-nums; line-height:1.5; font-size:16px; }
        .v3h .num { direction:ltr; unicode-bidi:isolate; display:inline-block; }
        .v3h .mono { font-family:var(--font-mono); font-size:11px; letter-spacing:.08em; color:var(--dim); }
        .v3h .up { color:var(--gain); } .v3h .down { color:var(--loss); }
        .v3h a { color:inherit; text-decoration:none; }
        .v3h .head { display:flex; justify-content:space-between; align-items:baseline; gap:8px 24px; flex-wrap:wrap; padding-bottom:12px; border-bottom:1px solid var(--rule-strong); }
        .v3h .head .h2 { font-weight:500; font-size:18px; line-height:1.5; }
        .v3h .block { margin-top:48px; }
        .v3h .kpi { display:grid; grid-template-columns:1.8fr 1fr 1fr; border-bottom:1px solid var(--rule); }
        .v3h .kpi > div { padding:18px 18px 20px; border-inline-start:1px solid var(--rule); min-width:0; display:flex; flex-direction:column; }
        .v3h .kpi > div:first-child { padding-inline-start:0; border-inline-start:0; }
        .v3h .kpi small { display:block; font-size:13px; color:var(--dim); }
        .v3h .kpi strong { display:block; font-size:clamp(22px,2.5vw,30px); font-weight:400; line-height:1.2; margin-top:4px; white-space:nowrap; }
        .v3h .kpi em { display:block; margin-top:2px; font-style:normal; font-size:15px; line-height:1.4; }
        .v3h .kpi > div:first-child em { font-size:14px; }
        .v3h .kpi > div:not(:first-child) em .num { font-size:16px; }
        .v3h .notice { display:flex; align-items:center; flex-wrap:wrap; gap:6px 14px; padding:12px 16px; border:1px solid var(--rule); border-radius:6px; background:var(--surface); font-size:15px; }
        .v3h .notice i { width:8px; height:8px; display:inline-block; }
        .v3h .notice b { font-weight:600; }
        .v3h .topzone { display:flex; align-items:center; gap:56px; margin-top:24px; }
        .v3h .topmain { flex:1 1 auto; min-width:0; }
        .v3h .radar-solo { flex:none; width:230px; }
        .v3h .radar-solo svg { display:block; width:100%; height:auto; }
        .v3h .sweep { transform-origin:210px 210px; animation:v3sweep 48s linear infinite; }
        @keyframes v3sweep { to { transform:rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) { .v3h .sweep { animation:none; } }
        .v3h .scan { margin-top:12px; text-align:center !important; font-size:14px; }
        .v3h .scan small { display:block; margin-top:2px; font-size:13px; color:var(--dim); text-align:center !important; }
        .v3h .scan b { font-weight:500; }
        .v3h .dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-inline-end:7px; background:var(--dot-off); }
        .v3h .radar-solo.late { --accent:var(--loss); }
        .v3h .radar-solo.late .sweep, .v3h .radar-solo.dead .sweep { animation:none; }
        .v3h .radar-solo.dead { --accent:var(--dim); }
        .v3h .hold { display:flex; flex-wrap:wrap; gap:0 64px; }
        .v3h .plot { flex:1 1 320px; max-width:440px; padding-top:24px; margin:0; }
        .v3h .plot svg { display:block; width:100%; height:auto; }
        .v3h .rows { flex:1 1 380px; min-width:0; padding-top:12px; }
        .v3h .rows .cap { font-size:13px; color:var(--dim); padding:14px 0 10px; border-bottom:1px solid var(--rule); }
        .v3h .row { display:grid; grid-template-columns:1fr 84px 128px; align-items:center; gap:12px; padding:18px 10px; border-bottom:1px solid var(--rule); }
        .v3h .row:hover { background:var(--hover); }
        .v3h .row .nm { font-size:17px; }
        .v3h .row .pl { font-size:17px; }
        .v3h .row .st { font-size:14px; color:var(--dim); }
        .v3h .row .st.up { color:var(--gain); } .v3h .row .st.down { color:var(--loss); }
        .v3h .row.out .nm { font-weight:600; color:var(--loss); } .v3h .row.out .pl { font-weight:600; }
        .v3h .legend { display:flex; gap:20px; font-size:13px; color:var(--dim); }
        .v3h .legend i { display:inline-block; width:16px; vertical-align:middle; margin-inline-start:8px; border-top:2px solid var(--accent); }
        .v3h .legend i.d { border-top:2px dashed var(--dash); }
        .v3h .chart { position:relative; margin-top:16px; }
        .v3h .chart { padding-bottom:14px; border-bottom:1px solid var(--rule); margin-bottom:48px; }
        .v3h .chart svg { display:block; width:100%; height:150px; }
        .v3h .chart .zero { position:absolute; inset-inline-start:0; top:50%; transform:translateY(-120%); font-family:var(--font-mono); font-size:11px; color:var(--dim); background:var(--bg); padding-inline:4px; }
        .v3h .times { direction:ltr; display:flex; justify-content:space-between; font-family:var(--font-mono); font-size:11px; color:var(--dim); margin-top:6px; }
        .v3h .cols { display:flex; flex-wrap:wrap; gap:48px; margin-top:56px; }
        .v3h .cols > div { min-width:0; }
        .v3h .hours { flex:1 1 280px; } .v3h .news { flex:2 1 420px; }
        .v3h .li { display:flex; justify-content:space-between; align-items:center; gap:16px; padding-block:15px; border-bottom:1px solid var(--rule); font-size:16px; }
        .v3h .mk { display:flex; flex-direction:column; align-items:flex-end; gap:2px; min-width:0; text-align:end !important; }
        .v3h .mk .cd { font-size:13px; color:var(--dim); }
        .v3h .nw { display:block; padding-block:15px; border-bottom:1px solid var(--rule); }
        .v3h a.nw:hover { background:var(--hover); }
        .v3h .nw div { line-height:1.4; }
        .v3h .nw small { display:block; font-size:13px; color:var(--dim); margin-top:4px; }
        .v3h .note { font-size:13px; color:var(--dim); margin-top:12px; }
        .v3h .foot { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-top:56px; padding-top:14px; border-top:1px solid var(--rule); font-size:13px; color:var(--dim); }
        @media (max-width:720px) {
            .v3h .kpi { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .v3h .kpi > div:first-child { grid-column:1 / -1; }
            .v3h .kpi > div:nth-child(n+2) { border-top:1px solid var(--rule); }
            .v3h .kpi > div:nth-child(2) { padding-inline-start:0; border-inline-start:0; }
            .v3h .topzone { display:block; } .v3h .radar-solo { display:none; }
            .v3h .row { gap:10px; }
        }
"""


# ───────────────────────── מניות מובילות (וטבלאות דומות) ─────────────────────────

def age_ticker(age_seconds: int) -> str:
    """'עודכן לפני N שניות' עם מונה שרץ בצד הלקוח ב-CSS בלבד (@property + steps), בלי JS - ר' .v3age ב-COMPONENT_CSS."""
    a = max(0, min(int(age_seconds), 59))
    return f'<span class="upd">עודכן לפני <span class="num v3age" style="--age:{a}"></span> שניות</span>'


def movers_head(title: str, fresh: str, age_seconds: int | None) -> str:
    fresh_html = f'<span class="fresh">{esc(fresh)}</span>' if fresh else ""
    side = f'<span class="hr withico">{fresh_html}{age_ticker(age_seconds) if age_seconds is not None else ""}</span>'
    return f'<section class="block" style="margin-top:32px">{head(title, side)}</section>'


def colored_head(title: str, count: int, kind: str) -> str:
    var = "var(--gain)" if kind == "up" else "var(--loss)"
    return (
        f'<div class="head" style="border-bottom-color:{var}"><div class="h2 {kind}">{esc(title)} {num(f"({count})")}</div></div>'
    )


def stocks_table(rows: list[dict], cum_days: int | None, show_price: bool = True) -> str:
    """rows: [{name, mono, daily, cum, price}] - מניה | שינוי יומי | מצטבר N ימים | שער (דף "מניות מובילות" ו"קרוב לסף התראה")."""
    body = []
    for r in rows:
        d, c = r.get("daily"), r.get("cum")
        price_td = f'<td>{num(r.get("price", "—"))}</td>' if show_price else ""
        d_html = (f'<td class="{cls_for(d)}">{num(("⚠ " if r.get("warn") else "") + signed(d, 1, "%"))}</td>' if d is not None else "<td>—</td>")
        c_html = (f'<td class="{cls_for(c)}">{num(signed(c, 1, "%"))}</td>' if c is not None else "<td>—</td>")
        mono = f'<span class="mono">{esc(r["mono"])}</span>' if r.get("mono") else ""
        body.append(
            f'<tr><td class="n" title="{esc(r["name"])}"><bdi>{esc(short_name(r["name"]))}</bdi>{mono}</td>{d_html}{c_html}{price_td}</tr>'
        )
    cum_th = f'<th>מצטבר {num(cum_days)} ימים</th>' if cum_days else "<th>מצטבר</th>"
    return (
        '<div class="tw"><table class="tb"><thead><tr><th>מניה</th><th>שינוי יומי</th>'
        f'{cum_th}{"<th>שער</th>" if show_price else ""}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    )


def watchlist_table(rows: list[dict]) -> str:
    body = "".join(
        f'<tr><td class="n" title="{esc(r["name"])}">{esc(short_name(r["name"]))}{f"<span class=mono>{esc(r.get("mono", ""))}</span>" if r.get("mono") else ""}</td>'
        f'<td>{num(r["added"])}</td><td class="{cls_for(r.get("ret"))}">{num(signed(r["ret"], 1, "%")) if r.get("ret") is not None else "—"}</td>'
        f'<td>{num(r.get("price", "—"))}</td></tr>'
        for r in rows
    )
    return (
        '<div class="tw"><table class="tb"><thead><tr><th>מניה</th><th>נוספה</th><th>שינוי מאז ההוספה</th><th>שער</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
    )


MOVERS_CSS = """
        @property --v3sec { syntax: '<integer>'; initial-value: 0; inherits: false; }
        @keyframes v3tick { from { --v3sec: var(--age); } to { --v3sec: 60; } }
        .v3h .v3age { --v3sec: 0; counter-reset: v3s var(--v3sec); animation: v3tick calc((60 - var(--age)) * 1s) steps(60, end) forwards; }
        .v3h .v3age::after { content: counter(v3s); }
        .v3h .head > .hr { display:flex; align-items:baseline; gap:20px; font-size:14px; color:var(--dim); }
        .v3h .upd { color:var(--dim); }
        .v3h .tw { overflow-x:auto; }
        .v3h table.tb { width:100%; border-collapse:collapse; }
        .v3h .tb th { text-align:start; font-weight:400; font-size:13px; color:var(--dim); padding:10px 8px; border-bottom:1px solid var(--rule); white-space:nowrap; }
        .v3h .tb td { padding:14px 8px; border-bottom:1px solid var(--rule); font-size:16px; white-space:nowrap; color:var(--v3-soft); }
        .v3h .tb td:first-child, .v3h .tb th:first-child { padding-inline-start:0; }
        .v3h .tb tbody tr:hover td { background:var(--hover); }
        .v3h .tb td.n { color:var(--ink); font-size:17px; }
        .v3h .tb td.n .mono { margin-inline-start:10px; }
        .v3h .tb td.up { color:var(--gain); } .v3h .tb td.down { color:var(--loss); }
"""


# ───────────────────────── התראות ─────────────────────────

def kpi4(cells: list[tuple]) -> str:
    """cells: [(label, value_text, css_class[, sub_text])] - פס סיכום בארבעה תאים שווים (התראות היום, מעקב קדימה)."""
    inner = "".join(
        f'<div><small>{esc(c[0])}</small><strong class="{c[2]}">{num(c[1])}' + (f'<em>{esc(c[3])}</em>' if len(c) > 3 else "") + '</strong></div>'
        for c in cells
    )
    return f'<div class="kpi k4">{inner}</div>'


_CHEV = (
    '<svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="transform:scaleX(-1)"><path d="M9 6l6 6-6 6"/></svg>'
)


def alerts_header() -> str:
    cols = ["מניה", "שינוי", "סיווג", "ניקוד", "כניסה", "יעד", "סטופ", "שעה"]
    return '<div class="arow ahead">' + "".join(f"<span>{c}</span>" for c in cols) + "</div>"


def alert_row(name: str, mono: str, is_new: bool, change_html: str, sig_key: str, sig_label: str, score_text: str,
              entry: str, target: str, stop: str, hhmm: str, is_open: bool) -> str:
    new = '<span class="isnew">חדשה</span>' if is_new else ""
    return (
        f'<div class="arow r{" open" if is_open else ""}">'
        f'<span class="nmc"><span class="nm" title="{esc(name)}"><bdi>{esc(short_name(name))}</bdi><small>{esc(mono)}</small>{new}{_CHEV}</span></span>'
        f'<span>{change_html}</span><span class="sig {sig_key}">{esc(sig_label)}</span><span>{num(score_text)}</span>'
        f'<span>{num(entry)}</span><span>{num(target)}</span><span>{num(stop)}</span><span>{num(hhmm)}</span></div>'
    )


def spark(prices: list[float]) -> str:
    if not prices or len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rg = (mx - mn) or 1.0
    pts = [(i * 126 / (len(prices) - 1), 36 - (v - mn) / rg * 30) for i, v in enumerate(prices)]
    up = prices[-1] >= prices[0]
    col = "var(--gain)" if up else "var(--loss)"
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    return (
        f'<svg class="spk" width="140" height="40" viewBox="0 0 126 40" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline vector-effect="non-scaling-stroke" points="{poly}" fill="none" stroke="{col}" stroke-width="1.4"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.6" fill="{col}"/></svg>'
    )


def alert_detail(parts: list[tuple[str, int]], prices: list[float], reason: str, over: float | None, quality: float | None,
                 over_cls: str, quality_cls: str, exp_drop: float | None, flags: list[str], news: list[dict],
                 net_text: str, held: bool) -> str:
    why = "".join(
        f'<span>{esc(n)}<b class="{"p" if p > 0 else "m"}">{num(f"{p:+d}")}</b></span>' for n, p in parts
    ) or '<span class="dim">אין גורם תומך</span>'
    def metric(label: str, val: float | None, cls: str) -> str:
        v = "—" if val is None else f'{int(val)}<span class="of">/100</span>'
        return f'<div><small>{label}</small><strong class="{cls}">{num_raw(v)}</strong></div>'
    drop_html = (
        f'<div><small>צפי לנמוך היומי</small><strong class="down">{num(f"-{exp_drop:.1f}%")}</strong></div>' if exp_drop is not None
        else '<div><small>צפי לנמוך היומי</small><strong>—</strong></div>'
    )
    met = (
        f'<div class="amet"><div><small>סיבת הירידה</small><strong class="r">{esc(reason)}</strong></div>'
        f'{metric("תגובת יתר", over, over_cls)}{metric("איכות פונדמנטלית", quality, quality_cls)}{drop_html}</div>'
    )
    flag_html = "".join(f'<div class="flagline"><i></i>{esc(f)}</div>' for f in flags)
    if news:
        def _news_item(n: dict) -> str:
            title = esc(n.get("title"))
            link = n.get("link")
            body = f'<a href="{esc(link)}" target="_blank" rel="noopener">{title}</a>' if link else title
            return f'<div>{body} <span class="src">{esc(n.get("source"))}</span></div>'

        items = "".join(_news_item(n) for n in news)
        news_html = f'<details class="nwd"><summary>חדשות {num(f"({len(news)})")}</summary><div class="nws">{items}</div></details>'
    else:
        news_html = ""
    foot = f'<div class="afoot"><span>{net_text}</span></div>' if net_text else ""
    held_html = '<div class="heldline">כבר באחזקות</div>' if held else ""
    return (
        f'<div class="adet"><div class="atop"><div class="asec"><small>ניקוד</small><div class="why">{why}</div></div>{spark(prices)}</div>'
        f'{met}{flag_html}{news_html}{foot}{held_html}</div>'
    )


def num_raw(inner_html: str) -> str:
    """כמו num() אבל מקבל HTML פנימי (למשל '72<span class="of">/100</span>')."""
    return f'<span class="num">{inner_html}</span>'


ALERTS_CSS = """
        .v3h .kpi.k4 { grid-template-columns:repeat(4,minmax(0,1fr)); margin-top:0; }
        .v3h .kpi.k4 > div { padding:18px 24px 20px; }
        .v3h .arow { display:grid; grid-template-columns:2.2fr .9fr 1fr .8fr 1fr 1fr 1fr .8fr; align-items:center; gap:0 8px; padding:0 12px; border-bottom:1px solid var(--rule); font-size:16px; white-space:nowrap; min-width:640px; }
        .v3h .arow > span { padding-block:15px; }
        .v3h .arow.ahead { border-bottom:1px solid var(--rule-strong); }
        .v3h .arow.ahead > span { font-size:13px; color:var(--dim); padding-block:10px; }
        .v3h .arow .nm { display:inline-flex; align-items:baseline; gap:10px; font-size:17px; }
        .v3h .arow .nm small { font-family:var(--font-mono); font-size:11px; letter-spacing:.08em; color:var(--dim); }
        .v3h .arow .nm .chev { align-self:center; color:var(--dim); transition:transform .15s; }
        .v3h .arow.open .nm .chev { transform:scaleX(-1) rotate(90deg) !important; }
        .v3h .arow .isnew { font-size:12px; color:var(--accent); }
        .v3h .arow .sig { font-size:15px; }
        .v3h .arow .sig.buy { color:var(--gain); font-weight:500; } .v3h .arow .sig.avoid { color:var(--loss); }
        .v3h .arow .sig.wait { color:var(--ink); }
        .v3h .adet { display:flex; flex-direction:column; gap:20px; padding:16px 12px 22px; background:var(--surface); border-bottom:1px solid var(--rule); max-width:none; }
        .v3h .atop { display:flex; flex-wrap:wrap; align-items:flex-end; justify-content:space-between; gap:12px 24px; }
        .v3h .asec > small, .v3h .amet small { display:block; font-size:13px; color:var(--dim); margin-bottom:4px; }
        .v3h .why { display:flex; flex-wrap:wrap; gap:6px 28px; font-size:15px; }
        .v3h .why span b { font-weight:500; margin-inline-start:6px; }
        .v3h .why .p { color:var(--gain); } .v3h .why .m { color:var(--loss); }
        .v3h .amet { display:grid; grid-template-columns:1.4fr 1fr 1fr 1fr; gap:16px; padding-block:14px; border-block:1px solid var(--rule); }
        .v3h .amet strong { font-size:20px; font-weight:400; display:block; }
        .v3h .amet strong.r { font-size:17px; color:var(--v3-soft); }
        .v3h .amet .of { font-size:13px; color:var(--dim); margin-inline-start:2px; }
        .v3h .flagline { display:flex; align-items:center; gap:10px; font-size:14px; color:var(--loss); }
        .v3h .flagline i { width:8px; height:8px; background:var(--loss); display:inline-block; }
        .v3h .nwd summary { cursor:pointer; list-style:none; font-size:15px; color:var(--dim); padding:4px 0; }
        .v3h .nwd summary::-webkit-details-marker { display:none; }
        .v3h .nwd summary:hover { color:var(--accent); }
        .v3h .nws { margin-top:6px; }
        .v3h .nws > div { padding:6px 0; border-bottom:1px solid var(--rule); } .v3h .nws > div:last-child { border-bottom:0; }
        .v3h .src { color:var(--dim); font-size:13px; margin-inline-start:8px; }
        .v3h .afoot { font-size:15px; color:var(--v3-soft); }
        .v3h .heldline { font-size:15px; color:var(--dim); padding-block:6px; border-top:1px solid var(--rule); }
        @media (max-width:720px) { .v3h .amet { grid-template-columns:repeat(2,minmax(0,1fr)); } .v3h .kpi.k4 { grid-template-columns:repeat(2,minmax(0,1fr)); } }
"""


# ───────────────────────── אחזקות ─────────────────────────

def holding_row(name: str, mono: str, amt: str, ccy_sym: str, pct: float, daily: float | None, out: bool, is_open: bool) -> str:
    cls = cls_for(pct)
    daily_html = (f'<span class="st {cls_for(daily)}">{num(signed(daily, 1, "%"))} היום</span>' if daily is not None else '<span class="st"></span>')
    return (
        f'<div class="hrow{" out" if out else ""}{" open" if is_open else ""}">'
        f'<span class="nm" title="{esc(name)}"><bdi>{esc(short_name(name))}</bdi><span class="mono">{esc(mono)}</span></span>'
        f'<span class="amt {cls}"><span class="cur">{ccy_sym}</span><span class="n">{num(amt)}</span></span>'
        f'<span class="p {cls}">{num(signed(pct, 1, "%"))}</span>{daily_html}{_CHEV}</div>'
    )


def position_bar(stop_pct: float, target_pct: float, cur_pct: float) -> str:
    """סרגל מיקום: סטופ משמאל, יעד מימין, כניסה בין השניים. מתחת לסטופ - הנקודה נעצרת בקצה עם תווית "מתחת לסטופ"."""
    s = abs(stop_pct)
    rng = s + target_pct
    if rng <= 0:
        return ""
    entry_x = s / rng * 100
    out = cur_pct < stop_pct
    cur_x = 0.0 if out else max(0.0, min(100.0, (cur_pct + s) / rng * 100))
    stop_lbl = f'מתחת לסטופ {num(f"-{s:.1f}%".replace(".0%", "%"))}' if out else f'סטופ {num(f"-{s:.1f}%".replace(".0%", "%"))}'
    tgt = f"+{target_pct:.1f}%".replace(".0%", "%")
    return (
        '<div class="bar">'
        f'<span class="sg l" style="left:0;width:{entry_x:.1f}%"></span><span class="sg g" style="left:{entry_x:.1f}%;right:0"></span>'
        f'<span class="tk s" style="left:0"></span><span class="tk" style="left:{entry_x:.1f}%"></span><span class="tk t" style="right:0;left:auto"></span>'
        f'<span class="mk{" out" if out else ""}" style="left:{cur_x:.1f}%"></span>'
        f'<span class="lb a" style="left:0">{stop_lbl}</span><span class="lb" style="left:{entry_x:.1f}%">כניסה</span>'
        f'<span class="lb r">יעד {num(tgt)}</span></div>'
    )


def holding_detail(cost: str, value: str, net: float | None, net_txt: str, entry_px: str, cur_px: str, share: float, held: str) -> str:
    net_cell = (f'<span class="v {cls_for(net)}">{num(net_txt)}</span>' if net is not None else '<span class="v">—</span>')
    return (
        f'<div class="d1"><div><small>עלות</small><span class="v">{num(cost)}</span></div>'
        f'<div><small>שווי</small><span class="v">{num(value)}</span></div>'
        f'<div><small>רווח/הפסד נטו</small>{net_cell}</div></div>'
        f'<div class="d2"><div><small>שער ביצוע</small><span class="v">{num(entry_px)}</span></div>'
        f'<div><small>שער נוכחי</small><span class="v">{num(cur_px)}</span></div>'
        f'<div><small>אחוז מהתיק</small><span class="v">{num(f"{share:.0f}%")}</span></div>'
        f'<div><small>מוחזק</small><span class="v">{esc(held)}</span></div></div>'
    )


HOLDINGS_CSS = """
        .v3h .hrow { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) 14px; align-items:center; gap:12px; padding:18px 10px; border-bottom:1px solid var(--rule); }
        .v3h .hrow .nm { font-size:17px; color:var(--v3-soft); }
        .v3h .hrow .nm .mono { margin-inline-start:10px; }
        .v3h .hrow .amt { display:inline-flex; align-items:baseline; gap:4px; font-size:18px; font-weight:400; justify-self:start; direction:ltr; }
        .v3h .hrow .amt .cur { font-size:13px; opacity:.8; }
        .v3h .hrow .amt .n { display:inline-block; width:52px; text-align:right; }
        .v3h .hrow .p { font-size:18px; font-weight:500; direction:ltr; text-align:right; }
        .v3h .hrow .st { font-size:14px; color:var(--dim); justify-self:start; white-space:nowrap; }
        .v3h .hrow .st.up { color:var(--gain); } .v3h .hrow .st.down { color:var(--loss); }
        .v3h .hrow .chev { color:var(--dim); transition:transform .15s; transform:scaleX(-1); }
        .v3h .hrow.open .chev { transform:scaleX(-1) rotate(90deg); }
        .v3h .hrow.out .nm { font-weight:600; color:var(--loss); }
        .v3h .d1 { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin:4px 0 20px; }
        .v3h .d2 { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin-bottom:28px; }
        .v3h .d1 small, .v3h .d2 small { display:block; font-size:13px; color:var(--dim); }
        .v3h .d1 .v { display:block; font-size:20px; font-weight:500; color:var(--v3-soft); }
        .v3h .d2 .v { display:block; font-size:15px; color:var(--v3-soft); }
        .v3h .d1 .v.down { color:var(--loss); } .v3h .d1 .v.up { color:var(--gain); }
        .v3h .bar { position:relative; height:2px; background:var(--rule); margin:16px 10px 32px; direction:ltr; }
        .v3h .bar .sg { position:absolute; top:0; height:2px; }
        .v3h .bar .sg.l { background:color-mix(in srgb, var(--loss) 55%, transparent); } .v3h .bar .sg.g { background:color-mix(in srgb, var(--gain) 55%, transparent); }
        .v3h .bar .mk { position:absolute; top:-6px; width:14px; height:14px; margin-left:-7px; border-radius:50%; background:var(--ink); }
        .v3h .bar .mk.out { background:var(--loss); box-shadow:0 0 0 5px color-mix(in srgb, var(--loss) 20%, transparent); }
        .v3h .bar .tk { position:absolute; top:-5px; width:1px; height:12px; background:var(--dim); }
        .v3h .bar .tk.s { background:var(--loss); } .v3h .bar .tk.t { background:var(--gain); }
        .v3h .bar .lb { position:absolute; top:14px; font-size:12px; color:var(--dim); transform:translateX(-50%); white-space:nowrap; direction:rtl; }
        .v3h .bar .lb.a { transform:none; color:var(--loss); } .v3h .bar .lb.r { right:0; left:auto; transform:none; color:var(--gain); }
        .v3h .hdet { padding:4px 10px 6px; border-bottom:1px solid var(--rule); }
        @media (max-width:720px) { .v3h .hrow { grid-template-columns:minmax(0,1fr) auto auto 14px; } .v3h .hrow .amt { display:none; } .v3h .d1, .v3h .d2 { grid-template-columns:repeat(2,minmax(0,1fr)); } }
"""


# ───────────────────────── יומן עסקאות ─────────────────────────

def journal_kpi(cells: list[tuple[str, str, str]]) -> str:
    """cells: [(label, value_text, css_class)] - שורת סיכומים בעמודות שוות (מספר העמודות נקבע לפי מספר התאים)."""
    inner = "".join(f'<div><small>{esc(l)}</small><strong class="{c}">{num(v)}</strong></div>' for l, v, c in cells)
    return f'<div class="kpi kn" style="grid-template-columns:repeat({len(cells)},minmax(0,1fr))">{inner}</div>'


_OUTCOME_CLS = {"הגיע ליעד": "up", "רווח לפני היעד": "up", "פגע בסטופ": "down"}


def journal_table(rows: list[dict]) -> str:
    """rows: name, mono, sig_key, sig_label, manual, entry_px, entry_dt, exit_px, exit_dt, days, outcome, pct, gross, net, ccy."""
    body = []
    for r in rows:
        sig = f'סיגנל <span class="{ {"buy": "up", "wait": "warn"}.get(r["sig_key"], "")}">{esc(r["sig_label"])}</span>' if r.get("sig_label") else ""
        sub_bits = [b for b in (sig, "ידנית" if r.get("manual") else "") if b]
        sub = f'<span class="sub">{" · ".join(sub_bits)}</span>' if sub_bits else ""
        oc = _OUTCOME_CLS.get(r["outcome"], "dim")
        body.append(
            f'<tr><td><span class="nm" title="{esc(r["name"])}"><bdi>{esc(short_name(r["name"]))}</bdi><span class="mono">{esc(r["mono"])}</span></span>{sub}</td>'
            f'<td class="c-entry"><span class="px">{num(r["entry_px"])}</span><span class="sub">{num(r["entry_dt"])}</span></td>'
            f'<td class="c-exit"><span class="px">{num(r["exit_px"])}</span><span class="sub">{num(r["exit_dt"])}</span></td>'
            f'<td>{num(r["days"])}</td><td class="c-res"><span class="res {oc}">{esc(r["outcome"])}</span></td>'
            f'<td><span class="pct {cls_for(r["gross"])}">{num(signed(r["pct"], 1, "%"))}</span></td>'
            f'<td class="c-gross"><span class="amt {cls_for(r["gross"])}">{num(signed(r["gross"]))}</span></td>'
            f'<td><span class="net {cls_for(r["net"])}">{num(signed(r["net"]))}</span></td>'
            f'<td class="c-ccy"><span class="mono">{esc(r["ccy"])}</span></td></tr>'
        )
    cols = ["20", "11", "11", "8", "15", "9", "10", "10", "6"]
    colgroup = "<colgroup>" + "".join(
        f'<col{(" class=" + chr(34) + cl + chr(34)) if cl else ""} style="width:{w}%">'
        for w, cl in zip(cols, ["", "c-entry", "c-exit", "", "c-res", "", "c-gross", "", "c-ccy"])
    ) + "</colgroup>"
    head_cells = ["מניה", "כניסה", "יציאה", "ימי מסחר", "תחזית מול ביצוע", "תשואה", "רווח/הפסד", "נטו", "מטבע"]
    cls = ["", "c-entry", "c-exit", "", "c-res", "", "c-gross", "", "c-ccy"]
    ths = "".join(f'<th class="{c}">{h}</th>' for h, c in zip(head_cells, cls))
    return (
        f'<div class="tablewrap"><table class="jr">{colgroup}<thead><tr>{ths}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    )


JOURNAL_CSS = """
        .v3h .tablewrap { overflow-x:auto; }
        .v3h table.jr { width:100%; border-collapse:collapse; min-width:760px; table-layout:fixed; }
        .v3h .jr th { text-align:start; font-weight:400; font-size:13px; color:var(--dim); padding:14px 12px 10px; border-bottom:1px solid var(--rule); white-space:nowrap; }
        .v3h .jr td { padding:14px 12px; border-bottom:1px solid var(--rule); vertical-align:middle; white-space:nowrap; }
        .v3h .jr tr:hover td { background:var(--hover); }
        .v3h .jr th:first-child, .v3h .jr td:first-child { padding-inline-start:0; }
        .v3h .jr .nm { font-size:17px; color:var(--v3-soft); }
        .v3h .jr .nm .mono { margin-inline-start:10px; }
        .v3h .jr .sub { display:block; font-size:12px; color:var(--dim); margin-top:2px; }
        .v3h .jr .px { display:block; font-size:16px; color:var(--ink); }
        .v3h .jr .pct, .v3h .jr .net, .v3h .jr .amt { font-size:17px; }
        .v3h .jr .pct, .v3h .jr .net { font-weight:500; }
        .v3h .jr .res { font-size:15px; }
        .v3h .jr .warn { color:var(--v3-warn); } .v3h .jr .dim { color:var(--dim); }
        @media (max-width:560px) {
            .v3h .jr .c-entry, .v3h .jr .c-exit, .v3h .jr .c-res, .v3h .jr .c-gross, .v3h .jr .c-ccy { display:none; }
            .v3h table.jr { min-width:0; table-layout:auto; } .v3h .jr col { width:auto !important; }
            .v3h .jr td, .v3h .jr th { padding-inline:6px; } .v3h .jr td:first-child { white-space:normal; }
        }
"""


# ───────────────────────── ביצועי אסטרטגיה ─────────────────────────

def perf_filter_summary(parts: list[str], is_open: bool) -> str:
    inner = "".join(f'<span class="fp">{esc(p)}</span>' for p in parts)
    return (
        f'<div class="fl{" open" if is_open else ""}"><span class="fsum">{inner}</span>'
        f'<span class="chg">שינוי{_CHEV}</span></div>'
    )


def perf_kpi(total: int, hit: int, stop: int, neither: int, pending: int, rate_text: str, rate_up: bool | None) -> str:
    cells = [
        ("התראות שנבדקו", str(total), ""), ("הגיעו ליעד", str(hit), "up"), ("פגעו בסטופ", str(stop), "down"),
        ("נשארו באמצע", str(neither), ""), ("בהמתנה", str(pending), ""),
        ("שיעור הצלחה", rate_text, "" if rate_up is None else ("up" if rate_up else "down")),
    ]
    inner = "".join(f'<div><small>{l}</small><strong class="{c}">{num(v)}</strong></div>' for l, v, c in cells)
    n = max(total, 1)
    segs = "".join(
        f'<i class="{c}" style="flex:{max(v, 0)}"></i>' for c, v in (("g", hit), ("l", stop), ("n", neither), ("p", pending)) if v > 0
    )
    bar = f'<div class="pbar" role="img" aria-label="חלוקת התוצאות">{segs}</div>' if total else ""
    return f'<div class="kpi k6">{inner}</div>{bar}'


def rate_cell(rate: float) -> str:
    cls = "up" if rate >= 50 else "down"
    return f'<td class="r {cls}"><span class="rate">{num(f"{rate:.1f}")}<span class="rb"><i style="width:{max(0, min(rate, 100)):.1f}%"></i></span></span></td>'


def plain_table(headers: list[str], rows: list[list[str]], main_first: bool = True) -> str:
    """rows: רשימת שורות של תאים (HTML מוכן לתא <td>...</td> או טקסט פשוט - טקסט פשוט עטוף אוטומטית)."""
    ths = "".join(f"<th>{h}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = []
        for i, c in enumerate(row):
            tds.append(c if c.startswith("<td") else f'<td{" class=main" if (i == 0 and main_first) else ""}>{c}</td>')
        trs.append(f'<tr>{"".join(tds)}</tr>')
    return f'<div class="tablewrap"><table class="tb"><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def collapsible(title: str, hint_parts: list[str], body_html: str) -> str:
    hint = "".join(f'<span class="fp">{h}</span>' for h in hint_parts)
    return (
        f'<details class="more"><summary><span class="mt"><b>{esc(title)}</b><span class="ms">{hint}</span></span>'
        f'<span class="chg">הצגה{_CHEV}</span></summary><div class="in">{body_html}</div></details>'
    )


def titled_section(title: str, side_html: str, body_html: str) -> str:
    return f'<section class="sec"><div class="sech">{esc(title)}{side_html}</div>{body_html}</section>'


PERF_CSS = """
        .v3h .kpi.k6 { grid-template-columns:repeat(6,minmax(0,1fr)); margin-top:28px; border-top:1px solid var(--rule); }
        .v3h .kpi.k6 > div { padding:18px 18px 20px; }
        .v3h .kpi.k6 > div:first-child { padding-inline-start:0; border-inline-start:0; }
        .v3h .kpi.k6 strong { font-size:clamp(20px,2.4vw,26px); }
        .v3h .pbar { display:flex; gap:2px; height:4px; margin-top:-1px; }
        .v3h .pbar i { display:block; height:100%; }
        .v3h .pbar .g { background:var(--gain); } .v3h .pbar .l { background:var(--loss); } .v3h .pbar .n { background:var(--dim); opacity:.5; } .v3h .pbar .p { background:var(--rule); }
        .v3h .fl { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 0; border-bottom:1px solid var(--rule); cursor:pointer; }
        .v3h .fsum { display:flex; flex-wrap:wrap; align-items:center; row-gap:6px; font-size:16px; color:var(--v3-soft); }
        .v3h .fp { display:inline-block; }
        .v3h .fp + .fp { margin-inline-start:18px; padding-inline-start:18px; border-inline-start:1px solid var(--dim); line-height:1.1; }
        .v3h .chg { display:inline-flex; align-items:center; gap:8px; font-size:14px; color:var(--accent); }
        .v3h .chg svg { transform:scaleX(-1); transition:transform .15s; }
        .v3h .fl.open .chg svg { transform:scaleX(-1) rotate(90deg); }
        .v3h .tb td.r { font-weight:500; }
        .v3h .rate { display:inline-flex; align-items:center; gap:12px; }
        .v3h .rate .num { min-width:42px; text-align:right; }
        .v3h .rb { position:relative; display:inline-block; width:72px; height:4px; background:var(--rule); direction:ltr; }
        .v3h .rb i { display:block; height:100%; background:var(--gain); }
        .v3h .rb::after { content:''; position:absolute; left:50%; top:-3px; width:1px; height:10px; background:var(--dim); }
        .v3h .down .rb i { background:var(--loss); }
        .v3h .sec { margin-top:44px; }
        .v3h .sec .sech { margin:0; font-weight:500; font-size:18px; padding-bottom:12px; border-bottom:1px solid var(--rule-strong); display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:6px 24px; }
        .v3h .sec .sech .hsub { display:inline-flex; flex-wrap:wrap; align-items:center; row-gap:4px; font-size:14px; font-weight:400; color:var(--dim); }
        .v3h .sec .sech .hsub .fp + .fp { margin-inline-start:14px; padding-inline-start:14px; }
        .v3h .two { display:grid; grid-template-columns:1fr 1fr; gap:0 56px; }
        .v3h details.more { border-bottom:1px solid var(--rule); }
        .v3h details.more > summary { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:18px 0; cursor:pointer; list-style:none; }
        .v3h details.more > summary::-webkit-details-marker { display:none; }
        .v3h details.more[open] .chg svg { transform:scaleX(-1) rotate(90deg); }
        .v3h .mt { display:flex; flex-direction:column; gap:2px; }
        .v3h .mt b { font-weight:500; font-size:16px; color:var(--ink); }
        .v3h .ms { display:flex; flex-wrap:wrap; align-items:center; row-gap:4px; font-size:13.5px; color:var(--dim); }
        .v3h .ms .fp + .fp { margin-inline-start:12px; padding-inline-start:12px; }
        .v3h details.more .in { padding:0 0 24px; }
        .v3h .stack { margin-top:44px; border-top:1px solid var(--rule-strong); }
        @media (max-width:820px) { .v3h .two { grid-template-columns:1fr; } }
        @media (max-width:720px) { .v3h .kpi.k6 { grid-template-columns:repeat(2,minmax(0,1fr)); } .v3h .kpi.k6 > div:nth-child(odd) { padding-inline-start:0; border-inline-start:0; } .v3h .kpi.k6 > div:nth-child(n+3) { border-top:1px solid var(--rule); } }
"""


HOURS_IFRAME_TEMPLATE = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root { --ink:#24211D; --dim:#6F6A62; --rule:#DAD5CC; --gain:#2F6B4F; --strong:#24211D; }
:root[data-theme="dark"] { --ink:#ECE8E0; --dim:#9A948A; --rule:#34302A; --gain:#7DBF9C; --strong:#5A554C; }
html, body { margin:0; background:transparent; color:var(--ink); font-family:'Heebo',system-ui,sans-serif; direction:rtl; font-variant-numeric:tabular-nums; }
.head { padding-bottom:12px; border-bottom:1px solid var(--strong); font-weight:500; font-size:18px; line-height:1.5; }
.li { display:flex; justify-content:space-between; align-items:center; gap:16px; padding-block:15px; border-bottom:1px solid var(--rule); }
.nmc { display:flex; flex-direction:column; gap:2px; }
.nmc .n { font-size:16px; }
.stt { font-size:13px; color:var(--dim); }
.stt.up { color:var(--gain); }
.cd { display:flex; flex-direction:column; align-items:flex-end; gap:6px; }
.cd .lbl { font-size:13px; color:var(--dim); }
.clk { display:flex; gap:14px; direction:ltr; }
.u { display:flex; flex-direction:column; align-items:center; min-width:34px; line-height:1.15; }
.u b { font-size:20px; font-weight:400; direction:ltr; unicode-bidi:isolate; }
.u i { font-style:normal; font-size:11px; color:var(--dim); }
.num { direction:ltr; unicode-bidi:isolate; display:inline-block; }
</style></head><body>
<div id="w"><div class="head">זמני מסחר</div><div id="rows"></div></div>
<script>
(function () {
  var P = window.parent, root = document.documentElement, M = __DATA__;
  function eff() { try { var t = P.document.documentElement.getAttribute('data-theme'); if (t) return t; return P.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch (e) { return 'light'; } }
  function mirror() { root.setAttribute('data-theme', eff()); }
  mirror();
  try { if (window.MutationObserver) new MutationObserver(mirror).observe(P.document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }); } catch (e) {}
  var rows = document.getElementById('rows');
  M.forEach(function (m, i) {
    var d = document.createElement('div'); d.className = 'li';
    d.innerHTML = '<div class="nmc"><span class="n">' + m.name + '</span><span class="stt' + (m.open ? ' up' : '') + '">' + (m.open ? 'השוק פתוח' : 'השוק סגור') + '</span></div><span class="cd" id="c' + i + '"></span>';
    rows.appendChild(d);
  });
  function p2(n) { return (n < 10 ? '0' : '') + n; }
  function tick() {
    var now = Date.now();
    M.forEach(function (m, i) {
      var s = Math.max(0, Math.floor((m.target_ms - now) / 1000)), dd = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
      function seg(v, label) { return '<span class="u"><b>' + p2(v) + '</b><i>' + label + '</i></span>'; }
      document.getElementById('c' + i).innerHTML = '<span class="lbl">' + (m.open ? 'נסגר בעוד' : 'נפתח בעוד') + '</span><span class="clk">' + seg(dd, 'ימים') + seg(hh, 'שעות') + seg(mm, 'דקות') + seg(ss, 'שניות') + '</span>';
    });
  }
  tick(); setInterval(tick, 1000);
  function fit() { try { var h = Math.ceil(document.getElementById('w').getBoundingClientRect().bottom + 4) + 'px'; if (window.frameElement) { window.frameElement.style.height = h; window.frameElement.parentElement.style.height = h; } } catch (e) {} }
  fit(); window.addEventListener('resize', fit);
})();
</script></body></html>"""


def hours_iframe(markets: list[dict]) -> str:
    """זמני מסחר כ-iframe עם שעון רץ (כולל שניות) לפתיחה/סגירה; הסטטוס (פתוח/סגור) מתחת לשם הבורסה.
    markets: [{name, open, target_ms}] - target_ms = רגע האירוע הבא (epoch באלפיות שנייה)."""
    import json as _json
    return HOURS_IFRAME_TEMPLATE.replace("__DATA__", _json.dumps(markets, ensure_ascii=False))
