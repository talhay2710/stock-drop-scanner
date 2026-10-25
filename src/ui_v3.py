"""עיצוב v3 ("Ivory + Radar") - פונקציות טהורות שבונות HTML/SVG, בלי תלות ב-Streamlit (נבדקות ב-tests/test_core.py).

המקור לכל מבנה ועיצוב: המוקאפים שאושרו טאב-אחר-טאב (ר' project_site_redesign_studio). כל ה-HTML מוחזר כמחרוזת *בלי שורות ריקות
ובלי הזחה בתחילת שורה* - אחרת מרקדאון של Streamlit שובר את בלוק ה-HTML (שורה ריקה) או הופך אותו לקוד (הזחה).
"""
from __future__ import annotations

import html
from .names import fix_name
import math
import re

CCY_SYMBOL = {"ILS": "₪", "USD": "&#36;"}


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


_STOP_SHORT = {"בית", "הון", "קרן", "ים", "בע\"מ", "חב'"}
_GENERIC_FIRST = {"בנק", "חברת", "הבנק", "בית", "קרן", "The", "Bank"}
_DROP_FIRST = {"קבוצת"}  # "קבוצת אקרשטיין" -> "אקרשטיין"


def short_name(name) -> str:
    """שם מניה מקוצר: מילה אחת ("אלביט מערכות" -> "אלביט", "Intel Corporation" -> "Intel").
    אם המילה הראשונה כללית (בנק, קבוצת...) לוקחים גם את השנייה ("בנק הפועלים")."""
    text = fix_name(str(name if name is not None else "").strip())
    if not text:
        return ""
    words = re.split(r"\s+", text)
    first = words[0].strip(",.;")
    if first in _DROP_FIRST and len(words) > 1:
        return words[1].strip(",.;")
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


def ltr_nums(text: str) -> str:
    """עוטף מספרים/אחוזים בתוך טקסט עברי ב-bdi LTR - הסימן (-) נשאר לפני המספר ולא "בורח" אחריו (למשל "(-16%)")."""
    return re.sub(r"[+\-−]?\d[\d,.]*%?", lambda m: f'<bdi dir="ltr">{m.group(0)}</bdi>', text)


def signed(value: float, decimals: int = 0, suffix: str = "") -> str:
    if round(value, decimals) == 0:  # "-0.0%" / "+0.0%" מבלבל - אפס בלי סימן
        return f"{0:,.{decimals}f}{suffix}"
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


def _dual(n: int, one: str, two: str, many: str) -> str:
    """ספירה בעברית: 1 -> 'דקה', 2 -> 'שתי דקות' (נקבה) / 'יומיים' / 'שעתיים', 3+ -> '3 דקות'."""
    return one if n == 1 else (two if n == 2 else f"{n} {many}")


def _and(text: str) -> str:
    """'ו' החיבור: צמודה למילה ("ושעה"), ובמספר עם מקף ("ו־12 דקות")."""
    return ("ו־" if text[:1].isdigit() else "ו") + text


def fmt_countdown(minutes: int) -> str:
    """כמו ב-JS של המוקאפ: 'יום ו־3 שעות' / '3 שעות ו־12 דקות' / '12 דקות' (יחיד: שעה/דקה/יום)."""
    minutes = max(int(minutes), 0)
    d, rem = divmod(minutes, 1440)
    h, m = divmod(rem, 60)
    hs = _dual(h, "שעה", "שעתיים", "שעות")
    ms = _dual(m, "דקה", "שתי דקות", "דקות")
    if d > 0:
        return _dual(d, "יום", "יומיים", "ימים") + ((" " + _and(hs)) if h else "")
    if h > 0:
        return hs + ((" " + _and(ms)) if m else "")
    return ms


# ───────────────────────── עמוד הבית ─────────────────────────

def notice(name: str, gap_pct: float, is_target: bool) -> str:
    """שורת התראה אחת: אחזקה שחצתה סטופ (אדום) או יעד (ירוק). בלי כותרת "דורש תשומת לב"."""
    what = "עברה את היעד" if is_target else "חצתה את הסטופ-לוס"
    color = "var(--gain)" if is_target else "var(--loss)"
    return (
        f'<div class="notice"><i style="background:{color}"></i>'
        f'<span><b>{esc(short_name(name))}</b> {what} ב-{num(f"{abs(gap_pct):.1f}%")}</span></div>'
    )


_NOTICE_COLORS = {"loss": "var(--loss)", "gain": "var(--gain)", "warn": "var(--v3-warn)", "info": "var(--dim)"}


NOTICE_SECONDS = 8


def notices(items: list[tuple[str, str, str]]) -> str:
    """הודעות בראש עמוד הבית: items = [(kind loss|gain|warn|info, name, text_html)]. הודעה אחת - סטטית; כמה - מתחלפות כל NOTICE_SECONDS שניות.
    המסגרת קבועה, רק התוכן מוחלף מיידית (בלי דהייה) - כדי שלא יהיה הבהוב."""
    if not items:
        return ""

    def slide(kind: str, name: str, text: str, style: str = "") -> str:
        b = f"<b>{esc(short_name(name))}</b> " if name else ""
        return f'<span class="s"{style}><i style="background:{_NOTICE_COLORS.get(kind, "var(--dim)")}"></i><span>{b}{text}</span></span>'

    n = len(items)
    if n == 1:
        return f'<div class="notice"><span class="slides">{slide(*items[0]).replace(" class=\"s\"", " class=\"s on\"", 1)}</span></div>'
    win = 100.0 / n
    kf = f"@keyframes ntcrot{n}{{0%,{win - 0.01:.2f}%{{visibility:visible}}{win:.2f}%,100%{{visibility:hidden}}}}"
    slides = "".join(slide(*it, style=f' style="animation-delay:{i * NOTICE_SECONDS}s"') for i, it in enumerate(items))
    return (
        f'<style>{kf}.v3h .notice.n{n} .s{{animation:ntcrot{n} {n * NOTICE_SECONDS}s step-end infinite}}</style>'
        f'<div class="notice n{n}"><span class="slides">{slides}</span></div>'
    )


def money(n_html: str, sym: str) -> str:
    """סכום + סמל מטבע: ש"ח משמאל למספר, דולר תמיד מימין למספר (בהקשר RTL הסמל הראשון בסדר הלוגי יושב מימין)."""
    return f"{sym}&nbsp;{n_html}" if sym == CCY_SYMBOL["USD"] else f"{n_html}&nbsp;{sym}"


def portfolio_strip(value: float, count: int, pnl: float, pnl_pct: float,
                    day_change: float | None, day_pct: float | None, ccy: str, day_label: str = "שינוי יומי",
                    alloc_html: str = "") -> str:
    # סכומים בלבד: בלי פס ההרכב ובלי שורת האחוזים מתחת לסכומים (הוסרו לבקשת המשתמש, 19.10.2026) - האחוזים בטבלת האחזקות שמתחת
    sym = CCY_SYMBOL.get(ccy, esc(ccy))
    cells = [
        f'<div><small>שווי נוכחי</small><strong>{money(num(plain(value)), sym)}</strong></div>',
        f'<div><small>רווח/הפסד</small><strong class="{cls_for(pnl)}">{money(num(signed(pnl)), sym)}</strong></div>',
    ]
    if day_change is not None:
        cells.append(
            f'<div><small>{esc(day_label)}</small><strong class="{cls_for(day_change)}">{money(num(signed(day_change)), sym)}</strong></div>'
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
        ago = "סריקה אחרונה " + ("הרגע" if m == 0 else (f"לפני {_dual(m, 'דקה', 'שתי דקות', 'דקות')}" if m < 120 else f"לפני {_dual(m // 60, 'שעה', 'שעתיים', 'שעות')}"))
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


def radar_positions(rows: list[dict], step: float = 3.0) -> list[dict]:
    """מוסיף לכל שורה x/y/label_y/out לפי pnl_pct ו-stop_pct האישי (ההילה האדומה = חצתה את הסטופ של עצמה)."""
    losers = sorted([r for r in rows if r["pnl_pct"] < 0], key=lambda r: -r["pnl_pct"])
    winners = sorted([r for r in rows if r["pnl_pct"] >= 0], key=lambda r: -r["pnl_pct"])
    placed = []
    for group, lo, hi in ((losers, 128.0, 235.0), (winners, 50.0, -50.0)):
        for r, ang in zip(group, _spread(len(group), lo, hi)):
            off = ang - (180.0 if ang > 90 else 0.0)  # סטייה מהציר האופקי (שם יושבות תוויות האחוזים)
            if abs(off) < 16.0:
                ang += (16.0 if off >= 0 else -16.0) - off
            rad = min(abs(r["pnl_pct"]) * (53.0 / step), _R_MAX)
            theta = math.radians(ang)
            x = _CX + rad * math.cos(theta)
            y = _CY - rad * math.sin(theta)
            stop = r.get("stop_pct")
            out = stop is not None and r["pnl_pct"] < stop
            placed.append({**r, "x": x, "y": y, "out": out, "below": y > 300})
    return placed


def _hit(a: tuple, b: tuple) -> bool:
    """חפיפה בין שני מלבנים (x, y, w, h)."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def holdings_radar(rows: list[dict], step: float = 3.0) -> str:
    """step = היעד באחוזים: הטבעת הפנימית (והקשת הירוקה) היא היעד, והחיצוניות ב-2x ו-3x ממנו.
    כלום לא מסתיר טקסט: תוויות הציר תמיד על אותו קו; תווית מניה שחופפת להן (או לתווית אחרת) עולה גבוה יותר או עוברת מתחת לנקודה."""
    placed = radar_positions(rows, step)
    s1, s2, s3 = (f"{step * k:g}" for k in (1, 2, 3))
    halo = "paint-order:stroke; stroke:var(--bg); stroke-width:5px; stroke-linejoin:round"
    ticks = [(137, f"-{s1}%", "loss"), (84, f"-{s2}%", "loss"), (32, f"-{s3}%", "loss"),
             (243, f"+{s1}%", "gain"), (296, f"+{s2}%", "gain"), (348, f"+{s3}%", "gain")]
    tick_y = [193.5] * len(ticks)  # תוויות הציר תמיד על אותו קו - הנקודה זזה, לא התווית
    tick_box = lambda i: (ticks[i][0] - len(ticks[i][1]) * 3.0, tick_y[i] - 10, len(ticks[i][1]) * 6.0, 13)
    taken = [tick_box(i) for i in range(len(ticks))] + [(205, 118, 36, 15)]  # תוויות הציר + "יעד"
    pad = lambda b, k: (b[0] - k, b[1] - 2, b[2] + 2 * k, b[3] + 4)
    tick_band = (14.0, 181.0, 352.0, 17.0)  # שורת תוויות האחוזים לכל רוחבה - שמות מניות לא נכנסים אליה בכלל
    tick_pad = [pad(tick_box(i), 14.0) for i in range(len(ticks))]  # שוליים סביב תוויות האחוזים - שמות לא מתקרבים אליהן
    dots = []
    for p in placed:
        label = esc(short_name(p["name"]))
        w = max(26.0, len(short_name(p["name"])) * 7.6)
        rr = 11.0 if p["out"] else 8.0
        rad = math.hypot(p["x"] - _CX, _CY - p["y"])
        ang = math.degrees(math.atan2(_CY - p["y"], p["x"] - _CX))

        def spot(d: float, lift: float = 0.0, below: bool = False) -> tuple[float, float, float, tuple, tuple]:
            """נקודה שמוסטת ב-d מעלות על אותה טבעת (הרדיוס = הרווח/הפסד נשמר), עם תיבת הנקודה ותיבת התווית שמעליה (מורמת ב-lift) או מתחתיה."""
            th = math.radians(ang + d)
            x, y = _CX + rad * math.cos(th), _CY - rad * math.sin(th)
            ly = y + rr + 13 if below else y - (14 if p["out"] else 11) - lift
            return x, y, ly, (x - rr, y - rr, 2 * rr, 2 * rr), (x - w / 2, ly - 13, w, 17)

        # השם תמיד מעל הנקודה ולעולם לא בשורת תוויות האחוזים (לא רק כשהוא חופף להן כרגע): קודם מזיזים את הנקודה לאורך הטבעת, ורק אם אי אפשר (נקודה במרכז) מרימים את השם
        # לפני שמרימים את השם גבוה (ונהיה רחוק מהנקודה וקרוב ל"יעד"), מנסים אותו מתחת לנקודה
        near, wide = [0.0] + [k * sg for k in range(1, 11) for sg in (1, -1)], [0.0] + [k * sg for k in range(1, 91) for sg in (1, -1)]
        cands = ([(d, lf, False) for lf in (0.0, 3.0, 6.0) for d in near] + [(d, 0.0, True) for d in near]
                 + [(d, lf, False) for lf in (0.0, 3.0, 6.0) for d in wide] + [(d, 0.0, True) for d in wide]
                 + [(d, lf, False) for lf in (9.0, 12.0, 15.0, 20.0, 30.0) for d in wide])
        pick, lift, below = next(((d, lf, bl) for d, lf, bl in cands
                                  if not any(_hit(spot(d, lf, bl)[3], t) for t in taken)
                                  and not any(_hit(spot(d, lf, bl)[4], t) for t in taken + tick_pad + [tick_band])), (0.0, 0.0, False))
        p["x"], p["y"], ly, dbox, lbox = spot(pick, lift, below)
        taken += [dbox, lbox]
        if p["out"]:
            dots.append(
                f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="6" fill="var(--loss)" stroke="none"/>'
                f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="9.5" fill="none" stroke="var(--loss)" stroke-width="2.5" opacity=".55"/>'
                f'<text x="{p["x"]:.0f}" y="{ly:.0f}" fill="var(--loss)" font-size="14" font-weight="600">{label}</text>'
            )
        else:
            dots.append(
                f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="6" fill="var(--ink)" stroke="none"/>'
                f'<text x="{p["x"]:.0f}" y="{ly:.0f}" fill="var(--ink)">{label}</text>'
            )
    tick_html = "".join(f'<text x="{x}" y="{tick_y[i]:.1f}" fill="var(--{col})">{t}</text>' for i, (x, t, col) in enumerate(ticks))
    n_out = sum(1 for p in placed if p["out"])
    aria = "רדאר אחזקות לפי רווח והפסד. צד שמאל הפסד, צד ימין רווח." + (f" {n_out} אחזקות חצו את הסטופ שלהן." if n_out else "")
    return (
        f'<figure class="plot"><svg style="overflow:visible" viewBox="0 0 380 392" role="img" aria-label="{esc(aria)}">'
        '<circle cx="190" cy="190" r="53" fill="none" stroke="var(--rule)"/><circle cx="190" cy="190" r="106" fill="none" stroke="var(--rule)"/>'
        '<circle cx="190" cy="190" r="158" fill="none" stroke="var(--rule)"/>'
        '<line x1="190" y1="14" x2="190" y2="366" stroke="var(--rule)"/><line x1="32" y1="190" x2="348" y2="190" stroke="var(--rule)"/>'
        '<path d="M190 14 A176 176 0 0 0 190 366" fill="none" stroke="var(--loss)" stroke-width="1" stroke-dasharray="4 5" opacity=".35"/>'
        '<path d="M190 137 A53 53 0 0 1 190 243" fill="none" stroke="var(--gain)" stroke-width="1.5" stroke-dasharray="4 5"/>'
        '<g style="direction:ltr; unicode-bidi:bidi-override; paint-order:stroke; stroke:var(--bg); stroke-width:4px; stroke-linejoin:round" '
        'font-size="10" font-family="IBM Plex Mono, monospace" text-anchor="middle">'
        f'{tick_html}</g>'
        f'<text x="222" y="130" text-anchor="middle" style="{halo}; stroke-width:6px" fill="var(--gain)" font-size="13" font-weight="600" font-family="Heebo, sans-serif">יעד</text>'
        '<circle cx="190" cy="190" r="2.5" fill="var(--dim)"/>'
        f'<g style="{halo}" text-anchor="middle" font-family="Heebo, sans-serif" font-size="13">{"".join(dots)}</g></svg></figure>'
    )


def stop_target_ladder(rows: list[dict]) -> str:
    """סולם סטופ ויעד (טאב האחזקות): שורה לכל אחזקה על ציר משותף של אחוזים מהכניסה - סטופ משמאל, כניסה (0) באמצע, יעד מימין,
    והנקודה היא הרווח/הפסד הנוכחי. rows: {name, pnl_pct, stop_pct, tgt_pct}. נקודה אדומה בהילה = מתחת לסטופ, ירוקה = מעל היעד."""
    rows = [r for r in rows if r.get("pnl_pct") is not None and (r.get("stop_pct") is not None or r.get("tgt_pct") is not None)]
    if not rows:
        return ""
    vals = [0.0] + [r["pnl_pct"] for r in rows] + [r["stop_pct"] for r in rows if r.get("stop_pct") is not None]         + [r["tgt_pct"] for r in rows if r.get("tgt_pct") is not None]
    lo, hi = min(vals) - 1.5, max(vals) + 1.5
    span = (hi - lo) or 1.0

    def x(v: float) -> float:
        return (v - lo) / span * 100.0

    out = []
    for r in sorted(rows, key=lambda r: r["pnl_pct"]):
        pnl, stop, tgt = r["pnl_pct"], r.get("stop_pct"), r.get("tgt_pct")
        below = stop is not None and pnl < stop
        above = tgt is not None and pnl >= tgt
        seg_l = f'<i class="lz l" style="left:{x(stop if stop is not None else min(pnl, 0)):.2f}%;width:{x(0) - x(stop if stop is not None else min(pnl, 0)):.2f}%"></i>'
        seg_g = f'<i class="lz g" style="left:{x(0):.2f}%;width:{x(tgt if tgt is not None else max(pnl, 0)) - x(0):.2f}%"></i>'
        ticks = (f'<i class="tk s" style="left:{x(stop):.2f}%"></i>' if stop is not None else "") +                 f'<i class="tk" style="left:{x(0):.2f}%"></i>' +                 (f'<i class="tk t" style="left:{x(tgt):.2f}%"></i>' if tgt is not None else "")
        cls = "out" if below else ("hit" if above else "")
        out.append(
            f'<div class="lr"><span class="ln{" out" if below else ""}">{esc(short_name(r["name"]))}</span>'
            f'<div class="lt">{seg_l}{seg_g}{ticks}<b class="mk {cls}" style="left:{x(pnl):.2f}%"></b></div>'
            f'<span class="lv {cls_for(pnl)}">{num(signed(pnl, 1, "%"))}</span></div>'
        )
    legend = ('<div class="lg"><span><b class="mk"></b>נוכחי</span><span><i class="tk"></i>כניסה</span>'
              '<span><i class="tk t"></i>יעד</span><span><i class="tk s"></i>סטופ</span></div>')
    return f'<section class="block">{head("מיקום מול יעד וסטופ-לוס")}{legend}<div class="ladder">{"".join(out)}</div></section>'


def daily_head_date(dates) -> None:
    """התאריך כבר מופיע בכרטיסי המדדים ("סגירה 16.10") - לא חוזרים עליו בכותרת/בשורות האחזקות."""
    return None


def daily_suffix(date, head_date) -> str:
    return ""


def daily_head_text(head_date) -> str:
    return "יומי"


def _daily_col_label(dates) -> str:
    """כותרת עמודת השינוי היומי: "היום" כשהנתון הוא של היום; ביום בלי מסחר (סוף שבוע/חג/לפני הפתיחה) - תאריך הנתון האחרון (dd.mm)."""
    import datetime as _dt
    import pandas as _pd
    ds = []
    for d in dates:
        try:
            t = _pd.to_datetime(d, errors="coerce")
        except Exception:
            continue
        if _pd.notna(t):
            ds.append(t.date())
    if not ds:
        return "היום"
    last = max(ds)
    return "היום" if last >= _dt.date.today() else last.strftime("%d.%m")


def holdings_rows(rows: list[dict], unit: str = "pct") -> str:
    """unit: "pct" (אחוזים) או "value" (סכומים במטבע האחזקה - pnl_amt / daily_amt / ccy בכל שורה)."""
    out = []
    head_date = daily_head_date([r.get("daily_pct_date") for r in rows])
    for r in sorted(rows, key=lambda r: -r["pnl_pct"]):
        is_out = r.get("stop_pct") is not None and r["pnl_pct"] < r["stop_pct"]
        daily = r.get("daily_pct")
        by_value = unit == "value" and r.get("pnl_amt") is not None
        if daily is None:
            daily_html = '<span class="st"></span>'
        else:
            dtxt = num(signed(r["daily_amt"])) if (by_value and r.get("daily_amt") is not None) else num(signed(daily, 1, "%"))
            daily_html = f'<span class="st {cls_for(daily)}">{dtxt}{daily_suffix(r.get("daily_pct_date"), head_date)}</span>'
        if by_value:
            # מצב ₪: רווח/הפסד מהקנייה בשקלים | שינוי היום בשקלים
            pl_html = f'<span class="pl {cls_for(r["pnl_pct"])}">{num(signed(r["pnl_amt"]))}</span>'
        else:
            pl_html = f'<span class="pl {cls_for(r["pnl_pct"])}">{num(signed(r["pnl_pct"], 1, "%"))}</span>'
        out.append(
            f'<div class="row{" out" if is_out else ""}"><span class="nm" title="{esc(r["name"])}">{esc(short_name(r["name"]))}</span>'
            f'{pl_html}{daily_html}</div>'
        )
    first = "<span>רווח/הפסד</span>" if unit == "value" else "<span>תשואה</span>"
    return (
        f'<div class="rows"><div class="cap"><span></span>{first}'
        f'<span>{num(_daily_col_label([r.get("daily_pct_date") for r in rows]))}</span></div>' + "".join(out) + "</div>"
    )


def holdings_section(rows: list[dict], step: float = 3.0, unit: str = "pct") -> str:
    return f'<section class="block">{head("אחזקות")}<div class="hold">{holdings_rows(rows, unit)}{holdings_radar(rows, step)}</div></section>'


def intraday_chart(series: list[tuple[str, list[float]]], times: list[str], portfolio_label: str, bench_label: str, date_label: str = "") -> str:
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
    legend = f'<div class="legend"><span>{esc(bench_label)}<i class="d"></i></span><span>{esc(portfolio_label)}<i></i></span></div>'
    ticks = "".join(f"<span>{esc(t)}</span>" for t in times)
    return (
        f'<section class="block"><div class="head"><div class="h2">תשואה תוך-יומית{" " + num(date_label) if date_label else ""}</div>{legend}</div><div class="chart">'
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
    return f'<div class="news">{head("חדשות כלכליות")}<div class="nwg">{body}</div></div>'


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
        .v3h .up { color:var(--gain); } .v3h .down { color:var(--loss); } .v3h .kpi strong.warn { color:var(--v3-warn); }
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
        .v3h .notice .slides { display:grid; }
        .v3h .notice .s { grid-area:1 / 1; display:flex; align-items:center; flex-wrap:wrap; gap:6px 14px; visibility:hidden; }
        .v3h .notice .s.on { visibility:visible; }
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
        .v3h .plot { flex:1 1 320px; max-width:440px; padding-top:29px; margin:0; }  /* קצה הגרף העליון בגובה הטקסט של כותרות הטבלה */
        .v3h .plot svg { display:block; width:100%; height:auto; }
        .v3h .rows { flex:1 1 380px; min-width:0; padding-top:12px; }
        .v3h .rows .cap { display:grid; grid-template-columns:1fr 84px 128px; gap:12px; font-size:13px; color:var(--dim); padding:14px 10px 10px; border-bottom:1px solid var(--rule); }
        .v3h .row { display:grid; grid-template-columns:1fr 84px 128px; align-items:center; gap:12px; padding:18px 10px; border-bottom:1px solid var(--rule); }
        .v3h .row:hover { background:var(--hover); }
        .v3h .row .nm { font-size:17px; }
        .v3h .row .pl { font-size:17px; }
        .v3h .row .st { font-size:14px; color:var(--dim); }
        .v3h .row .st.up { color:var(--gain); } .v3h .row .st.down { color:var(--loss); }
        .v3h .row.out .nm { font-weight:600; color:var(--loss); } .v3h .row.out .pl { font-weight:600; }
        .v3h .legend { display:flex; gap:20px; font-size:13px; color:var(--dim); align-items:center; }
        .v3h .legend span { display:inline-flex; align-items:center; }
        .v3h .legend i { display:block; width:16px; height:0; flex:none; margin-inline-start:8px; border-top:2px solid var(--accent); }
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
        .v3h .news .nwg { display:grid; grid-template-columns:1fr 1fr; column-gap:64px; } @media (max-width:560px) { .v3h .news .nwg { grid-template-columns:1fr; } }
        .v3h .news .nw { display:flex; flex-direction:column; justify-content:space-between; gap:6px; padding-block:10px; box-sizing:border-box; }  /* גובה לפי התוכן (החדשות כבר לא לצד זמני המסחר); שני הפריטים בשורה באותו גובה */
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


def movers_head(title: str, fresh: str, age_seconds: int | None, icons: int = 1) -> str:
    fresh_html = f'<span class="fresh">{esc(fresh)}</span>' if fresh else ""
    side = f'<span class="hr withico{" withico2" if icons > 1 else ""}">{fresh_html}{age_ticker(age_seconds) if age_seconds is not None else ""}</span>'
    return f'<section class="block" style="margin-top:32px">{head(title, side)}</section>'


def colored_head(title: str, count: int, kind: str) -> str:
    var = "var(--gain)" if kind == "up" else "var(--loss)"
    return (
        f'<div class="head" style="border-bottom-color:{var}"><div class="h2 {kind}">{esc(title)}</div></div>'
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


def watchlist_head() -> str:
    cells = ["מניה", "נוספה בתאריך", "שער ביצוע", "שער נוכחי", "ימי החזקה", "שינוי"]
    return '<div class="wlh wlrow">' + "".join(f"<span>{c}</span>" for c in cells) + "<span></span></div>"


def watchlist_row(r: dict) -> str:
    """שורת מניה במעקב (רשת, כמו שורות האחזקות). העמודה האחרונה ריקה - שם נכנס כפתור ההסרה (✕) כשכבת-על."""
    ret = r.get("ret")
    mono = f'<span class="mono">{esc(r.get("mono", ""))}</span>' if r.get("mono") else ""
    return (
        f'<div class="wlrow"><span class="n" title="{esc(r["name"])}">{esc(short_name(r["name"]))}{mono}</span>'
        f'<span>{num(r["added"])}</span><span>{num(r.get("entry", "—"))}</span><span>{num(r.get("price", "—"))}</span>'
        f'<span>{num(r.get("days", "—"))}</span>'
        f'<span class="{cls_for(ret)}">{num(signed(ret, 1, "%")) if ret is not None else "—"}</span><span></span></div>'
    )


MOVERS_CSS = """
        @property --v3sec { syntax: '<integer>'; initial-value: 0; inherits: false; }
        @keyframes v3tick { from { --v3sec: var(--age); } to { --v3sec: 60; } }
        .v3h .v3age { --v3sec: 0; counter-reset: v3s var(--v3sec); animation: v3tick calc((60 - var(--age)) * 1s) steps(60, end) forwards; }
        .v3h .v3age::after { content: counter(v3s); }
        .v3h .head > .hr { display:flex; align-items:baseline; gap:20px; font-size:14px; color:var(--dim); }
        .v3h .upd { color:var(--dim); }
        .v3h .tw, .v3h.tw { overflow-x:auto; -webkit-overflow-scrolling:touch; }
        .v3h .wlrow { display:grid; grid-template-columns:minmax(0,1.7fr) 1fr 1fr 1fr .8fr .8fr 34px; gap:12px; align-items:center; padding:14px 10px; border-bottom:1px solid var(--rule); font-size:16px; white-space:nowrap; }
        .v3h .wlrow .n { font-size:17px; color:var(--v3-soft); } .v3h .wlrow .mono { margin-inline-start:10px; font-family:var(--font-mono); font-size:11px; letter-spacing:.08em; color:var(--dim); }
        .v3h .wlh { font-size:13px; color:var(--dim); padding-block:10px; border-bottom:1px solid var(--rule-strong); }
        @media (max-width:720px) { .v3h .wlrow { grid-template-columns:minmax(0,1.5fr) 1fr 1fr 34px; } .v3h .wlrow > span:nth-child(2), .v3h .wlrow > span:nth-child(3), .v3h .wlrow > span:nth-child(5) { display:none; } }
        .v3h table.tb { width:100%; border-collapse:collapse; }
        .v3h .tb th { text-align:start; font-weight:400; font-size:13px; color:var(--dim); padding:10px 8px; border-bottom:1px solid var(--rule); white-space:nowrap; }
        .v3h .tb td { padding:14px 8px; border-bottom:1px solid var(--rule); font-size:16px; white-space:nowrap; color:var(--v3-soft); }
        .v3h .tb td:first-child, .v3h .tb th:first-child { padding-inline-start:8px; }
        .v3h .tb tbody tr:hover td { background:var(--hover); }
        .v3h .tb td.n { color:var(--ink); font-size:17px; }
        .v3h .tb td.n .mono { margin-inline-start:10px; }
        .v3h .tb td.up { color:var(--gain); } .v3h .tb td.down { color:var(--loss); }
"""


# ───────────────────────── התראות ─────────────────────────

def kpi4(cells: list[tuple], compact: bool = False) -> str:
    """cells: [(label, value_text, css_class[, sub_text])] - פס סיכום בארבעה תאים שווים (התראות היום, מעקב קדימה)."""
    inner = "".join(
        f'<div><small>{esc(c[0])}</small><strong class="{c[2]}">{num(c[1])}' + (f'<em>{esc(c[3])}</em>' if len(c) > 3 else "") + '</strong></div>'
        for c in cells
    )
    return f'<div class="kpi k4{" sm" if compact else ""}">{inner}</div>'


_CHEV = (
    '<svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="transform:scaleX(-1)"><path d="M9 6l6 6-6 6"/></svg>'
)


def alerts_header() -> str:
    cols = ["מניה", "שינוי בהתראה", "שינוי נוכחי", "סיגנל", "ניקוד", "כניסה", "יעד", "סטופ", "שעה"]
    return '<div class="arow ahead">' + "".join(f'<span{" class=\"x\"" if 4 <= i <= 7 else ""}>{c}</span>' for i, c in enumerate(cols)) + "</div>"


def alert_row(name: str, mono: str, is_new: bool, change_html: str, sig_key: str, sig_label: str, score_text: str,
              entry: str, target: str, stop: str, hhmm: str, is_open: bool, index_label: str = "", cur_html: str = "") -> str:
    new = ""  # תגית "חדשה" הוסרה - השעה בשורה מספיקה
    return (
        f'<div class="arow r{" open" if is_open else ""}">'
        f'<span class="nmc"><span class="nm" title="{esc(name)}"><bdi>{esc(short_name(name))}</bdi><small>{esc(mono)}</small>{f'<small class="ix">{esc(index_label)}</small>' if index_label else ""}{new}{_CHEV}</span></span>'
        f'<span>{change_html}</span><span>{cur_html}</span><span class="sig {sig_key}">{esc(sig_label)}</span><span class="x">{num(score_text)}</span>'
        f'<span class="x">{num(entry)}</span><span class="x">{num(target)}</span><span class="x">{num(stop)}</span><span>{num(hhmm)}</span></div>'
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
                 net_text: str, held: bool, levels: tuple[str, str, str] | None = None, quiet: bool = False,
                 cum: tuple[int, float | None] | None = None, split: bool = False):
    why = "".join(
        f'<span>{ltr_nums(esc(n))}<b class="{"p" if p > 0 else "m"}">{num(f"{p:+d}")}</b></span>' for n, p in parts
    ) or '<span class="dim">אין גורם תומך</span>'
    def metric(label: str, val: float | None, cls: str) -> str:
        v = "—" if val is None else f'{int(val)}<span class="of">/100</span>'
        return f'<div><small>{label}</small><strong class="{cls}">{num_raw(v)}</strong></div>'
    drop_html = (
        f'<div><small>צפי לנמוך היומי</small><strong class="down">{num(f"-{exp_drop:.1f}%")}</strong></div>' if exp_drop is not None
        else '<div><small>צפי לנמוך היומי</small><strong>—</strong></div>'
    )
    cum_html = ""
    if cum is not None:
        _days, _pct = cum
        _val = '<strong>—</strong>' if _pct is None else f'<strong class="{cls_for(_pct)}">{num(signed(_pct, 1, "%"))}</strong>'
        cum_html = f'<div><small>מצטבר · {num(str(_days))} ימים</small>{_val}</div>'
    # quiet (סיגנל "לקנות"): הציונים נשארים, רק בלי דגלי אזהרה - הסיגנל אחד וברור, בלי מסרים סותרים
    scores = f'{metric("תגובת יתר", over, over_cls)}{metric("איכות פונדמנטלית", quality, quality_cls)}'
    met = (
        f'<div class="amet{" q" if quiet else ""}"><div><small>סיבת הירידה</small><strong class="r">{esc(reason)}</strong></div>'
        f'{scores}{drop_html}{cum_html}</div>'
    )
    flag_html = "" if quiet else "".join(f'<div class="flagline"><i></i>{esc(f)}</div>' for f in flags)
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
    held_html = '<div class="heldline">פוזיציה פתוחה</div>' if held else ""
    lev = (
        '<div class="alev">' + "".join(f'<div><small>{lbl}</small><strong>{num(v)}</strong></div>' for lbl, v in zip(("כניסה", "יעד", "סטופ"), levels)) + '</div>'
        if levels else ""
    )
    _rest = (
        f'{lev}<div class="atop"><div class="asec"><small>ניקוד</small><div class="why">{why}</div></div>{spark(prices)}</div>'
        f'{flag_html}{news_html}{foot}{held_html}'
    )
    if split:  # הכרטיס נחתך לשניים - בין חלקיו מוצבת שורת הירידה המצטברת עם בורר הימים
        return f'<div class="adet">{met}</div>', f'<div class="adet">{_rest}</div>'
    return f'<div class="adet">{met}{_rest}</div>'


def num_raw(inner_html: str) -> str:
    """כמו num() אבל מקבל HTML פנימי (למשל '72<span class="of">/100</span>')."""
    return f'<span class="num">{inner_html}</span>'


ALERTS_CSS = """
        .v3h .kpi.k4 { grid-template-columns:repeat(4,minmax(0,1fr)); margin-top:0; }
        .v3h .kpi.k4 > div { padding:18px 24px 20px; }
        .v3h .kpi.k4.sm > div { padding:10px 20px 11px; }
        .v3h .kpi.k4.sm small { font-size:12px; }
        .v3h .kpi.k4.sm strong { font-size:20px; line-height:1.15; margin-top:1px; }
        .v3h .arow { display:grid; grid-template-columns:minmax(0,1.9fr) minmax(0,1.4fr) minmax(0,1fr) minmax(0,.9fr) minmax(0,.7fr) minmax(0,.95fr) minmax(0,.95fr) minmax(0,.95fr) minmax(0,.7fr); align-items:center; gap:0 8px; padding:0 12px; border-bottom:1px solid var(--rule); font-size:16px; white-space:nowrap; min-width:720px; }
        .v3h .arow > span { padding-block:15px; }
        .v3h .arow > span:has(.nt) { padding-block:8px; }
        .v3h .arow .nm small.ix { opacity:.75; }
        .v3h .arow .nt { display:block; font-size:12px; line-height:1.25; color:var(--dim); }
        .v3h .arow.ahead { border-bottom:1px solid var(--rule-strong); }
        .v3h .arow.ahead > span { font-size:13px; color:var(--dim); padding-block:10px; }
        .v3h .arow .nmc { min-width:0; overflow:hidden; }
        .v3h .arow .nm { display:inline-flex; align-items:baseline; gap:10px; font-size:17px; max-width:100%; }
        .v3h .arow .nm bdi { overflow:hidden; text-overflow:ellipsis; min-width:0; }
        .v3h .arow .nm small { font-family:var(--font-mono); font-size:11px; letter-spacing:.08em; color:var(--dim); }
        .v3h .arow .nm .chev { align-self:center; color:var(--dim); transition:transform .15s; }
        .v3h .arow.open .nm .chev { transform:scaleX(-1) rotate(90deg) !important; }
        .v3h .arow .isnew { font-size:12px; color:var(--accent); }
        .v3h .arow .sig { font-size:15px; }
        .v3h .arow .sig.buy { color:var(--gain); font-weight:500; } .v3h .arow .sig.avoid { color:var(--loss); }
        .v3h .arow .sig.wait { color:var(--v3-warn); }
        .v3h .adet { display:flex; flex-direction:column; gap:20px; padding:16px 12px 22px; background:var(--surface); border-bottom:1px solid var(--rule); max-width:none; white-space:normal; }
        .v3h .atop { display:flex; flex-wrap:wrap; align-items:flex-end; justify-content:flex-start; gap:12px 56px; }  /* הגרף הקטן צמוד לניקוד ולא בקצה השמאלי */
        .v3h .asec > small, .v3h .amet small { display:block; font-size:13px; color:var(--dim); margin-bottom:4px; }
        .v3h .why { display:flex; flex-wrap:wrap; gap:6px 28px; font-size:15px; }
        .v3h .asec { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 18px; }  /* "ניקוד" באותה שורה עם הגורמים */
        .v3h .asec > small { margin-bottom:0; }
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
        .v3h .heldline { font-size:15px; color:var(--dim); padding-block:16px; margin-bottom:-22px; border-top:1px solid var(--rule); }
        @media (max-width:720px) { .v3h .amet { grid-template-columns:repeat(2,minmax(0,1fr)); } .v3h .kpi.k4 { grid-template-columns:repeat(2,minmax(0,1fr)); } }
        .v3h .alev { display:none; }
        @media (max-width:480px) {
            /* נייד: ארבע כרטיסי סיכום בשורה אחת; בטבלה רק העמודות החשובות (כניסה/יעד/סטופ עוברים לפרטי ההתראה) */
            .v3h .kpi.k4, .v3h .kpi.k4.sm { grid-template-columns:repeat(4,minmax(0,1fr)); }
            .v3h .kpi.k4 > div, .v3h .kpi.k4.sm > div { padding:10px 8px 11px; border-top:0 !important; }
            .v3h .kpi.k4 > div:first-child { grid-column:auto; padding-inline-start:0; }
            .v3h .kpi.k4 > div:nth-child(2) { border-inline-start:1px solid var(--rule); padding-inline-start:8px; }
            .v3h .kpi.k4 small { font-size:12px; white-space:nowrap; }
            .v3h .kpi.k4 strong, .v3h .kpi.k4.sm strong { font-size:22px; }
            .v3h .arow { grid-template-columns:minmax(0,1.9fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1.1fr) minmax(0,.8fr); min-width:0; font-size:15px; padding:0 4px; gap:0 6px; }
            .v3h .arow .x { display:none; }
            .v3h .arow .nm { font-size:15px; display:grid; grid-template-areas:"name mono" "ix chev"; justify-content:start; align-items:baseline; column-gap:6px; row-gap:2px; }
            .v3h .arow .nm bdi { grid-area:name; }
            .v3h .arow .nm small:not(.ix) { grid-area:mono; }
            .v3h .arow .nm small.ix { grid-area:ix; }
            .v3h .arow .nm .chev { grid-area:chev; justify-self:start; }
            .v3h .arow.ahead > span { font-size:12px; white-space:normal; line-height:1.25; align-self:end; }
            .v3h .alev { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; padding-block:12px; border-bottom:1px solid var(--rule); }
            .v3h .alev small { display:block; font-size:13px; color:var(--dim); margin-bottom:4px; }
            .v3h .alev strong { font-size:18px; font-weight:400; }
        }
"""


# ───────────────────────── אחזקות ─────────────────────────

def _money_cell(value: float, sym: str, with_sign: bool = False, show_sym: bool = True) -> str:
    """סכום עם סמל מטבע קטן (₪ משמאל למספר, $ מימין); show_sym=False - המספר בלבד (בתאי הטבלה עצמה)."""
    n = f'<span class="n">{num(signed(value) if with_sign else plain(value))}</span>'
    if not show_sym:
        return n
    c = f'<span class="cur">{sym}</span>'
    return f"{n}{c}" if sym == CCY_SYMBOL["USD"] else f"{c}{n}"


def hold_head(day_label: str = "היום") -> str:
    """כותרות טבלת האחזקות: מניה | שווי | רווח/הפסד | יום | סטופ·יעד | ימים | גרף."""
    return (
        '<div class="hhead"><span>מניה</span><span class="r">שווי</span><span class="r">תשואה</span><span class="r">רווח/הפסד</span>'
        f'<span class="r">{esc(day_label)}</span><span>יעד · סטופ</span><span class="r">ימי החזקה</span><span class="r">נטו</span><span class="ctr">שינוי מקנייה</span></div>'
    )


def hold_row(name: str, mono: str, sym: str, value: float | None, share: float | None, pnl_amt: float | None, pnl_pct: float,
             day_amt: float | None, day_pct: float | None, stop_gap: float | None, tgt_gap: float | None,
             held: int | None, horizon: int | None, spark_prices=None, spark_base: float | None = None,
             signal: tuple[str, str] | None = None, out: bool = False, is_open: bool = False, net_amt: float | None = None) -> str:
    """שורת אחזקה בטבלה החדשה: שם + סיגנל כניסה, שווי ומשקל, רווח/הפסד (סכום ואחוז), שינוי היום, מרחק מסטופ ויעד, ימי החזקה, גרף, חץ."""
    dot = f'<i class="sd" style="background:{esc(signal[1])}" title="סיגנל כניסה: {esc(signal[0])}"></i>' if signal and signal[1] else ""
    nm = f'<span class="nm" title="{esc(name)}"><span class="l1">{dot}<bdi>{esc(short_name(name))}</bdi><span class="mono">{esc(mono)}</span>{_CHEV}</span></span>'
    val = (f'<span class="c"><b>{_money_cell(value, sym)}</b>'
           + (f'<small>{num(f"{share:.0f}%")} מהתיק</small>' if share is not None else "") + "</span>") if value is not None else '<span class="c"></span>'
    ret = f'<span class="c {cls_for(pnl_pct)}"><b>{num(signed(pnl_pct, 1, "%"))}</b></span>'
    pl = f'<span class="c {cls_for(pnl_pct)}"><b>{_money_cell(pnl_amt, sym, True, False) if pnl_amt is not None else ""}</b></span>'
    net = (f'<span class="c {cls_for(net_amt)}"><b>{_money_cell(net_amt, sym, True)}</b></span>' if net_amt is not None else '<span class="c"></span>')
    day = (f'<span class="c {cls_for(day_pct)}"><b>{_money_cell(day_amt, sym, True, False) if day_amt is not None else ""}</b>'
           f'<small>{num(signed(day_pct, 1, "%"))}</small></span>') if day_pct is not None else '<span class="c"></span>'
    lines = []
    if tgt_gap is not None:
        lines.append('<em class="up">מעל היעד</em>' if tgt_gap < 0 else f'<em>יעד <b class="up">{num(f"+{tgt_gap:.1f}%")}</b></em>')
    if stop_gap is not None:
        lines.append('<em class="down">מתחת לסטופ</em>' if stop_gap < 0 else f'<em>סטופ <b class="down">{num(f"-{stop_gap:.1f}%")}</b></em>')
    reach = f'<span class="c rc2">{"".join(lines)}</span>'
    hd = f'<span class="c"><b>{num(str(held))}</b></span>' if held is not None else '<span class="c"></span>'
    return (
        f'<div class="hrow{" out" if out else ""}{" open" if is_open else ""}">{nm}{val}{ret}{pl}{day}{reach}{hd}{net}'
        f'<span class="sp">{mini_spark(spark_prices, spark_base)}</span></div>'
    )


def hold_mobile_strip(value: float | None, sym: str, share: float | None, stop_gap: float | None, tgt_gap: float | None,
                      held: int | None, horizon: int | None, pnl_amt: float | None = None, net_amt: float | None = None) -> str:
    """בנייד העמודות הצפופות מוסתרות מהשורה - הן מופיעות כאן בראש הפרטים של השורה שנפתחת."""
    cells = []
    if pnl_amt is not None:
        cells.append(f'<div><small>רווח/הפסד</small><strong class="{cls_for(pnl_amt)}">{_money_cell(pnl_amt, sym, True)}</strong></div>')
    if net_amt is not None:
        cells.append(f'<div><small>נטו</small><strong class="{cls_for(net_amt)}">{_money_cell(net_amt, sym, True)}</strong></div>')
    if value is not None:
        cells.append(f'<div><small>שווי</small><strong>{_money_cell(value, sym)}</strong>'
                     + (f'<em>{num(f"{share:.0f}%")} מהתיק</em>' if share is not None else "") + "</div>")
    if stop_gap is not None or tgt_gap is not None:
        parts = []
        if tgt_gap is not None:
            parts.append("מעל היעד" if tgt_gap < 0 else f'יעד {num(f"+{tgt_gap:.1f}%")}')
        if stop_gap is not None:
            parts.append("מתחת לסטופ" if stop_gap < 0 else f'סטופ {num(f"-{stop_gap:.1f}%")}')
        cells.append(f'<div><small>יעד · סטופ</small><strong class="two">{"<br>".join(parts)}</strong></div>')
    if held is not None:
        cells.append(f'<div><small>ימי החזקה</small><strong>{num(str(held))}</strong></div>')
    return f'<div class="hmob">{"".join(cells)}</div>' if cells else ""


def range_text(rng) -> str:
    """שורת-משנה מתחת לשם האחזקה: 'המסלול' מאז הקנייה - השיא והשפל ביחס לשער הכניסה (מידע שלא מופיע בשום מקום אחר בטאב)."""
    if not rng:
        return ""
    hi, lo = rng
    # שני חלקים בשתי שורות (כל חלק לא נשבר באמצע) - אחרת "שפל" נשאר בשורה אחת והמספר שלו יורד לשורה הבאה
    return (f'<span style="white-space:nowrap">שיא <b class="{cls_for(hi)}">{num(signed(hi, 1, "%"))}</b></span><br>'
            f'<span style="white-space:nowrap">שפל <b class="{cls_for(lo)}">{num(signed(lo, 1, "%"))}</b></span>')


def mini_spark(prices, base: float | None = None) -> str:
    """גרף זעיר לשורת אחזקה: הקו הכהה = מחיר, הקו המקווקו = שער הכניסה, והשטח ביניהם צבוע (ירוק מעל הכניסה, אדום מתחתיה)."""
    if not prices or len(prices) < 2:
        return ""
    vals = list(prices) + ([base] if base else [])
    mn, mx = min(vals), max(vals)
    rg = (mx - mn) or 1.0
    w, h = 96, 34

    def y(v: float) -> float:
        return h - 5 - (v - mn) / rg * (h - 10)

    pts = [(i * (w - 8) / (len(prices) - 1) + 4, y(v)) for i, v in enumerate(prices)]
    up = (prices[-1] >= base) if base else (prices[-1] >= prices[0])
    col = "var(--gain)" if up else "var(--loss)"
    poly = " ".join(f"{x:.1f},{yy:.1f}" for x, yy in pts)
    lx, ly = pts[-1]
    base_svg = area = ""
    if base:
        by = y(base)
        base_svg = f'<line x1="2" y1="{by:.1f}" x2="{w - 2}" y2="{by:.1f}" stroke="var(--dim)" stroke-width="1" stroke-dasharray="2 3"/>'
        area = f'<polygon points="{pts[0][0]:.1f},{by:.1f} {poly} {lx:.1f},{by:.1f}" fill="{col}" fill-opacity=".14"/>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">{area}{base_svg}'
            f'<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="1.5" stroke-linejoin="round"/><circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.6" fill="{col}"/></svg>')


_SECTOR_TONES = ["#2F5D50", "#8A6F3C", "#4A6580", "#8C4B3B", "#6B5B7A", "#6F7A4F", "#9A8F7E"]


def allocation_bar(items: list[dict]) -> str:
    """פס הרכב התיק: קו דק לכל אחזקה, רוחב לפי משקלה בתיק, בגוונים נייטרליים (כהה = משקל גדול); מתחת לכל קו השם והאחוז. items: {name, share (% מהתיק), pnl_pct}."""
    items = sorted([i for i in items if i["share"] > 0], key=lambda i: -i["share"])
    if not items:
        return ""
    total = sum(i["share"] for i in items)
    alphas = [90, 66, 48, 34, 24, 18]  # גוון כהה יותר = משקל גדול יותר
    segs = "".join(
        f'<div class="ab" style="flex:{i["share"]:.3f} 1 0" '
        f'title="{esc(i["name"])} · {i["share"] / total * 100:.0f}% מהתיק · {signed(i["pnl_pct"] or 0, 1, "%")}">'
        f'<span class="abs" style="background:color-mix(in srgb, var(--ink) {alphas[min(k, len(alphas) - 1)]}%, transparent)"></span>'
        f'<span class="abl"><span class="abn">{esc(short_name(i["name"]))}</span><span class="abp">{num(f"{i["share"] / total * 100:.0f}%")}</span></span></div>'
        for k, i in enumerate(items)
    )
    return f'<div class="abar">{segs}</div>'


def sector_section(items: list[dict], title: str = "התפלגות סקטוריאלית") -> str:
    """התפלגות סקטוריאלית: טבעת דקה (עוגה בשפת האתר - קו עדין, גוונים מעומעמים, מרווחים בין הפלחים) + רשימה (נקודה, שם, מניות, אחוז).
    items: {label, pct, names:[...]}, ממוין יורד."""
    items = [i for i in items if i["pct"] > 0]
    if not items:
        return ""
    r, circ, gap = 74.0, 2 * math.pi * 74.0, 3.0
    hhi = sum((i["pct"] / sum(x["pct"] for x in items)) ** 2 for i in items)  # מדד הרפינדל-הירשמן: 1 = הכל בסקטור אחד
    conc, conc_color = (("נמוך", "var(--gain)") if hhi < 0.25 else (("בינוני", "#8A6F3C") if hhi < 0.5 else ("גבוה", "var(--loss)")))
    segs, offset = [], 0.0
    for k, i in enumerate(items):
        length = max(i["pct"] / 100.0 * circ - gap, 1.5)
        segs.append(
            f'<circle cx="100" cy="100" r="{r:.0f}" fill="none" stroke="{_SECTOR_TONES[k % len(_SECTOR_TONES)]}" stroke-width="11" '
            f'stroke-dasharray="{length:.2f} {circ - length:.2f}" stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 100 100)">'
            f'<title>{esc(i["label"])} {i["pct"]:.0f}%</title></circle>'
        )
        offset += i["pct"] / 100.0 * circ
    donut = (
        '<figure class="sdonut"><svg viewBox="0 0 200 200" role="img" aria-label="התפלגות סקטוריאלית">'
        f'<circle cx="100" cy="100" r="{r:.0f}" fill="none" stroke="var(--rule)" stroke-width="1" stroke-dasharray="2 4"/>'
        + "".join(segs) +
        '</svg>'
        f'<figcaption class="sdc"><span>ריכוז סקטוריאלי</span><strong style="color:{conc_color}">{conc}</strong></figcaption></figure>'
    )
    top = max(i["pct"] for i in items) or 1.0
    rows = "".join(
        f'<div class="srow"><span class="dot" style="background:{_SECTOR_TONES[k % len(_SECTOR_TONES)]}"></span>'
        f'<span class="sn"><b>{esc(i["label"])}</b><small>{esc(", ".join(short_name(n) for n in i["names"]))}</small></span>'
        f'<span class="sbar"><i style="width:{i["pct"] / top * 100:.0f}%;background:{_SECTOR_TONES[k % len(_SECTOR_TONES)]}"></i></span>'
        f'<span class="sp2">{num(f"{i['pct']:.0f}%")}</span></div>'
        for k, i in enumerate(items)
    )
    return f'{head(title)}<div class="sgrid"><div class="slist">{rows}</div>{donut}</div>'


def holdings_overview(invested: float, value: float, count: int, pnl: float, pnl_pct: float,
                      day_amt: float | None, day_pct: float | None, ccy: str) -> str:
    """פתיחת טאב האחזקות: סקירה בארבעה תאים (הושקע / שווי נוכחי / רווח-הפסד כולל / שינוי יומי) - ניסוח ופריסה שונים מ'התיק שלי' שבעמוד הבית."""
    usd = ccy == "USD"
    def m(v: float, signed_: bool = False) -> str:
        t = signed(v) if signed_ else plain(v)
        return f"{t}$" if usd else f"₪ {t}"
    def cell(label: str, val: str, cls: str = "", sub_html: str = "") -> str:
        return f'<div><small>{esc(label)}</small><strong class="{cls}">{num(val)}' + (f'<em>{sub_html}</em>' if sub_html else "") + '</strong></div>'
    day_cell = (cell("שינוי יומי", m(day_amt, True), cls_for(day_amt), num(signed(day_pct, 1, "%")))
                if day_amt is not None and day_pct is not None else cell("שינוי יומי", "—"))
    inner = (
        cell("הושקע", m(invested), "", f"{count} אחזקות")
        + cell("שווי נוכחי", m(value))
        + cell("רווח/הפסד כולל", m(pnl, True), cls_for(pnl), num(signed(pnl_pct, 1, "%")))
        + day_cell
    )
    return head("סקירת האחזקות") + f'<div class="kpi k4">{inner}</div>'


def portfolio_map(items: list[dict]) -> str:
    """מפת התיק (heatmap): אריח לכל אחזקה, רוחב לפי חלקה בתיק, צבע וגוון לפי הרווח/הפסד - ירוק/אדום, עוצמה לפי גודל השינוי.
    items: {name, share (% מהתיק), pnl_pct, daily_pct}."""
    items = sorted([i for i in items if i["share"] > 0], key=lambda i: -i["share"])
    if not items:
        return ""
    tiles = []
    for i in items:
        p = i["pnl_pct"]
        strength = min(abs(p) / 12.0, 1.0) * 46 + 10
        tone = "var(--gain)" if p >= 0 else "var(--loss)"
        tiles.append(
            f'<div class="tile" style="flex:{i["share"]:.2f} 1 0; background:color-mix(in srgb, {tone} {strength:.0f}%, var(--surface));" '
            f'title="{esc(i["name"])} · {i["share"]:.0f}% מהתיק">'
            f'<span class="tn">{esc(short_name(i["name"]))}</span>'
            f'<b class="{cls_for(p)}">{num(signed(p, 1, "%"))}</b></div>'
        )
    return f'<div class="pmap">{"".join(tiles)}</div><div class="pcap">רוחב האריח = משקל בתיק · צבע = רווח/הפסד</div>'


def total_line(pnl: float, pnl_pct: float, day_amt: float | None, day_pct: float | None, ccy: str, day_label: str = "שינוי יומי") -> str:
    """סיכום שקט בשורה אחת מתחת לטבלת האחזקות: "סה"כ רווח/הפסד -2,535 ₪ · -7.5%   ·   היום -160 ₪ · -0.5%" - בלי קווים ובלי קופסאות."""
    sym = CCY_SYMBOL.get(ccy, esc(ccy))

    def part(label: str, a: float, p: float) -> str:
        c = cls_for(a)
        return (f'<span class="tl"><small>{esc(label)}</small><b class="{c}">{money(num(signed(a)), sym)}</b>'
                f'<i class="{c}">{num(signed(p, 1, "%"))}</i></span>')

    inner = part("רווח/הפסד", pnl, pnl_pct)
    if day_amt is not None and day_pct is not None:
        inner += part(day_label, day_amt, day_pct)
    return f'<div class="tline">{inner}</div>'


def total_pill(pnl: float, pnl_pct: float, day_amt: float | None, day_pct: float | None, ccy: str) -> str:
    """סה"כ מתחת לטבלת האחזקות, בשפת שאר האתר: פס KPI דק (בלי כרטיס ובלי צ'יפים) - סכום גדול ואחוז קטן מתחתיו בצבע הסימן."""
    sym = CCY_SYMBOL.get(ccy, esc(ccy))

    def cell(label: str, a: float, p: float) -> str:
        c = cls_for(a)
        return (f'<div><small>{esc(label)}</small><strong class="{c}">{money(num(signed(a)), sym)}</strong>'
                f'<em class="{c}">{num(signed(p, 1, "%"))}</em></div>')

    inner = cell('סה"כ רווח/הפסד', pnl, pnl_pct)
    if day_amt is not None and day_pct is not None:
        inner += cell("שינוי יומי", day_amt, day_pct)
    return f'<div class="kpi ktot">{inner}</div>'


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


def hold_card(cost: str, qty: str, fees: str, bought: str, signal: tuple[str, str] | None, score: tuple, alert_pct: float | None,
              range_html: str, stop_px: str, tgt_px: str, sector: str, mobile_strip: str = "") -> str:
    """כרטיס האחזקה שנפתח (8 תאים, שתי שורות): רק מה שאינו בעמודות הטבלה - עלות וכמות, עמלות ומס, תאריך קנייה, סיגנל כניסה וציון,
    גודל הירידה בזמן ההתראה, שיא ושפל מאז הקנייה, סטופ ויעד במחיר, סקטור."""
    def cell(label: str, val: str, sub: str = "") -> str:
        return f'<div class="hc"><small>{label}</small><span class="v">{val}{f" <em>· {sub}</em>" if sub else ""}</span></div>'

    sig_txt, sig_col = (signal or ("", ""))
    sc, mx = score if score else (None, None)
    sig = (f'<span style="color:{esc(sig_col)}">{esc(sig_txt)}</span>' if sig_txt and sig_col else esc(sig_txt)) if sig_txt else "—"
    sig_sub = ("ציון " + num(f"{max(sc, 0)}/{mx}")) if sc is not None and mx else ""
    drop = f'<span class="{cls_for(alert_pct)}">{num(signed(alert_pct, 1, "%"))}</span>' if alert_pct is not None else "—"
    stop_html = f'<span class="down">{num(stop_px)}</span>' if stop_px else "—"
    tgt_html = f'<span class="up">{num(tgt_px)}</span>' if tgt_px else "—"
    cells = [
        cell("תאריך קנייה", num(bought) if bought else "—"),
        cell("סיגנל כניסה", sig, sig_sub),
        cell("ירידה בזמן ההתראה", drop),
        cell("עלות", num(cost), (num(qty) + " יחידות") if qty else ""),
        cell("יעד · סטופ (מחיר)", tgt_html + " · " + stop_html),
        cell("שיא / שפל מאז הקנייה", (range_html.replace("<br>", " · ") if range_html else "—")),
        cell("סקטור", esc(sector) if sector else "—"),
        cell("עמלות ומס", num(fees) if fees else "—"),
    ]
    return f'{mobile_strip}<div class="hcg">{"".join(cells)}</div>'


HOLDINGS_CSS = """
        .v3h .lg { display:flex; gap:22px; margin:14px 0 6px; font-size:13px; color:var(--dim); direction:rtl; justify-content:flex-start; }
        .v3h .lg span { display:inline-flex; align-items:center; gap:7px; }
        .v3h .lg .tk { display:inline-block; position:static; width:2px; height:12px; background:var(--dim); }
        .v3h .lg .tk.s { background:var(--loss); } .v3h .lg .tk.t { background:var(--gain); }
        .v3h .lg .mk { position:static; width:9px; height:9px; margin:0; }
        .v3h .ladder { display:flex; flex-direction:column; }
        .v3h .lr { display:grid; grid-template-columns:110px minmax(0,1fr) 64px; align-items:center; gap:16px; padding:16px 10px; border-bottom:1px solid var(--rule); }
        .v3h .lr .ln { font-size:16px; color:var(--v3-soft); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .v3h .lr .ln.out { color:var(--loss); font-weight:600; }
        .v3h .lr .lt { position:relative; height:18px; direction:ltr; }
        .v3h .lr .lt::before { content:''; position:absolute; left:0; right:0; top:8px; height:2px; background:var(--rule); }
        .v3h .lr .lz { position:absolute; top:7px; height:4px; border-radius:2px; }
        .v3h .lr .lz.l { background:color-mix(in srgb, var(--loss) 42%, transparent); }
        .v3h .lr .lz.g { background:color-mix(in srgb, var(--gain) 42%, transparent); }
        .v3h .lr .tk { position:absolute; top:3px; width:2px; height:12px; margin-left:-1px; background:var(--dim); }
        .v3h .lr .tk.s { background:var(--loss); } .v3h .lr .tk.t { background:var(--gain); }
        .v3h .mk { position:absolute; top:4px; width:10px; height:10px; margin-left:-5px; border-radius:50%; background:var(--ink); display:inline-block; }
        .v3h .mk.out { background:var(--loss); box-shadow:0 0 0 4px color-mix(in srgb, var(--loss) 22%, transparent); }
        .v3h .mk.hit { background:var(--gain); box-shadow:0 0 0 4px color-mix(in srgb, var(--gain) 22%, transparent); }
        .v3h .lr .lv { font-size:15px; direction:ltr; text-align:end; }
        .v3h .lr .lv.up { color:var(--gain); } .v3h .lr .lv.down { color:var(--loss); }
        @media (max-width:720px) { .v3h .lr { grid-template-columns:70px minmax(0,1fr) 54px; gap:10px; padding:14px 4px; } .v3h .lr .ln { font-size:15px; } }
        .v3h .kpi.pstrip > div:not(:first-child) em { margin-top:auto; }  /* האחוזים בתאים האחרים באותו גובה כמו פס ההרכב */
        .v3h .abar { display:flex; gap:3px; margin-top:14px; width:100%; }
        .v3h .abar .ab { min-width:0; display:flex; flex-direction:column; gap:3px; }
        .v3h .abar .abs { height:3px; border-radius:2px; margin-bottom:4px; }
        .v3h .abar .abl { display:flex; align-items:baseline; gap:5px; min-width:0; line-height:1.3; }
        .v3h .abar .abn { font-size:12px; color:var(--dim); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }
        .v3h .abar .abp { font-size:12px; color:var(--v3-soft); flex:none; }
        .v3h .sgrid { display:flex; align-items:center; gap:56px; margin-top:22px; }
        .v3h .sdonut { margin:0; flex:none; width:216px; position:relative; }
        .v3h .sdonut .sdc { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; text-align:center; pointer-events:none; }
        .v3h .sdonut .sdc span { font-size:12px; color:var(--dim); }
        .v3h .sdonut .sdc strong { font-size:21px; font-weight:400; }
        .v3h .sdonut svg { display:block; width:100%; height:auto; overflow:visible; }
        .v3h .slist { flex:1 1 auto; min-width:0; }
        .v3h .srow { display:grid; grid-template-columns:10px 104px minmax(60px,1fr) 44px; align-items:center; gap:14px; padding:15px 8px; border-bottom:1px solid color-mix(in srgb, var(--rule) 70%, transparent); }
        .v3h .srow .dot { width:8px; height:8px; border-radius:50%; opacity:.85; }
        .v3h .srow .sn b { display:block; font-size:15px; font-weight:400; color:var(--v3-soft); }
        .v3h .srow .sn small { display:block; margin-top:2px; font-size:12px; color:var(--dim); opacity:.85; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .v3h .srow .sbar { display:block; height:3px; border-radius:2px; background:color-mix(in srgb, var(--rule) 55%, transparent); }
        .v3h .srow .sbar i { display:block; height:100%; border-radius:2px; opacity:.8; }
        .v3h .srow .sp2 { font-size:14px; font-weight:400; direction:ltr; text-align:end; color:var(--dim); font-variant-numeric:tabular-nums; }
        @media (max-width:720px) {
            .v3h .sgrid { flex-direction:column; align-items:stretch; gap:16px; }
            .v3h .sdonut { width:200px; max-width:100%; margin-inline:auto; order:-1; }
            .v3h .srow { grid-template-columns:10px minmax(0,1fr) 44px; gap:8px 12px; padding:13px 6px; }
            .v3h .srow .sn { grid-column:2; grid-row:1; }
            .v3h .srow .sbar { grid-column:2; grid-row:2; }
            .v3h .srow .sp2 { grid-column:3; grid-row:1 / 3; }
        }
        .v3h .pmap { display:flex; gap:4px; margin:14px 0 6px; height:78px; }
        .v3h .pmap .tile { min-width:46px; border-radius:10px; padding:9px 10px; display:flex; flex-direction:column; justify-content:space-between; overflow:hidden; }
        .v3h .pmap .tn { font-size:12px; color:var(--v3-ink); font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .v3h .pmap .tile b { font-size:16px; font-weight:400; line-height:1.1; direction:ltr; text-align:right; }
        .v3h .pmap .tile b.up { color:var(--gain); } .v3h .pmap .tile b.down { color:var(--loss); }
        .v3h .pcap { font-size:11px; color:var(--dim); text-align:right; }
                .v3h .tline { display:flex; flex-wrap:wrap; gap:6px 40px; padding:18px 10px 4px; align-items:baseline; }
        .v3h .tl { display:inline-flex; align-items:baseline; gap:10px; }
        .v3h .tl small { font-size:13px; color:var(--dim); }
        .v3h .tl b { font-size:19px; font-weight:400; }
        .v3h .tl i { font-style:normal; font-size:14px; }
        .v3h .tl .up { color:var(--gain); } .v3h .tl .down { color:var(--loss); }
        .v3h .kpi.ktot { grid-template-columns:repeat(2,minmax(0,1fr)); margin-top:22px; border-top:0; }
        .v3h .kpi.ktot > div { padding:16px 18px 18px; border-top:0 !important; }
        .v3h .kpi.ktot > div:first-child { grid-column:auto; padding-inline-start:0; border-inline-start:0; }
        .v3h .kpi.ktot > div:nth-child(2) { border-inline-start:1px solid var(--rule); padding-inline-start:18px; }
        .v3h .kpi.ktot strong { font-size:clamp(22px,2.4vw,28px); font-weight:400; }
        .v3h .kpi.ktot em { font-size:15px; }
.v3h .tpill { display:flex; align-items:stretch; gap:0; margin:18px 0 6px; background:var(--surface); border:1px solid var(--rule); border-radius:8px; }
        .v3h .tpill .tb { flex:1 1 0; padding:16px 22px 18px; min-width:0; }
        .v3h .tpill .tb small { display:block; font-size:13px; color:var(--dim); margin-bottom:8px; }
        .v3h .tpill .tv { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 12px; }
        .v3h .tpill strong { font-size:26px; font-weight:400; direction:ltr; line-height:1; white-space:nowrap; }
        .v3h .tpill strong.up { color:var(--gain); } .v3h .tpill strong.down { color:var(--loss); }
        .v3h .tpill .chip { font-size:14px; padding:2px 8px; border-radius:5px; direction:ltr; }
        .v3h .tpill .chip.up { color:var(--gain); background:color-mix(in srgb, var(--gain) 11%, transparent); }
        .v3h .tpill .chip.down { color:var(--loss); background:color-mix(in srgb, var(--loss) 11%, transparent); }
        .v3h .tpill .tsep { width:1px; background:var(--rule); }
        /* טבלת האחזקות: מניה | שווי | רווח/הפסד | יום | סטופ·יעד | ימי החזקה | גרף | חץ */
        .v3h .hhead, .v3h .hrow { display:grid; grid-template-columns:minmax(0,1.2fr) 104px 74px 86px 98px 100px 74px 86px 96px; align-items:center; gap:10px; padding-inline:10px; }
        .v3h .hhead { padding-block:12px 10px; font-size:13px; color:var(--dim); border-bottom:1px solid var(--rule); }
        .v3h .hhead span { white-space:nowrap; }
        .v3h .hhead .r { text-align:end; } .v3h .hhead .ctr { text-align:center; }
        .v3h .hrow { padding-block:14px; border-bottom:1px solid var(--rule); }
        .v3h .hrow:hover { background:var(--hover); }
        .v3h .hrow .nm { font-size:17px; color:var(--v3-soft); min-width:0; }
        .v3h .hrow .nm .l1 { display:flex; align-items:baseline; white-space:nowrap; }
        .v3h .hrow .nm .sd { display:inline-block; width:8px; height:8px; border-radius:50%; margin-inline-end:9px; flex:none; align-self:center; }
        .v3h .hrow .nm .mono { margin-inline-start:10px; }
        .v3h .hrow.out .nm { font-weight:600; color:var(--loss); }
        .v3h .hrow .c { display:flex; flex-direction:column; align-items:flex-end; gap:3px; direction:ltr; line-height:1.15; }
        .v3h .hrow .c b { display:inline-flex; align-items:baseline; gap:4px; font-size:16px; font-weight:500; white-space:nowrap; }
        .v3h .hrow .c b .cur { font-size:12px; font-weight:400; opacity:.85; }
        .v3h .hrow .c small { font-size:12px; color:var(--dim); white-space:nowrap; direction:rtl; }
        .v3h .hrow .c.up b, .v3h .hrow .c.up small { color:var(--gain); } .v3h .hrow .c.down b, .v3h .hrow .c.down small { color:var(--loss); }
        .v3h .hrow .c.warn b, .v3h .hrow .c.warn small { color:var(--loss); }
        .v3h .hrow .rc2 { align-items:flex-start; direction:rtl; gap:4px; }
        .v3h .hrow .rc2 em { font-style:normal; font-size:13px; color:var(--dim); white-space:nowrap; }
        .v3h .hrow .rc2 em b { display:inline; font-size:13px; font-weight:500; }
        .v3h .hrow .rc2 em b.up { color:var(--gain); } .v3h .hrow .rc2 em b.down { color:var(--loss); }
        .v3h .hrow .rc2 em.down { color:var(--loss); } .v3h .hrow .rc2 em.up { color:var(--gain); }
        .v3h .hrow .sp { display:flex; justify-content:center; } .v3h .hrow .sp svg { display:block; }
        .v3h .hrow .chev { color:var(--dim); transition:transform .15s; transform:scaleX(-1); align-self:center; margin-inline-start:10px; flex:none; }
        .v3h .hrow.open .chev { transform:scaleX(-1) rotate(90deg); }
        .v3h .hmob { display:none; }
        .v3h .bar { position:relative; height:2px; background:var(--rule); margin:16px 10px 32px; direction:ltr; }
        .v3h .bar .sg { position:absolute; top:0; height:2px; }
        .v3h .bar .sg.l { background:color-mix(in srgb, var(--loss) 55%, transparent); } .v3h .bar .sg.g { background:color-mix(in srgb, var(--gain) 55%, transparent); }
        .v3h .bar .mk { position:absolute; top:-6px; width:14px; height:14px; margin-left:-7px; border-radius:50%; background:var(--ink); }
        .v3h .bar .mk.out { background:var(--loss); box-shadow:0 0 0 5px color-mix(in srgb, var(--loss) 20%, transparent); }
        .v3h .bar .tk { position:absolute; top:-5px; width:1px; height:12px; background:var(--dim); }
        .v3h .bar .tk.s { background:var(--loss); } .v3h .bar .tk.t { background:var(--gain); }
        .v3h .bar .lb { position:absolute; top:14px; font-size:12px; color:var(--dim); transform:translateX(-50%); white-space:nowrap; direction:rtl; }
        .v3h .bar .lb.a { transform:none; color:var(--loss); } .v3h .bar .lb.r { right:0; left:auto; transform:none; color:var(--gain); }
        .v3h .hdet { padding:6px 10px 14px; border-bottom:1px solid var(--rule); }
        .v3h .hcg { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; padding-top:6px; }
        .v3h .hc { padding:14px 18px 14px 0; display:flex; flex-direction:column; gap:5px; min-width:0; }
        .v3h .hc:nth-child(n+5) { border-top:1px solid var(--rule); }
        .v3h .hc small { font-size:12px; color:var(--dim); letter-spacing:.01em; }
        .v3h .hc .v { font-size:17px; color:var(--v3-soft); line-height:1.25; white-space:nowrap; }
        .v3h .hc .v .up { color:var(--gain); } .v3h .hc .v .down { color:var(--loss); }
        .v3h .hc .v b { font-size:15px; font-weight:500; }
        .v3h .hc .v em { font-style:normal; font-size:13px; color:var(--dim); }
        @media (max-width:720px) {
            .v3h .hhead span:nth-child(2), .v3h .hhead span:nth-child(4), .v3h .hhead span:nth-child(n+6) { display:none; }  /* נשארים: מניה | תשואה | היום */
            .v3h .hhead { padding-block:8px 6px; }
            .v3h .hhead, .v3h .hrow { grid-template-columns:minmax(0,1fr) 62px 74px; gap:10px; }
            .v3h .hrow > .c:nth-child(2), .v3h .hrow > .c:nth-child(4), .v3h .hrow > .rc2, .v3h .hrow > .c:nth-child(7), .v3h .hrow > .c:nth-child(8), .v3h .hrow > .sp { display:none; }
            .v3h .hcg { grid-template-columns:repeat(2,minmax(0,1fr)); } .v3h .hc:nth-child(n+3) { border-top:1px solid var(--rule); }
            .v3h .hc .v { white-space:normal; overflow-wrap:anywhere; }
            .v3h .hmob { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; padding:12px 0 6px; border-bottom:1px solid var(--rule); margin-bottom:12px; }
            .v3h .hmob small { display:block; font-size:12px; color:var(--dim); margin-bottom:3px; }
            .v3h .hmob strong { font-size:16px; font-weight:500; display:inline-flex; gap:4px; align-items:baseline; direction:ltr; }
            .v3h .hmob strong .cur { font-size:12px; font-weight:400; }
            .v3h .hmob strong.up { color:var(--gain); } .v3h .hmob strong.down { color:var(--loss); }
            .v3h .hmob strong.two { display:block; direction:rtl; font-size:13px; line-height:1.5; }
            .v3h .hmob em { display:block; font-style:normal; font-size:12px; color:var(--dim); }
        }
"""


# ───────────────────────── יומן עסקאות ─────────────────────────

def journal_kpi(cells: list[tuple]) -> str:
    """cells: [(label, value_text, css_class[, sub_text])] - שורת סיכומים בעמודות שוות (מספר העמודות נקבע לפי מספר התאים)."""
    inner = "".join(
        f'<div><small>{esc(c[0])}</small><strong class="{c[2]}">{num(c[1])}</strong>' + (f'<em class="ms">{c[3]}</em>' if len(c) > 3 else "") + "</div>"
        for c in cells
    )
    return f'<div class="kpi kn" style="grid-template-columns:repeat({len(cells)},minmax(0,1fr))">{inner}</div>'


JOURNAL_KPI_CSS = """
        .v3h .kpi.kn em.ms { display:block; margin-top:2px; font-style:normal; font-size:13px; color:var(--dim); }
        @media (max-width:480px) {
            .v3h .kpi.kn { grid-template-columns:repeat(2,minmax(0,1fr)) !important; margin-top:16px; }
            .v3h .kpi.kn > div { padding:12px 12px 14px; border-top:1px solid var(--rule) !important; border-inline-start:1px solid var(--rule); }
            .v3h .kpi.kn > div:nth-child(-n+2) { border-top:0 !important; }
            .v3h .kpi.kn > div:nth-child(odd) { border-inline-start:0; padding-inline-start:0; }
            .v3h .kpi.kn > div:first-child { grid-column:auto !important; }
            .v3h .kpi.kn small { font-size:12px; }
            .v3h .kpi.kn strong { font-size:22px; }
        }
"""


_OUTCOME_CLS = {"הגיעה ליעד": "up", "רווח לפני היעד": "up", "פגע בסטופ": "down"}


_HE_MONTHS = ("ינו'", "פבר'", "מרץ", "אפר'", "מאי", "יוני", "יולי", "אוג'", "ספט'", "אוק'", "נוב'", "דצמ'")


def _nice_ticks(lo: float, hi: float, want: int = 4) -> list[float]:
    raw = (hi - lo) / max(want, 1)
    if raw <= 0:
        return [0.0]
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 6))
        t += step
    return out


def equity_curve(points: list[dict], sym: str = "₪") -> str:
    """עקומת רווח נקי מצטבר. points (לפי סדר כרונולוגי): {ts: חותמת זמן, date: 'dd.mm', name, net: רווח העסקה, cum: מצטבר}.
    כל נקודה = עסקה שנסגרה; גובה הנקודה = הרווח הנקי המצטבר עד אליה; ריחוף מציג את פרטי העסקה. צירי ערך ותאריך, קו אפס, תווית סכום בקצה."""
    if len(points) < 2:
        return ""
    vals = [p["cum"] for p in points]
    lo, hi = min(min(vals), 0.0), max(max(vals), 0.0)
    if hi - lo < 1:
        hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.10
    lo, hi = lo - pad, hi + pad
    t0, t1 = points[0]["ts"], points[-1]["ts"]
    span = (t1 - t0) or 1.0

    def px(t: float) -> float:  # אחוז רוחב: הנקודה הראשונה והאחרונה בקצוות האזור (השוליים של 5px בעיצוב משאירים את הנקודות בתוך קו הכותרת)
        return 100.0 * (t - t0) / span

    def py(v: float) -> float:  # אחוז גובה
        return (hi - v) / (hi - lo) * 100.0

    col = "var(--gain)" if vals[-1] >= 0 else "var(--loss)"
    W, H = 1000, 100
    coords = [(px(p["ts"]) * W / 100.0, py(p["cum"]) * H / 100.0) for p in points]
    poly = " ".join(f"{x:.1f},{y:.2f}" for x, y in coords)
    y0 = py(0.0) * H / 100.0
    area = f'<polygon points="{coords[0][0]:.1f},{y0:.2f} {poly} {coords[-1][0]:.1f},{y0:.2f}" fill="{col}" fill-opacity=".09"/>'
    ticks = _nice_ticks(lo, hi)
    grid = "".join(
        f'<line x1="0" y1="{py(t) * H / 100:.2f}" x2="{coords[-1][0]:.1f}" y2="{py(t) * H / 100:.2f}" stroke="var(--rule-strong)" '
        f'stroke-opacity="{1 if abs(t) < 1e-9 else .35}" stroke-width="1" stroke-dasharray="{"3 5" if abs(t) < 1e-9 else "1 4"}" vector-effect="non-scaling-stroke"/>'
        for t in ticks
    )
    ylab = "".join(
        f'<span class="eqy" style="top:{py(t):.2f}%">{num(("0" if abs(t) < 1e-9 else f"{t:,.0f}"))}</span>'
        for t in ticks
    )
    dots = []
    for p, (x, y) in zip(points, coords):
        cls = "up" if p["net"] >= 0 else "down"
        xp = x / W * 100
        side = " r" if xp > 72 else (" l" if xp < 28 else "")
        tip = (
            f'<b class="eqt"><span class="t">{esc(p["name"])} · {num(p.get("full") or p["date"])}</span>'
            f'<span>רווח העסקה<em class="{cls}">{num(signed(p["net"]))}</em></span>'
            f'<span>מצטבר<em class="{cls_for(p["cum"])}">{num(signed(p["cum"]))}</em></span></b>'
        )
        dots.append(f'<i class="eqd {cls}{side}" style="left:{xp:.2f}%;top:{y / H * 100:.2f}%">{tip}</i>')
    # ציר תחתון: חודש ושנה (אוק' 26) - מיקום לפי תחילת החודש, ובחודש הראשון לפי תחילת הטווח
    from datetime import datetime as _dtm
    first, last = _dtm.fromtimestamp(t0), _dtm.fromtimestamp(t1)
    xl, y_, m_ = [], first.year, first.month
    while (y_, m_) <= (last.year, last.month):
        ts_m = max(_dtm(y_, m_, 1).timestamp(), t0)
        xl.append(f'<span style="left:{px(ts_m):.2f}%"><bdi dir="rtl">{_HE_MONTHS[m_ - 1]} {y_ % 100:02d}</bdi></span>')
        y_, m_ = (y_ + 1, 1) if m_ == 12 else (y_, m_ + 1)
    return (
        f'{head("מסלול רווח/הפסד")}'
        f'<div class="eq"><div class="eqp"><div class="eqyl">{ylab}</div>'
        f'<div class="eqa"><svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="מסלול רווח/הפסד">'
        f'{grid}{area}<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>'
        f'{"".join(dots)}</div></div>'
        f'<div class="eqx"><div class="eqxl">{"".join(xl)}</div></div></div>'
    )


def journal_table(rows: list[dict]) -> str:
    """rows: name, mono, sig_key, sig_label, manual, entry_px, entry_dt, exit_px, exit_dt, days, outcome, pct, gross, net, ccy."""
    body = []
    for r in rows:
        sig = f'סיגנל <span class="{ {"buy": "up", "wait": "warn", "avoid": "down"}.get(r["sig_key"], "")}">{esc(r["sig_label"])}</span>' if r.get("sig_label") else ""
        sub_bits = [b for b in (sig, "ידנית" if r.get("manual") else "") if b]
        sub = f'<span class="sub">{" · ".join(sub_bits)}</span>' if sub_bits else ""
        oc = _OUTCOME_CLS.get(r["outcome"]) or cls_for(r["gross"]) or "dim"  # תוצאה ניטרלית (נמכרה ידנית / חזרה מסטופ) נצבעת לפי הרווח או ההפסד בפועל
        body.append(
            f'<tr><td><span class="nm" title="{esc(r["name"])}"><bdi>{esc(short_name(r["name"]))}</bdi><span class="mono">{esc(r["mono"])}</span></span>{sub}</td>'
            f'<td class="c-entry"><span class="px">{num(r["entry_px"])}</span><span class="sub">{num(r["entry_dt"])}</span></td>'
            f'<td class="c-exit"><span class="px">{num(r["exit_px"])}</span><span class="sub">{num(r["exit_dt"])}</span></td>'
            f'<td>{num(r["days"])}</td><td class="c-res"><span class="res {oc}">{esc(r["outcome"])}</span></td>'
            f'<td><span class="pct {cls_for(r["gross"])}">{num(signed(r["pct"], 1, "%"))}</span></td>'
            f'<td class="c-gross"><span class="amt {cls_for(r["gross"])}">{num(signed(r["gross"]))}</span></td>'
            f'<td class="c-net"><span class="net {cls_for(r["net"])}">{num(signed(r["net"]))}</span></td>'
            f'<td class="c-ccy"><span class="mono">{esc(r["ccy"])}</span></td></tr>'
        )
    cols = ["20", "11", "11", "8", "15", "9", "10", "10", "6"]
    colgroup = "<colgroup>" + "".join(
        f'<col{(" class=" + chr(34) + cl + chr(34)) if cl else ""} style="width:{w}%">'
        for w, cl in zip(cols, ["", "c-entry", "c-exit", "", "c-res", "", "c-gross", "c-net", "c-ccy"])
    ) + "</colgroup>"
    head_cells = ["מניה", "כניסה", "יציאה", "ימי החזקה", "תחזית מול ביצוע", "תשואה", "רווח/הפסד", "נטו", "מטבע"]
    cls = ["", "c-entry", "c-exit", "", "c-res", "", "c-gross", "c-net", "c-ccy"]
    ths = "".join(f'<th class="{c}">{h}</th>' for h, c in zip(head_cells, cls))
    return (
        f'<div class="tablewrap"><table class="jr">{colgroup}<thead><tr>{ths}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    )


JOURNAL_CSS = """
        .v3h .tablewrap { overflow-x:auto; }
        .v3h .eq { padding:14px 0 6px; }
        .v3h .eqp { display:flex; direction:ltr; height:190px; }
        .v3h .eqyl { position:relative; flex:none; width:64px; }
        .v3h .eqy { position:absolute; right:8px; transform:translateY(-50%); font-size:12px; color:var(--dim); white-space:nowrap; }
        .v3h .eqa { position:relative; flex:1 1 auto; margin-inline:5px; }
        .v3h .eqa svg { display:block; width:100%; height:100%; overflow:visible; }
        .v3h .eqd { position:absolute; width:9px; height:9px; margin:-4.5px 0 0 -4.5px; border-radius:50%; background:var(--v3-bg); border:1.6px solid var(--dim); cursor:default; box-sizing:border-box; }
        .v3h .eqd::after { content:''; position:absolute; inset:-7px; }
        .v3h .eqt { display:none; position:absolute; bottom:calc(100% + 9px); left:50%; transform:translateX(-50%); z-index:5; min-width:150px; direction:rtl; text-align:right; padding:8px 12px; background:var(--v3-surface); border:1px solid var(--rule-strong); border-radius:6px; box-shadow:0 4px 14px rgba(0,0,0,.12); font-style:normal; font-weight:400; font-size:13px; line-height:1.5; color:var(--v3-soft); white-space:nowrap; }
        .v3h .eqd.l .eqt { left:-8px; transform:none; } .v3h .eqd.r .eqt { left:auto; right:-8px; transform:none; }
        .v3h .eqd:hover { z-index:6; } .v3h .eqd:hover .eqt { display:block; }
        .v3h .eqt > span { display:flex; justify-content:space-between; align-items:baseline; gap:18px; }
        .v3h .eqt > .t { font-weight:500; color:var(--ink); margin-bottom:2px; display:block; }
        .v3h .eqt em { font-style:normal; direction:ltr; white-space:nowrap; display:inline-block; } .v3h .eqt em .num { display:inline; }
        .v3h .eqt em.up { color:var(--gain); } .v3h .eqt em.down { color:var(--loss); }
        .v3h .eqd.up { border-color:var(--gain); background:var(--gain); } .v3h .eqd.down { border-color:var(--loss); background:var(--loss); }
        .v3h .eqv { position:absolute; right:0; transform:translateY(-150%); direction:ltr; font-size:14px; white-space:nowrap; background:var(--v3-bg); padding:0 4px; border-radius:3px; z-index:1; pointer-events:none; }
        .v3h .eqv.below { transform:translateY(60%); }
        .v3h .eqv.up { color:var(--gain); } .v3h .eqv.down { color:var(--loss); }
        .v3h .eqx { padding-top:8px; padding-inline-start:0; direction:ltr; }
        .v3h .eqxl { position:relative; height:16px; margin-left:69px; margin-right:5px; font-size:12px; color:var(--dim); }
        .v3h .eqxl span { position:absolute; transform:translateX(-50%); white-space:nowrap; }
        .v3h .head .hs { font-size:16px; direction:ltr; } .v3h .head .hs.up { color:var(--gain); } .v3h .head .hs.down { color:var(--loss); }
        .v3h table.jr, .v3h table.tb { border:0 !important; }
        .v3h .jr th, .v3h .jr td, .v3h .tb th, .v3h .tb td { border-top:0 !important; border-inline:0 !important; }  /* קווים אופקיים בלבד (ברירת המחדל של markdown מציירת רשת מלאה) */
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
            .v3h .jr .c-entry, .v3h .jr .c-exit, .v3h .jr .c-res, .v3h .jr .c-net, .v3h .jr .c-ccy { display:none; }  /* בנייד: רווח/הפסד (ברוטו) במקום נטו */
            .v3h .jr .amt { font-weight:500; }
            .v3h table.jr { min-width:0; table-layout:auto; } .v3h .jr col { width:auto !important; }
            .v3h .jr td, .v3h .jr th { padding-inline:6px; } .v3h .jr td:first-child { white-space:normal; }
        }
"""


# ───────────────────────── ביצועי אסטרטגיה ─────────────────────────

def perf_filter_summary(parts: list[str], is_open: bool) -> str:
    inner = "".join(f'<span class="fp">{esc(p)}</span>' for p in parts)
    return (
        f'<div class="fl{" open" if is_open else ""}"><span class="fsum">{inner}</span></div>'
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
        f'<span class="chg">{_CHEV}</span></summary><div class="in">{body_html}</div></details>'
    )


def titled_section(title: str, side_html: str, body_html: str) -> str:
    return f'<section class="sec"><div class="sech">{esc(title)}{side_html}</div>{body_html}</section>'


PERF_CSS = """
        .v3h .kpi.k6 { grid-template-columns:repeat(6,minmax(0,1fr)); margin-top:28px; border-top:1px solid var(--rule); }
        .v3h .kpi.k6 > div { padding:18px 18px 20px; }
        .v3h .kpi.k6 > div:first-child { padding-inline-start:0; border-inline-start:0; }
        @media (max-width:480px) {
            .v3h .kpi.k6 { grid-template-columns:repeat(2,minmax(0,1fr)); margin-top:20px; }
            .v3h .kpi.k6 > div { padding:12px 12px 14px; border-top:1px solid var(--rule); border-inline-start:1px solid var(--rule); }
            .v3h .kpi.k6 > div:nth-child(-n+2) { border-top:0; }
            .v3h .kpi.k6 > div:nth-child(odd) { border-inline-start:0; padding-inline-start:0; }
            .v3h .kpi.k6 > div:first-child { grid-column:auto; }
            .v3h .kpi.k6 small { font-size:12px; }
            .v3h .kpi.k6 strong { font-size:22px; }
        }
        .v3h .kpi.k6 strong { font-size:clamp(20px,2.4vw,26px); }
        .v3h .pbar { display:flex; gap:2px; height:4px; margin-top:-1px; }
        .v3h .pbar i { display:block; height:100%; }
        .v3h .pbar .g { background:var(--gain); } .v3h .pbar .l { background:var(--loss); } .v3h .pbar .n { background:var(--dim); opacity:.5; } .v3h .pbar .p { background:var(--rule); }
        .v3h .fl { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px 10px; border-bottom:1px solid var(--rule); cursor:default; }
        .v3h .fsum { display:flex; flex-wrap:wrap; align-items:center; row-gap:6px; font-size:16px; color:var(--v3-soft); }
        .v3h .fp { display:inline-block; }
        @media (max-width:480px) {
            .v3h .fsum { gap:4px 16px; font-size:15px; }
            .v3h .fsum .fp + .fp { margin-inline-start:0; padding-inline-start:0; border-inline-start:0; }
        }
        .v3h .fp + .fp { margin-inline-start:18px; padding-inline-start:18px; border-inline-start:1px solid var(--dim); line-height:1.1; }
        .v3h .chg { display:inline-flex; align-items:center; gap:8px; font-size:14px; color:var(--dim); }
        .v3h .chg svg { transform:scaleX(-1); transition:transform .15s; }
        .v3h .fl.open .chg svg { transform:scaleX(-1) rotate(90deg); }
        .v3h .tb td.r { font-weight:500; }
        .v3h .rate { display:inline-flex; align-items:center; gap:12px; }
        .v3h .rate .num { min-width:42px; text-align:right; }
        .v3h .rb { position:relative; display:inline-block; width:96px; height:5px; background:var(--rule); direction:ltr; }
        .v3h .rb i { display:block; height:100%; background:var(--gain); }
        .v3h .rb::after { content:''; position:absolute; left:50%; top:-3px; width:1px; height:10px; background:var(--dim); }
        .v3h .down .rb i { background:var(--loss); }
        @media (max-width:480px) {
            .v3h .rb { width:44px; flex:none; }
            .v3h .rate { gap:8px; }
            .v3h .tb th, .v3h .tb td { padding-inline:5px; }
            .v3h .tb td { font-size:15px; }
            .v3h .tb td.main { white-space:normal; min-width:66px; }
            .v3h .tb th { white-space:normal; font-size:12px; line-height:1.25; vertical-align:bottom; }
            .v3h .tb .rb { width:36px; }
        }
        .v3h .sec { margin-top:60px; }
        .v3h .sec .sech { margin:0; font-weight:500; font-size:18px; padding-bottom:12px; border-bottom:1px solid var(--rule-strong); display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:6px 24px; }
        .v3h .sec .sech .hsub { display:inline-flex; flex-wrap:wrap; align-items:center; row-gap:4px; font-size:14px; font-weight:400; color:var(--dim); }
        .v3h .sec .sech .hsub .fp + .fp { margin-inline-start:14px; padding-inline-start:14px; }
        .v3h .two { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:0 56px; }
        .v3h details.more { border-bottom:1px solid var(--rule); }
        .v3h details.more > summary { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:18px 10px; cursor:pointer; list-style:none; }
        .v3h details.more > summary::-webkit-details-marker { display:none; }
        .v3h details.more[open] .chg svg { transform:scaleX(-1) rotate(90deg); }
        .v3h .mt { display:flex; flex-direction:column; gap:2px; }
        .v3h .mt b { font-weight:400; font-size:17px; color:var(--v3-soft); }
        .v3h .ms { display:flex; flex-wrap:wrap; align-items:center; row-gap:4px; font-size:13.5px; color:var(--dim); }
        .v3h .ms .fp + .fp { margin-inline-start:12px; padding-inline-start:12px; }
        @media (max-width:480px) {
            .v3h .ms { display:flex; flex-wrap:wrap; gap:2px 14px; }
            .v3h .ms .fp + .fp, .v3h .sec .sech .hsub .fp + .fp { margin-inline-start:0; padding-inline-start:0; border-inline-start:0; }
            .v3h .sec .sech .hsub { column-gap:14px; }
        }
        .v3h details.more .in { padding:0 0 24px; }
        .v3h .stack { margin-top:60px; border-top:1px solid var(--rule-strong); }
        @media (max-width:820px) { .v3h .two { grid-template-columns:minmax(0,1fr); } .v3h .two > * { min-width:0; } }
        @media (max-width:720px) { .v3h .kpi.k6 { grid-template-columns:repeat(2,minmax(0,1fr)); } .v3h .kpi.k6 > div:nth-child(odd) { padding-inline-start:0; border-inline-start:0; } .v3h .kpi.k6 > div:nth-child(n+3) { border-top:1px solid var(--rule); } }
"""


HOURS_IFRAME_TEMPLATE = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root { --ink:#24211D; --dim:#6F6A62; --rule:#DAD5CC; --gain:#2F6B4F; --strong:#24211D; }
:root[data-theme="dark"] { --ink:#ECE8E0; --dim:#9A948A; --rule:#34302A; --gain:#7DBF9C; --strong:#5A554C; }
html, body { margin:0; background:transparent; color:var(--ink); font-family:'Heebo',system-ui,sans-serif; direction:rtl; font-variant-numeric:tabular-nums; }
.head { padding-bottom:12px; border-bottom:1px solid var(--strong); font-weight:500; font-size:18px; line-height:1.5; }
#rows { display:grid; grid-template-columns:1fr 1fr; column-gap:64px; }
@media (max-width:560px) { #rows { grid-template-columns:1fr; } }
.li { display:flex; justify-content:space-between; align-items:center; gap:16px; padding-block:15px; border-bottom:1px solid var(--rule); }
.nmc { display:flex; flex-direction:column; gap:2px; }
.nmc .n { font-size:16px; }
.stt { font-size:13px; color:var(--dim); }
.stt.up { color:var(--gain); }
.cd { display:flex; flex-direction:column; align-items:flex-start; gap:6px; }
.cd .lbl { font-size:13px; color:var(--dim); margin-inline-start:4px; }  /* הקצה הימני של התווית באותו קו עם ה-ש של "שניות" */
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
