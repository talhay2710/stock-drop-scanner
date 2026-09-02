"""דשבורד צפייה חיה בהתראות - הרצה: streamlit run dashboard.py"""
import datetime as dt
import html
import json
import os
import re
import sys
import sqlite3
import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml
from PIL import Image, ImageDraw, ImageFont
from bidi.algorithm import get_display

def _find_bold_font_path() -> str | None:
    # נתיב Windows קבוע נשבר על Linux (Streamlit Cloud/GitHub Actions) - מנסים
    # כמה מועמדים בסדר עדיפות, ונופלים חזרה לפונט ברירת המחדל של Pillow אם
    # אף אחד לא נמצא (לא יתמוך בעברית כמו שצריך, אבל לא יקריס את האפליקציה).
    _candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "font_bold.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf",
    ]
    for _c in _candidates:
        if os.path.exists(_c):
            return _c
    return None


_FONT_PATH = _find_bold_font_path()


def _load_bold_font(font_size: int):
    if not _FONT_PATH:
        return ImageFont.load_default(font_size)
    font = ImageFont.truetype(_FONT_PATH, font_size)
    # assets/font_bold.ttf הוא גופן variable (Noto Sans Hebrew) בלי קובץ Bold
    # נפרד - צריך לבחור את ה-named instance "Bold" בפירוש, אחרת מתקבל המשקל
    # הרגיל (Regular) כברירת מחדל. arialbd.ttf המקומי כבר Bold מטבעו, אין לו
    # variations בכלל - ה-try/except מדלג עליו בשקט.
    try:
        font.set_variation_by_name("Bold")
    except Exception:
        pass
    return font


def render_text_image(text: str, color_hex: str, font_size: int = 26) -> Image.Image:
    """מצייר טקסט (עם נקודה צבעונית מימין) כתמונה בפועל, כדי לעקוף לחלוטין כל
    בעיית גופן/דפדפן אצל הלקוח - הפיקסלים קבועים מראש ולא תלויים ברינדור טקסט.
    Pillow הבסיסי (בלי raqm) לא מהפך RTL בעצמו - משתמשים ב-python-bidi כדי
    להמיר לסדר התצוגה הנכון (visual order) לפני הציור, אחרת המילה מצטיירת הפוך."""
    text = get_display(text)
    font = _load_bold_font(font_size)
    dummy = Image.new("RGBA", (10, 10))
    dd = ImageDraw.Draw(dummy)
    bbox = dd.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    dot_r = font_size // 4
    pad = 8
    width = text_w + dot_r * 2 + pad * 3
    height = max(text_h + 14, dot_r * 2 + 10)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = tuple(int(color_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    dot_cx, dot_cy = width - pad - dot_r, height // 2
    d.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=color)
    text_x = dot_cx - dot_r - pad - text_w - bbox[0]
    text_y = (height - text_h) // 2 - bbox[1]
    d.text((text_x, text_y), text, font=font, fill=color)
    return img

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config, db_path, CONFIG_PATH
from src.scanner import run_scan, STOP_LOSS_FACTOR, STOP_WARN_PCT, TARGET_WARN_PCT, compute_holdings_value_by_currency
from src.strategy import ATR_STOP_MULTIPLIER, live_target_price
from src import market_data, constituents, news, backtest, store, analysis, fees, cloud_sync, notifier
from src.market_hours import MARKET_HOURS, get_market_status, format_countdown, is_market_open, israel_today, israel_now

st.set_page_config(page_title="סורק מניות", layout="wide")

components.html(
    """
    <script>
      var doc = window.parent.document;
      doc.documentElement.setAttribute('translate', 'no');
      doc.documentElement.classList.add('notranslate');
    </script>
    """,
    height=0,
)

POS_COLOR = "#06806B"
NEG_COLOR = "#CC2F3C"
POS_BG = "rgba(6, 128, 107, 0.10)"
NEG_BG = "rgba(204, 47, 60, 0.10)"
NEUTRAL_COLOR = "#3B4A5A"
NEUTRAL_BG = "rgba(120,120,120,0.07)"
ACCENT_COLOR = "#3B6EA5"
CURRENCY_SYMBOLS = {"ILS": 'ש"ח', "USD": "$"}

# אייקון עיגול-שאלה שמחקה את ה-help= הטבעי של Streamlit (עיגול אפור עדין) -
# SVG במקום אימוג'י "❓", שמציג צבעוני/שונה מאוד בין פלטפורמות.
_HELP_ICON_SVG = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"></circle>'
    '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
)


def _help_icon_span(tooltip_text: str) -> str:
    """<span> עם האייקון + טולטיפ - onclick (לא רק title) כי הובר לבד לא עובד
    במגע (טאבלט/מובייל)."""
    _tip_js = tooltip_text.replace("'", "\\'")
    return (
        f'<span title="{tooltip_text}" onclick="alert(\'{_tip_js}\')" '
        f'style="cursor:help; color:rgba(49,51,63,0.6);">{_HELP_ICON_SVG}</span>'
    )


def _signed_num(value: float, decimals: int = 0, suffix: str = "") -> str:
    """מספר עם סימן (+/-) שנשאר לפני המספר גם בתוך טקסט עברי (RTL) - עוטף
    ב-LRM (סימן כיווניות שקוף) כדי למנוע היפוך ויזואלי של הסימן ע"י מנועי טקסט."""
    return f"‎{value:+,.{decimals}f}{suffix}"


def _price_text(value, index_name) -> str:
    """שער (לא סכום כסף כולל) לפי מדד - ת"א נסחר באגורות (ולא בש"ח עשרוני),
    בדיוק כמו שכבר נהוג בכל שאר האתר (למשל _format_price ב-scanner.py, וכרטיס
    האחזקה בטאב "אחזקות") - כדי שאפשר יהיה להשוות ישירות למסך הברוקר. משותף בין
    כל מקום בדשבורד שמציג שער בודד של מניה, כדי לא לשכפל את הבדיקה שוב ושוב."""
    if pd.isna(value):
        return "—"
    ccy = constituents.INDEX_CURRENCY.get(index_name, "ILS")
    if ccy == "ILS":
        return f"{value*100:,.0f}"
    return f"${value:,.2f}"


def _stat_card(label: str, value: str, color: str, bg: str) -> str:
    return (
        f'<div style="flex:1; min-width:120px; border:1px solid {color}33; border-radius:12px; '
        f'padding:12px 14px; background:{bg}; text-align:center; box-shadow:0 2px 6px rgba(0,0,0,0.05);">'
        f'<div style="font-size:0.8rem; font-weight:600; opacity:0.75;">{label}</div>'
        f'<div style="font-size:1.35rem; font-weight:700; color:{color}; margin-top:4px;">{value}</div>'
        f'</div>'
    )

REASON_COLORS = {
    "market_wide": "#4A90D9",
    "sector_pressure": "#9B59B6",
    "earnings_reaction": "#E67E22",
    "profit_taking": "#16A085",
    "stock_specific_news": "#7F8C8D",
    "ex_dividend": "#B8860B",
    "unclear": "#95A5A6",
}


def render_reason_pill(reasons_json: str) -> str:
    """תגית (pill) צבעונית לסיבת הירידה העיקרית, לזיהוי מהיר בטבלה/הרחבה."""
    tag = backtest.primary_reason_tag(reasons_json)
    color = REASON_COLORS.get(tag, "#95A5A6")
    label = analysis.REASON_LABELS.get(tag, tag)
    return (
        f'<span style="background:{color}22; color:{color}; border:1px solid {color}66; '
        f'border-radius:12px; padding:2px 10px; font-size:0.85em; font-weight:600;">{label}</span>'
    )


def _sparkline_svg(prices: list, width: int = 140, height: int = 36) -> str:
    """גרף זעיר (sparkline) כ-SVG מוטבע - מציג את מגמת המחיר האחרונה בלי צירים/legend."""
    if len(prices) < 2:
        return ""
    lo, hi = min(prices), max(prices)
    rng = (hi - lo) or 1
    step = width / (len(prices) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - ((p - lo) / rng) * (height - 4) - 2:.1f}"
        for i, p in enumerate(prices)
    )
    color = POS_COLOR if prices[-1] >= prices[0] else NEG_COLOR
    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


@st.cache_data(ttl=60)
def get_current_price(ticker: str) -> float | None:
    """מחיר עדכני אמיתי לטיקר בודד (regularMarketPrice) - בשימוש לאחזקות בפועל,
    כי ל-fetch_universe_daily_changes (הורדה בבת אחת להרבה טיקרים) יש לפעמים
    פער/עיכוב בנתון היומי, ואצל אחזקות שלך זה קריטי (בשונה מרשימת "מניות מובילות")."""
    return market_data.fetch_current_price(ticker)


@st.cache_data(ttl=60)
def get_current_changes_for(tickers: tuple[str, ...]) -> pd.DataFrame:
    """שינוי יומי נוכחי (סגירה אחרונה מול קודמת) לרשימת טיקרים ספציפית - לעמודת
    'שינוי נוכחי' בטבלת ההתראות, כדי שתתעדכן בכל סריקה (ttl=60 תואם ל-run_every
    של הפרגמנט) בלי תלות במדד שלם כמו get_all_changes."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "pct_change"])
    return market_data.fetch_universe_daily_changes(list(tickers))


@st.cache_data(ttl=300)
def get_holding_stop_price(ticker: str, entry_price: float) -> float:
    """קו סטופ-לוס לפי ATR (תנודתיות אמיתית של המניה) - נקרא פעם אחת בזמן
    הקנייה (או בפעם הראשונה שרואים אחזקה בלי קו סטופ שמור) ומאז נשאר קבוע,
    בדיוק כמו סטופ אמיתי אצל ברוקר. נופל חזרה ל-3% קבוע אם אין מספיק היסטוריה."""
    df = market_data.fetch_universe_daily_changes([ticker])
    if not df.empty:
        row = df.iloc[0]
        atr = market_data.compute_atr(row.get("highs"), row.get("lows_series"), row["history"])
        if atr is not None and atr > 0:
            return round(entry_price - ATR_STOP_MULTIPLIER * atr, 2)
    return round(entry_price * STOP_LOSS_FACTOR, 2)


def get_or_backfill_stop_price(holding_row: dict, entry_price: float) -> float:
    """קו הסטופ השמור לאחזקה - ואם אין (אחזקה שנקנתה לפני שהמנגנון הזה נוסף),
    מחשב פעם אחת עכשיו ושומר, כדי שמאותו רגע הוא יהיה קבוע גם היא, בלי צורך
    לחשב מחדש בכל טעינה."""
    stored = holding_row.get("holding_stop_price")
    if stored:
        return stored
    computed = get_holding_stop_price(holding_row["ticker"], entry_price)
    bf_conn = store.get_conn(db_path(cfg))
    store.update_holding_stop_price(bf_conn, int(holding_row["id"]), computed)
    bf_conn.close()
    return computed


@st.cache_data(ttl=300)
def get_sparkline_series(ticker: str, days: int = 15):
    df = market_data.fetch_universe_daily_changes([ticker])
    if df.empty:
        return pd.Series(dtype=float)
    hist = df.iloc[0]["history"]
    return hist.dropna().tail(days)


def get_sparkline_prices(ticker: str, days: int = 15) -> list:
    return get_sparkline_series(ticker, days).tolist()

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
    .main, .block-container, [data-testid="stMarkdownContainer"], p, span, div, li, label {
        font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
    }
    /* סרגל הכלים המובנה של Streamlit (הרחבה/העתקה/הורדה/הצגה כטבלה) שמופיע
       בהובר בפינת כל גרף - לא רלוונטי למשתמש הסופי, מוסתר בכל הגרפים באתר.
       הטולבר (data-testid="stElementToolbar") הוא אח (sibling) של הגרף בתוך
       stElementContainer המשותף, לא צאצא שלו - לכן צריך :has() כדי להגביל
       את ההסתרה רק ל-container שיש בו בפועל גרף Vega, לא לכל טולבר באתר
       (כמו טבלאות/תמונות, ששם ייתכן שהטולבר עדיין שימושי). */
    [data-testid="stElementContainer"]:has([data-testid="stVegaLiteChart"]) [data-testid="stElementToolbar"] {
        display: none !important;
    }
    [data-testid="stSidebar"] {
        width: 300px;
    }
    [data-testid="stSidebarHeader"] {
        height: 8px;
        min-height: 0px;
    }
    div[class*="st-key-nav_tabs_row"] {
        border: 1px solid rgba(128,128,128,0.3);
        border-radius: 12px;
        padding: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }
    div[class*="st-key-navtab_"] button {
        font-size: 1.25rem;
        padding: 16px 22px;
        border-radius: 8px;
        border: none;
        box-shadow: none;
    }
    div[class*="st-key-navtab_"] button[kind="primary"] {
        background-color: rgba(59, 110, 165, 0.12);
        color: #3B6EA5;
        font-weight: 700;
    }
    div[class*="st-key-navtab_"] button[kind="primary"]:hover {
        background-color: rgba(59, 110, 165, 0.2);
        color: #3B6EA5;
    }
    div[class*="st-key-navtab_"] button[kind="secondary"] {
        background-color: transparent;
        font-weight: 500;
    }
    [data-testid="stMainBlockContainer"] {
        padding-top: 2rem;
    }
    div[class*="st-key-market_panel"] {
        padding: 8px 16px !important;
        gap: 10px !important;
    }
    div[class*="st-key-news_header_wrap"] {
        padding: 0 16px !important;
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.8rem !important;
    }
    h1, h2, h3 { font-weight: 600 !important; letter-spacing: -0.01em; }
    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
    .main, .block-container, [data-testid="stMarkdownContainer"],
    [data-testid="stMetric"], [data-testid="stDataFrame"], table, th, td,
    div[data-baseweb="select"], div[data-baseweb="tab-list"] {
        direction: rtl;
    }
    /* Vega-Lite (st.altair_chart) בונה טקסט/מיקומים בהנחת LTR פנימית - כשה-
    direction:rtl מהעמוד "מדלוף" לתוך ה-SVG, טקסטים ב-legend מתנגשים עם
    האייקון הצבעוני שלהם וצירים נחתכים בקצוות. מבודדים לגמרי ל-LTR, בדיוק
    כמו שגרפים נשארים LTR גם באתרים עבריים אחרים - זה תקן, לא באג. */
    [data-testid="stVegaLiteChart"], [data-testid="stVegaLiteChart"] * {
        direction: ltr !important;
    }
    /* אותה בעיה בדיוק בשדות number_input - direction:rtl מהעמוד גורם למינוס
    של מספר שלילי (למשל "-1.5") להיצמד לצד הלא-נכון. מספרים הם תוכן LTR
    מטבעם - מבודדים ל-LTR, עם text-align:right כדי שעדיין יישבו צמוד לימין
    התיבה (עקבי עם שאר העמוד). */
    input[type="number"] {
        direction: ltr !important;
        text-align: right !important;
    }
    .block-container, [data-testid="stSidebar"] .block-container,
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] *,
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
    h1, h2, h3, h4, h5, h6, p, span, li, label,
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
        text-align: right !important;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
        justify-content: flex-end !important;
    }
    [data-testid="stHorizontalBlock"] {
        direction: rtl;
    }
    [data-testid="stWidgetLabel"] {
        text-align: right !important;
        justify-content: flex-start !important;
        width: 100%;
    }
    /* בתפריטי בחירה (למשל בחירת מדד), כל אפשרות תיושר אוטומטית לפי השפה שלה -
       אנגלית (S&P 500 / NASDAQ) תוצג משמאל לימין, עברית (ת"א 35/125) מימין לשמאל */
    div[data-baseweb="select"] *, [role="option"], [role="listbox"] * {
        unicode-bidi: plaintext;
    }
    [data-testid="stSidebar"] button[kind="primary"] {
        background-color: transparent; color: inherit;
        border: 1px solid rgba(128,128,128,0.3); border-radius: 12px;
        font-weight: 600; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        justify-content: flex-end; padding-right: 0px;
    }
    [data-testid="stSidebar"] button[kind="primary"] p {
        margin-right: -74px;
    }
    div[class*="st-key-pre_tabs_divider"] hr {
        margin: 0 !important;
    }
    [data-testid="stSidebar"] button[kind="primary"]:hover {
        background-color: rgba(128,128,128,0.08); color: inherit;
        border: 1px solid rgba(128,128,128,0.4);
    }
    [data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] > span > span {
        background-color: rgba(59, 110, 165, 0.15) !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] span {
        color: #3B6EA5 !important;
    }
    [data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] svg {
        fill: #3B6EA5 !important;
    }
    /* Streamlit's slider (react-aria, לא BaseWeb - הסלקטורים הישנים לא תפסו
       כלום, ר' commit): הטרק ממוקם ב-left:X% שכן מתחשב ב-RTL (מתהפך ל-100-X%
       עבור ערכים נמוכים), אבל ה-gradient שצובע את החלק "מלא" תמיד מצייר
       "to right" מקצה שמאל פיזי - לא מתהפך. בלי scaleX(-1) הצבע והנקודה
       (שמייצגים בדיוק אותו ערך) מופיעים בקצוות מנוגדים של הציר, לא נפגשים
       בכלל. אומת בדפדפן: 112px→542px (צבע) מול 1062px (נקודה) בלי התיקון,
       112px→1068px (צבע) מול 1062px (נקודה) איתו - כמעט מדויק.
       שתי רמות [data-orientation="horizontal"] כי גם המעטפת החיצונית וגם
       הפנימית נושאות את אותו attribute - הפנימית היא הרלוונטית. */
    [data-testid="stSlider"] div[data-orientation="horizontal"] div[data-orientation="horizontal"] > div:first-child {
        transform: scaleX(-1) !important;
    }
    [data-testid="stSliderTickBarMax"], [data-testid="stSliderTickBarMin"] {
        color: #3B6EA5 !important;
    }
    /* אייקון ה-help= הטבעי של Streamlit הוא בעצם <button>, שמקבל cursor:pointer
       כברירת מחדל של הדפדפן - לא cursor:help כמו שהיה מצופה מסימן שאלה. */
    [data-testid="stTooltipHoverTarget"] button {
        cursor: help !important;
    }
    div[class*="st-key-backtest_rerun_btn"] button {
        background-color: rgba(59, 110, 165, 0.10); color: #3B6EA5;
        border: 1px solid rgba(59, 110, 165, 0.4); border-radius: 8px; font-weight: 500;
    }
    div[class*="st-key-backtest_rerun_btn"] button:hover {
        background-color: rgba(59, 110, 165, 0.18); color: #3B6EA5;
        border: 1px solid rgba(59, 110, 165, 0.5);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📉 סורק מניות - התראות ואסטרטגיית ריבאונד")
st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

_TAB_DEFS = [
    ("movers", "🔝 מניות מובילות"),
    ("today", "🔔 התראות"),
    ("portfolio", "💰 אחזקות"),
    ("history", "📋 יומן עסקאות"),
    ("backtest", "📈 ביצועי אסטרטגיה"),
]
if "active_tab" not in st.session_state:
    st.session_state.active_tab = None

with st.container(key="nav_tabs_row"):
    _nav_cols = st.columns(len(_TAB_DEFS), gap="small")
    for _nav_col, (_nav_key, _nav_label) in zip(_nav_cols, _TAB_DEFS):
        with _nav_col:
            if st.button(
                _nav_label, key=f"navtab_{_nav_key}", use_container_width=True,
                type="primary" if st.session_state.active_tab == _nav_key else "secondary",
            ):
                st.session_state.active_tab = None if st.session_state.active_tab == _nav_key else _nav_key
                st.rerun()


st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# ב-Streamlit Cloud הסודות מוזנים דרך st.secrets (secrets.toml, לא קובץ ב-git) -
# מעתיקים אותם למשתני סביבה כאן כדי ש-load_config() (המשותף גם לסקריפטים
# העצמאיים כמו run_scan_once.py, בלי תלות ב-streamlit) יראה אותם באופן אחיד.
# מקומית אין secrets.toml, אז זה פשוט לא עושה כלום.
try:
    for _secret_key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if _secret_key in st.secrets:
            os.environ.setdefault(_secret_key, st.secrets[_secret_key])
except Exception:
    pass

cfg = load_config()


def _sync_and_warn(reason: str, include_db: bool = False) -> None:
    """עוטף cloud_sync.sync_to_cloud. בלי הודעה למשתמש על כישלון - ברוב המקרים
    זה סתם התנגשות חולפת עם דחיפת הבוט שמתאזנת לבד בניסיון החוזר הפנימי, וגם
    כשלא, השינוי המקומי לא הולך לאיבוד (ידחף עם הסנכרון הבא). כישלון אמיתי
    עדיין מתועד ב-log לצורך אבחון (ר' cloud_sync.sync_to_cloud)."""
    cloud_sync.sync_to_cloud(reason, include_db=include_db)


def _check_il_constituents_staleness(max_age_days: int = 90) -> list[str]:
    """בודק מתי לאחרונה עודכנו/אומתו קובצי רשימת המניות של ת"א מול תאריך בהערת
    הכותרת של הקובץ - כדי להזכיר לעדכן מול אתר הבורסה מדי רבעון (הרכב המדד משתנה)."""
    warnings = []
    for filename, label in (("ta35_constituents.csv", 'ת"א 35'), ("ta125_constituents.csv", 'ת"א 125')):
        path = os.path.join(constituents.DATA_DIR, filename)
        try:
            with open(path, encoding="utf-8") as f:
                first_lines = "".join(f.readline() for _ in range(3))
            match = re.search(r"(\d{4}-\d{2}-\d{2})", first_lines)
            if not match:
                continue
            verified_date = dt.date.fromisoformat(match.group(1))
            age_days = (dt.date.today() - verified_date).days
            if age_days > max_age_days:
                warnings.append(f"רשימת המניות של {label} אומתה לאחרונה לפני {age_days} ימים - כדאי לעדכן מול אתר הבורסה")
        except Exception:
            continue
    return warnings


for staleness_warning in _check_il_constituents_staleness():
    st.warning(f"📋 {staleness_warning}", icon="⚠️")


def _theme_type() -> str:
    """'dark' או 'light' - לכיול צבעים שנקבעים מראש (כמו תמונות PIL) לפי המצב
    הנוכחי, כי CSS media-query לא יכול להשפיע על פיקסלים מוכנים מראש."""
    try:
        return st.context.theme.type
    except Exception:
        return "light"


THEME = _theme_type()
NEAR_MISS_COLOR = "#F5C242" if THEME == "dark" else "#B8860B"


@st.cache_data(ttl=15)
def load_alerts(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    conn = store.get_conn(path)
    df = pd.read_sql_query("SELECT * FROM alerts ORDER BY scan_ts DESC", conn)
    conn.close()
    return df


df = load_alerts(db_path(cfg))

ALL_INDICES = ["SP500", "NASDAQ100", "TA35", "TA125"]
INDEX_LABELS = {"SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "TA35": 'ת"א 35', "TA125": 'ת"א 125'}


@st.cache_data(ttl=60)
def get_index_changes() -> dict:
    return {idx: market_data.fetch_index_proxy_change(idx) for idx in ALL_INDICES}


def _status_dot(color: str) -> str:
    return (f'<span style="display:inline-block; width:8px; height:8px; border-radius:50%; '
            f'background:{color}; margin-left:5px; vertical-align:middle;"></span>')


CLOSED_COLOR = "#888"
CLOSED_BG = "rgba(136,136,136,0.08)"


def render_index_card(label: str, val: float | None, trading_open: bool) -> None:
    if val is None:
        color, bg, value_html = CLOSED_COLOR, CLOSED_BG, "אין נתונים"
    elif not trading_open:
        color, bg = CLOSED_COLOR, CLOSED_BG
        arrow = "▲" if val >= 0 else "▼"
        value_html = f"{arrow} {_signed_num(val, 1, '%')}"
    else:
        color = POS_COLOR if val >= 0 else NEG_COLOR
        bg = POS_BG if val >= 0 else NEG_BG
        arrow = "▲" if val >= 0 else "▼"
        value_html = f"{arrow} {_signed_num(val, 1, '%')}"

    status_color = POS_COLOR if trading_open else CLOSED_COLOR
    status_text = "מסחר פע‌יל" if trading_open else "מסחר סגור"

    st.markdown(
        f"""
        <div style="border:1px solid {color}; border-radius:12px; padding:14px 16px; height:125px; overflow:hidden; display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;
                    background:{bg}; text-align:center; box-shadow:0 2px 6px rgba(0,0,0,0.06);
                    transition:box-shadow 0.2s;">
          <div style="font-size:0.9rem; font-weight:600; opacity:0.8;">{label}</div>
          <div style="font-size:1.6rem; font-weight:700; color:{color}; margin-top:4px;">{value_html}</div>
          <div style="font-size:0.85rem; letter-spacing:0.02em; opacity:0.8; margin-top:6px; line-height:17px;">
            {_status_dot(status_color)}{status_text}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_portfolio_card(label: str, pnl: float, pnl_pct: float, ccy_symbol: str, dynamic_icon: bool = False) -> None:
    color = POS_COLOR if pnl >= 0 else NEG_COLOR
    bg = POS_BG if pnl >= 0 else NEG_BG
    arrow = "▲" if pnl >= 0 else "▼"
    value_html = f"{arrow} {_signed_num(pnl_pct, 1, '%')}"
    if dynamic_icon:
        label = f"{'📈' if pnl >= 0 else '📉'} {label}"

    st.markdown(
        f"""
        <div style="border:1px solid {color}; border-radius:12px; padding:14px 16px; height:125px; overflow:hidden; display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;
                    background:{bg}; text-align:center; box-shadow:0 2px 6px rgba(0,0,0,0.06);
                    transition:box-shadow 0.2s;">
          <div style="font-size:0.9rem; font-weight:600; opacity:0.8;">{label}</div>
          <div style="font-size:1.6rem; font-weight:700; color:{color}; margin-top:4px;">{value_html}</div>
          <div style="font-size:0.85rem; letter-spacing:0.02em; opacity:0.8; margin-top:6px;">
            {_signed_num(pnl)} {ccy_symbol}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_value_card(label: str, value: float, invested: float, ccy_symbol: str, holdings_count: int) -> None:
    # ירוק אם השווי הנוכחי כיסה/עבר את סך ההשקעה (רווח כולל או לפחות איזון),
    # אדום אם עדיין מתחת לסכום שהושקע - בניגוד ל"שינוי כללי" זה לא באחוזים
    # אלא שאלה בינארית של "האם אני בפלוס על הכסף שהכנסתי בפועל".
    color = POS_COLOR if value >= invested else NEG_COLOR
    bg = POS_BG if value >= invested else NEG_BG
    st.markdown(
        f"""
        <div style="border:1px solid {color}; border-radius:12px; padding:14px 16px; height:125px; overflow:hidden; display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;
                    background:{bg}; text-align:center; box-shadow:0 2px 6px rgba(0,0,0,0.06);
                    transition:box-shadow 0.2s;">
          <div style="font-size:0.9rem; font-weight:600; opacity:0.8;">{label}</div>
          <div style="font-size:1.6rem; font-weight:700; margin-top:4px; color:{color};">{value:,.0f} {ccy_symbol}</div>
          <div style="font-size:0.85rem; letter-spacing:0.02em; opacity:0.8; margin-top:6px;">
            {holdings_count} אחזקות
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_proximity_card(name: str, gap_pct: float, is_target: bool) -> None:
    # מציג את האחזקה הכי קרובה לחצות את היעד שלה (רווח) או את הסטופ שלה (הפסד),
    # מכל האחזקות בתיק - כדי לתת "איתות" בלי צורך לבדוק כל אחזקה בנפרד.
    color = POS_COLOR if is_target else NEG_COLOR
    bg = POS_BG if is_target else NEG_BG
    icon = "🎯" if is_target else "🛑"
    # gap_pct שלילי אומר שהמחיר כבר עבר את הרף (יעד או סטופ) - "0.0% נותרו" היה
    # מטעה כאן (משתמע שהיא בדיוק על הרף, לא כבר מעבר לו). מציגים "חצתה ב-X%"
    # במקום, עם ה-X בפועל (לא מקוצץ ל-0), כדי שהכרטיס יישאר מדויק גם במצב הזה.
    if gap_pct < 0:
        label = f"{icon} {'עברה את היעד' if is_target else 'חצתה את הסטופ-לוס'}"
        gap_line = f"חצתה ב-{abs(gap_pct):.1f}%"
    else:
        label = f"{icon} קרוב ל{'יעד' if is_target else 'סטופ'}"
        gap_line = f"{gap_pct:.1f}% נותרו"
    st.markdown(
        f"""
        <div style="border:1px solid {color}; border-radius:12px; padding:14px 16px; height:125px; overflow:hidden; display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;
                    background:{bg}; text-align:center; box-shadow:0 2px 6px rgba(0,0,0,0.06);
                    transition:box-shadow 0.2s;">
          <div style="font-size:0.9rem; font-weight:600; opacity:0.8;">{label}</div>
          <div style="font-size:1.25rem; font-weight:700; color:{color}; margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{name}</div>
          <div style="font-size:0.85rem; letter-spacing:0.02em; opacity:0.8; margin-top:6px;">
            {gap_line}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


DAY_NAMES_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def _day_range_label(weekdays: set) -> str:
    days = sorted(weekdays)
    if not days:
        return ""
    if len(days) == 1:
        return f"יום {DAY_NAMES_HE[days[0] - 1]}"
    return f"{DAY_NAMES_HE[days[0] - 1]}-{DAY_NAMES_HE[days[-1] - 1]}"


def render_market_card(label: str, country: str) -> None:
    status = get_market_status(country)
    now = status["now"]
    spec = MARKET_HOURS[country]
    countdown = format_countdown(status["next_change"], now)
    clock_id = f"clock_{country}"

    if status["open"]:
        color, bg, icon, status_text = POS_COLOR, POS_BG, "🟢", "השוק פתוח"
        sub_text = f"נסגר בעוד {countdown} (בשעה {status['next_change'].strftime('%H:%M')})"
    else:
        color, bg, icon, status_text = CLOSED_COLOR, CLOSED_BG, "⚪", "השוק סגור"
        next_day_name = DAY_NAMES_HE[status["next_change"].isoweekday() - 1]
        sub_text = f"נפתח בעוד {countdown} (יום {next_day_name}, {status['next_change'].strftime('%H:%M')})"

    overrides = spec.get("close_overrides", {})
    main_days = set(spec["weekdays"]) - set(overrides.keys())
    hours_rows = [
        f'<div><b>{_day_range_label(main_days)}</b>&nbsp; '
        f'<span dir="ltr">{spec["open"][0]:02d}:{spec["open"][1]:02d}–{spec["close"][0]:02d}:{spec["close"][1]:02d}</span></div>'
    ]
    for wd, close_hm in overrides.items():
        hours_rows.append(
            f'<div><b>{_day_range_label({wd})}</b>&nbsp; '
            f'<span dir="ltr">{spec["open"][0]:02d}:{spec["open"][1]:02d}–{close_hm[0]:02d}:{close_hm[1]:02d}</span> (מקוצר)</div>'
        )

    components.html(
        f"""
        <html>
        <head>
        <style>
          html, body {{ margin:0; padding:0; background:transparent;
            font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;
            direction: rtl; color:#31333F; }}
          @media (prefers-color-scheme: dark) {{ html, body {{ color:#FAFAFA; }} }}
        </style>
        </head>
        <body>
        <div style="border:1px solid {color}; border-radius:12px; padding:14px 18px; background:{bg};
                    box-sizing:border-box; box-shadow:0 2px 6px rgba(0,0,0,0.06); margin:2px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:1rem; font-weight:600; opacity:0.85;">{label}</div>
            <div id="{clock_id}" style="font-family:'Consolas','Courier New',monospace; font-size:1.3rem;
                        font-weight:700; color:{color}; letter-spacing:0.05em;">--:--:--</div>
          </div>
          <div style="font-size:1.35rem; font-weight:700; color:{color}; margin-top:6px;">{icon} {status_text}</div>
          <div style="font-size:0.92rem; margin-top:6px;">{sub_text}</div>
          <div style="font-size:0.85rem; opacity:0.75; margin-top:8px; display:flex; gap:18px; flex-wrap:wrap;">
            {"".join(hours_rows)}
          </div>
        </div>
        <script>
          function tick() {{
              var el = document.getElementById("{clock_id}");
              if (!el) return;
              var fmt = new Intl.DateTimeFormat('en-GB', {{
                  timeZone: '{spec["tz"]}', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
              }});
              el.textContent = fmt.format(new Date());
          }}
          tick();
          setInterval(tick, 1000);
        </script>
        </body>
        </html>
        """,
        height=175,
    )



def _compute_portfolio_summaries(holdings_df: pd.DataFrame):
    """מחשב את כרטיסי 'התיק שלי' (רווח כולל, שינוי יומי, שווי). מופרד מהרינדור
    ונקרא מבפנים ל-fragment עם run_every, כדי שהמחירים (get_current_price /
    fetch_universe_daily_changes) יישלפו טריים בכל הפעלה עצמאית שלו - לא רק
    פעם אחת בטעינת הדף."""
    portfolio_summary = value_summary = today_summary = None
    if not holdings_df.empty:
        _by_ccy = {}
        for _, _r in holdings_df.iterrows():
            _entry, _qty = _r["actual_entry_price"], _r["actual_qty"]
            if not _entry or not _qty:
                continue
            _current = get_current_price(_r["ticker"])
            if _current is None:
                # שליפה חיה נכשלה (למשל בדקות הראשונות אחרי פתיחת המסחר, לפני
                # ש-Yahoo מפרסם נתון טרי) - נופלים חזרה למחיר האחרון הידוע
                # (sparkline) במקום להשמיט את האחזקה בשקט מהסיכום הכולל.
                _fallback_prices = get_sparkline_prices(_r["ticker"])
                _current = _fallback_prices[-1] if _fallback_prices else None
            if _current is None:
                continue
            _ccy = constituents.INDEX_CURRENCY.get(_r.get("index_name"), "ILS")
            _agg = _by_ccy.setdefault(_ccy, {"invested": 0.0, "pnl": 0.0})
            _agg["invested"] += _entry * _qty
            _agg["pnl"] += (_current - _entry) * _qty
        if _by_ccy:
            # אם יש אחזקות במספר מטבעות, מציגים רק את המטבע הדומיננטי (הכי הרבה מושקע
            # בו) - כי אי אפשר לחבר ש"ח ודולר לכרטיס אחד בעל משמעות.
            _dominant_ccy = max(_by_ccy, key=lambda c: _by_ccy[c]["invested"])
            _dom_agg = _by_ccy[_dominant_ccy]
            _dom_pct = (_dom_agg["pnl"] / _dom_agg["invested"] * 100) if _dom_agg["invested"] else 0.0
            portfolio_summary = (
                "שינוי כללי", _dom_agg["pnl"], _dom_pct,
                CURRENCY_SYMBOLS.get(_dominant_ccy, _dominant_ccy),
            )
            _total_value = _dom_agg["invested"] + _dom_agg["pnl"]
            value_summary = (
                "🪙 שווי תיק", _total_value, _dom_agg["invested"],
                CURRENCY_SYMBOLS.get(_dominant_ccy, _dominant_ccy), len(holdings_df),
            )

    if not holdings_df.empty:
        _daily_df = market_data.fetch_universe_daily_changes(holdings_df["ticker"].tolist())
        _today_by_ccy = {}
        # fetch_universe_daily_changes מחזיר DataFrame ריק-לגמרי (בלי אף עמודה,
        # כולל "ticker") אם אף טיקר לא הצליח להישלף באותו סבב (למשל Yahoo
        # חסם/rate-limit זמני) - אינדוקס לפי "ticker" על עמודה שלא קיימת קורס
        # ב-KeyError. מתייחסים לזה כמו ל"אין נתון" לכל אחזקה, לא קריסה.
        for _, _r in holdings_df.iterrows():
            _qty = _r["actual_qty"]
            if not _qty:
                continue
            if "ticker" not in _daily_df.columns:
                continue
            _match = _daily_df[_daily_df["ticker"] == _r["ticker"]]
            if _match.empty:
                continue
            _row_data = _match.iloc[0]
            _last_close, _prev_close = _row_data["last_close"], _row_data["prev_close"]
            if pd.isna(_last_close) or pd.isna(_prev_close):
                continue
            try:
                _bought_date = dt.datetime.fromisoformat(_r["bought_at"]).date() if _r.get("bought_at") else None
            except Exception:
                _bought_date = None
            _prev_close_date = _row_data.get("prev_close_date")
            _last_close_date = _row_data.get("last_close_date")
            # השוואה לפי התאריך האמיתי של הנתון, לא לפי "האם נקנה היום" - כי אותה
            # בעיה קיימת גם אם נקנתה אתמול/שלשום והנתון הכי עדכני עדיין קודם לקנייה
            # (שוק סגור בסופ"ש/חג, או שהאחזקה נקנתה אחרי הסגירה של prev_close).
            # אם prev_close מלפני הקנייה - הבסיס הנכון הוא שער הכניסה, לא הסגירה ההיא.
            # אם גם last_close מלפני הקנייה (אין עדיין שום סגירה מאז שהיא נקנתה) -
            # אין לנו נתון אמין בכלל, ומדלגים על האחזקה הזו לגמרי הפעם.
            if _bought_date and _last_close_date and _bought_date >= _last_close_date:
                continue
            _baseline = _prev_close
            if _bought_date and _prev_close_date and _bought_date >= _prev_close_date and _r.get("actual_entry_price"):
                _baseline = _r["actual_entry_price"]
            _ccy2 = constituents.INDEX_CURRENCY.get(_r.get("index_name"), "ILS")
            _agg2 = _today_by_ccy.setdefault(_ccy2, {"prev_value": 0.0, "change": 0.0})
            _agg2["prev_value"] += _baseline * _qty
            _agg2["change"] += (_last_close - _baseline) * _qty
        if _today_by_ccy:
            _dom_ccy2 = max(_today_by_ccy, key=lambda c: _today_by_ccy[c]["prev_value"])
            _dom2 = _today_by_ccy[_dom_ccy2]
            _today_pct = (_dom2["change"] / _dom2["prev_value"] * 100) if _dom2["prev_value"] else 0.0
            today_summary = (
                "שינוי יומי", _dom2["change"], _today_pct, CURRENCY_SYMBOLS.get(_dom_ccy2, _dom_ccy2)
            )

    proximity_summary = None
    if not holdings_df.empty:
        _best = None  # (gap_pct, name, is_target) - הפער הכי קטן שנמצא עד כה בין המחיר הנוכחי לבין היעד או הסטופ
        for _, _r in holdings_df.iterrows():
            _entry, _qty = _r.get("actual_entry_price"), _r.get("actual_qty")
            if not _entry or not _qty:
                continue
            _current = get_current_price(_r["ticker"])
            if _current is None:
                _fallback_prices = get_sparkline_prices(_r["ticker"])
                _current = _fallback_prices[-1] if _fallback_prices else None
            if _current is None:
                continue
            _name = _r.get("company_name") or _r["ticker"]
            _pnl_pct = (_current / _entry - 1) * 100
            _stop_price = get_or_backfill_stop_price(_r, _entry)
            _stop_pct = (_stop_price / _entry - 1) * 100
            _target_price = live_target_price(_entry, _stop_price, _r.get("target_base"))
            _target_pct = (_target_price / _entry - 1) * 100
            _gap_target = _target_pct - _pnl_pct
            _gap_stop = _pnl_pct - _stop_pct
            if _best is None or _gap_target < _best[0]:
                _best = (_gap_target, _name, True)
            if _gap_stop < _best[0]:
                _best = (_gap_stop, _name, False)
        if _best is not None:
            proximity_summary = (_best[1], _best[0], _best[2])

    return portfolio_summary, today_summary, value_summary, proximity_summary


def _compute_portfolio_history(holdings_df: pd.DataFrame):
    """מנרמל את התיק ואת פרוקסי המדד הדומיננטי (לפי איזה index_name הכי הרבה
    כסף מושקע בו) לתשואה % החל מתאריך הקנייה של האחזקה הראשונה, לצורך השוואה
    ישירה בגרף. מחזיר None אם אין מספיק נתונים."""
    if holdings_df.empty:
        return None

    bought_dates = []
    for _, r in holdings_df.iterrows():
        try:
            bought_dates.append(dt.datetime.fromisoformat(r["bought_at"]).date())
        except Exception:
            continue
    if not bought_dates:
        return None
    earliest_bought = min(bought_dates)
    days_span = (dt.date.today() - earliest_bought).days

    if days_span <= 5:
        period = "1mo"
    elif days_span <= 25:
        period = "3mo"
    elif days_span <= 150:
        period = "6mo"
    elif days_span <= 300:
        period = "1y"
    else:
        period = "2y"

    _idx_invested = {}
    for _, r in holdings_df.iterrows():
        idx = r.get("index_name")
        entry, qty = r.get("actual_entry_price"), r.get("actual_qty")
        if not idx or not entry or not qty:
            continue
        _idx_invested[idx] = _idx_invested.get(idx, 0.0) + entry * qty
    if not _idx_invested:
        return None
    dominant_index = max(_idx_invested, key=_idx_invested.get)
    dominant_ccy = constituents.INDEX_CURRENCY.get(dominant_index, "ILS")

    relevant_holdings = holdings_df[
        holdings_df["index_name"].apply(lambda i: constituents.INDEX_CURRENCY.get(i, "ILS") == dominant_ccy)
    ]
    if relevant_holdings.empty:
        return None

    daily_df = market_data.fetch_universe_daily_changes(relevant_holdings["ticker"].tolist(), history_period=period)
    if daily_df.empty:
        return None

    # תשואת % מנורמלת = ממוצע משוקלל (לפי הסכום שהושקע) של אחוז הרווח/הפסד של
    # *כל אחזקה בנפרד* מול מחיר הכניסה שלה - לא נרמול שווי כולל, כי שווי כולל
    # קופץ כשמצטרפת אחזקה חדשה (הון טרי) וזו לא "תשואה", רק עוד כסף שהוכנס.
    weighted_return_by_date: dict = {}
    weight_by_date: dict = {}
    for _, r in relevant_holdings.iterrows():
        match = daily_df[daily_df["ticker"] == r["ticker"]]
        if match.empty:
            continue
        hist = match.iloc[0]["history"]
        if hist is None or hist.empty:
            continue
        try:
            bought_date = dt.datetime.fromisoformat(r["bought_at"]).date()
        except Exception:
            continue
        qty = r.get("actual_qty")
        entry = r.get("actual_entry_price")
        if not qty or not entry:
            continue
        invested = entry * qty
        for ts, price in hist.items():
            d = ts.date() if hasattr(ts, "date") else ts
            if d < bought_date:
                continue
            holding_return_pct = (price / entry - 1) * 100
            weighted_return_by_date[d] = weighted_return_by_date.get(d, 0.0) + holding_return_pct * invested
            weight_by_date[d] = weight_by_date.get(d, 0.0) + invested

    if not weighted_return_by_date:
        return None

    portfolio_return_pct = pd.Series({
        d: weighted_return_by_date[d] / weight_by_date[d] for d in weighted_return_by_date
    }).sort_index()

    comparison_df = None
    benchmark_hist = market_data.fetch_index_history(dominant_index, period)
    if benchmark_hist is not None and not benchmark_hist.empty:
        bench_by_date = {(ts.date() if hasattr(ts, "date") else ts): price for ts, price in benchmark_hist.items()}
        common_dates = sorted(d for d in portfolio_return_pct.index if d in bench_by_date)
        if len(common_dates) >= 2:
            port_pct = portfolio_return_pct.loc[common_dates]
            bench_c = pd.Series({d: bench_by_date[d] for d in common_dates})
            bench_pct = (bench_c / bench_c.iloc[0] - 1) * 100
            comparison_df = pd.DataFrame({
                "התיק שלי": port_pct,
                INDEX_LABELS.get(dominant_index, dominant_index): bench_pct,
            })

    return comparison_df


_CHART_GRID_COLOR = "#E8EBEF"
_CHART_LABEL_COLOR = "#8A94A3"


def _build_pnl_bar_chart(rows: list[dict]) -> alt.Chart:
    """גרף 'בולט' (bullet chart) לכל אחזקה - פס רקע דק מהסטופ ועד היעד (%),
    ועמודה צבעונית שמראה איפה בדיוק עומד הרווח/הפסד הנוכחי בתוך הטווח הזה.
    משלב בבת אחת תשואה + קרבה לסטופ/יעד, שקודם היו שני דברים נפרדים -
    ה-tooltip מציג את שלושת הערכים (תשואה, סטופ, יעד) לכל מניה."""
    df = pd.DataFrame(rows)
    df["color"] = df["pnl_pct"].apply(lambda v: POS_COLOR if v >= 0 else NEG_COLOR)
    df["zero"] = 0.0
    # שדות טקסט מעוצבים מראש (עם _signed_num) במקום להסתמך על format="+.2f" של
    # ה-tooltip האוטומטי של Vega - זה האחרון מציג בעברית RTL את הסימן אחרי המספר
    # (למשל "5.20-" במקום "-5.20") כי אין לו את תיקון ה-LRM שיש בכל שאר האתר.
    df["pnl_pct_text"] = df["pnl_pct"].apply(lambda v: _signed_num(v, 2))
    df["stop_pct_text"] = df["stop_pct"].apply(lambda v: _signed_num(v, 2))
    df["target_pct_text"] = df["target_pct"].apply(lambda v: _signed_num(v, 2))

    y_enc = alt.Y("name:N", sort=alt.EncodingSortField(field="pnl_pct", order="descending"),
                  axis=alt.Axis(title=None, labelColor=_CHART_LABEL_COLOR, labelFontSize=11, labelLimit=170))
    x_scale = alt.Scale(padding=10)
    tooltip = [
        alt.Tooltip("name:N", title="מניה"),
        alt.Tooltip("pnl_pct_text:N", title="תשואה נוכחית"),
        alt.Tooltip("stop_pct_text:N", title="סטופ-לוס"),
        alt.Tooltip("target_pct_text:N", title="יעד"),
    ]

    range_bg = alt.Chart(df).mark_bar(size=7, opacity=0.35, color=_CHART_GRID_COLOR, cornerRadius=3).encode(
        y=y_enc,
        x=alt.X("stop_pct:Q", scale=x_scale,
                axis=alt.Axis(title=None, grid=True, gridColor=_CHART_GRID_COLOR, gridDash=[2, 3],
                               labelColor=_CHART_LABEL_COLOR, labelFontSize=10, format="+.1f")),
        x2="target_pct:Q",
        tooltip=tooltip,
    )
    progress = alt.Chart(df).mark_bar(size=18, cornerRadiusEnd=3).encode(
        y=y_enc, x=alt.X("zero:Q", scale=x_scale), x2="pnl_pct:Q",
        color=alt.Color("color:N", scale=None, legend=None),
        tooltip=tooltip,
    )
    zero_rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=_CHART_GRID_COLOR, strokeWidth=1).encode(x="x:Q")

    # נקודות סימון קטנות בקצוות פס הרקע - ירוקה על היעד, אדומה על הסטופ-לוס,
    # עם מקרא קטן בתחתית הגרף (בלי צורך לקרוא tooltip כדי לדעת מה כל צבע).
    points_df = pd.concat([
        pd.DataFrame({"name": df["name"], "x": df["target_pct"], "סוג": "יעד"}),
        pd.DataFrame({"name": df["name"], "x": df["stop_pct"], "סוג": "סטופ-לוס"}),
    ], ignore_index=True)
    points_df["x_text"] = points_df["x"].apply(lambda v: _signed_num(v, 2))
    points = alt.Chart(points_df).mark_point(size=45, filled=True, opacity=0.95).encode(
        y=alt.Y("name:N"),
        x=alt.X("x:Q", scale=x_scale),
        color=alt.Color("סוג:N", scale=alt.Scale(domain=["סטופ-לוס", "יעד"], range=[NEG_COLOR, POS_COLOR]),
                         legend=alt.Legend(title=None, orient="bottom", direction="horizontal",
                                            labelColor=_CHART_LABEL_COLOR, labelFontSize=10, symbolSize=50)),
        tooltip=[alt.Tooltip("name:N", title="מניה"), alt.Tooltip("סוג:N", title="סוג"),
                 alt.Tooltip("x_text:N", title="ערך (%)")],
    )
    # כשהפס האדום (pnl_pct) גדל מעבר לנקודת הסטופ, הוא מכסה אותה - שתיהן אדומות
    # ואין הבדל ויזואלי ביניהן. קו שחור דק נפרד, בדיוק על מיקום הסטופ, ורק
    # כשהוא באמת נחצה - שכבה אחרונה (מצוירת מעל הכל) כדי שלעולם לא תיעלם.
    crossed_df = df[df["pnl_pct"] <= df["stop_pct"]].copy()
    crossed_df["x_text"] = crossed_df["stop_pct"].apply(lambda v: _signed_num(v, 2))
    stop_crossed = alt.Chart(crossed_df).mark_tick(
        color="black", thickness=2, size=20, opacity=1.0,
    ).encode(
        y=y_enc,
        x=alt.X("stop_pct:Q", scale=x_scale),
        tooltip=[alt.Tooltip("name:N", title="מניה"), alt.Tooltip("x_text:N", title="חצתה סטופ ב-")],
    )

    # גובה קבוע (160) דחס את השורות זו לתוך זו כשמספר האחזקות גדל - Vega-Lite אז
    # מוריד תוויות/סימונים חופפים בשקט, מה שנראה כמו נקודות "כפולות" באותה שורה.
    # לכן הגובה גדל לפי מספר האחזקות במקום קבוע.
    chart_height = max(160, 46 * len(rows))
    return (
        (range_bg + progress + zero_rule + points + stop_crossed)
        .properties(height=chart_height, padding={"left": 8, "right": 12, "top": 8, "bottom": 8})
        .resolve_scale(color="independent")
        .configure_view(strokeWidth=0)
        .configure_axis(domain=False, tickSize=0)
    )


_ALLOCATION_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def _build_allocation_chart(rows: list[dict]) -> alt.Chart:
    """גרף עוגה (donut) - איך התיק מתחלק בין האחזקות לפי שווי נוכחי (לא עלות
    מקורית) - משקף את המשקל האמיתי של כל מניה בתיק היום, לא ביום שנקנתה."""
    df = pd.DataFrame(rows)
    df["pct"] = df["value"] / df["value"].sum() * 100
    chart = alt.Chart(df).mark_arc(innerRadius=42, outerRadius=80, stroke="#fff", strokeWidth=1.5).encode(
        theta=alt.Theta("value:Q", stack=True),
        color=alt.Color("name:N", scale=alt.Scale(range=_ALLOCATION_PALETTE),
                         legend=alt.Legend(title=None, orient="bottom", direction="horizontal", columns=2,
                                            labelColor=_CHART_LABEL_COLOR, labelFontSize=11, symbolType="circle")),
        tooltip=[
            alt.Tooltip("name:N", title="מניה"),
            alt.Tooltip("value:Q", title="שווי", format=",.0f"),
            alt.Tooltip("pct:Q", title="אחוז מהתיק", format=".1f"),
        ],
    )
    return chart.properties(height=200).configure_view(strokeWidth=0)


def _build_mini_allocation_chart(rows: list[dict]) -> alt.Chart:
    """גרסה מוקטנת של גרף ההתפלגות - בלי legend מובנה של Vega (אין לו מקום
    בגודל כרטיס קטן), אלא domain/range מפורשים כדי שהצבעים יתאימו 1:1 לרשימת
    הפירוט הטקסטואלית שמוצגת לצידו (ר' _allocation_legend_html). רקע שקוף
    כדי שהעיגול ישב על רקע הכרטיס ולא על ריבוע לבן."""
    df = pd.DataFrame(rows)  # rows כבר ממוינים לפי value יורד וכוללים עמודת pct
    names = df["name"].tolist()
    colors = _ALLOCATION_PALETTE[: len(names)]
    chart = alt.Chart(df).mark_arc(innerRadius=19, outerRadius=34, stroke="#fff", strokeWidth=1).encode(
        theta=alt.Theta("value:Q", stack=True, sort=None),
        color=alt.Color("name:N", scale=alt.Scale(domain=names, range=colors), legend=None),
        order=alt.Order("value:Q", sort="descending"),
        tooltip=[
            alt.Tooltip("name:N", title="מניה"),
            alt.Tooltip("value:Q", title="שווי", format=",.0f"),
            alt.Tooltip("pct:Q", title="אחוז מהתיק", format=".1f"),
        ],
    )
    return (
        chart.properties(height=68, width=68, background="transparent")
        .configure_view(strokeWidth=0, fill=None)
    )


def _allocation_legend_html(rows: list[dict]) -> str:
    """רשימת פירוט קומפקטית (נקודה צבעונית + שם + אחוז) לצד המיני-גרף, בסדר
    ובצבעים זהים בדיוק לפלחי העוגה - כדי שהפירוט יהיה גלוי תמיד ולא רק ב-hover.
    בלי flex (שמתעלם מ-direction:rtl ומפזר את הנקודה לצד הלא-נכון) - כמו
    _status_dot, נקודה inline-block לפני הטקסט בתוך div עם direction:rtl מפורש."""
    items = "".join(
        f'<div style="direction:rtl; text-align:right; white-space:nowrap; overflow:hidden; '
        f'text-overflow:ellipsis; font-size:12.5px; font-weight:500; line-height:22px; opacity:0.9;">'
        f'<span style="display:inline-block; width:9px; height:9px; border-radius:50%; '
        f'background:{_ALLOCATION_PALETTE[i % len(_ALLOCATION_PALETTE)]}; margin-left:7px; '
        f'vertical-align:middle;"></span>{r["name"]} <b>· {r["pct"]:.0f}%</b></div>'
        for i, r in enumerate(rows)
    )
    return f'<div style="display:flex; flex-direction:column; gap:2px; justify-content:center;">{items}</div>'


def _stacked_bar_html(rows: list[dict], height: int = 20, gap_pct: float = 0.6, radius: int = 10) -> str:
    """סרגל אחוזים אופקי (stacked bar) - חלף את הדונאט: לפי מתודולוגיית ה-dataviz,
    חלק-מתוך-שלם עם שמות קטגוריה ארוכים (עברית) קריא יותר כסרגל מאשר כעוגה
    ("donut stays deprioritized"). מיקום ב-% (לא px קבוע) כדי שיתאים לרוחב
    הכרטיס בפועל, ו-right מחושב ידנית (לא flex/direction) - נמנע לגמרי מבעיות
    ה-RTL/flex שכבר נתקלנו בהן עם הדונאט. row הראשון (הכי גדול, rows כבר
    ממוין יורד) מתחיל בקצה הימני - התחלת הקריאה בעברית. פינות מעוגלות רק
    בקצוות החיצוניים של הסרגל כולו, ריבועיות במפגשים הפנימיים בין קטעים."""
    total = sum(row["value"] for row in rows) or 1.0
    n = len(rows)
    usable_pct = 100 - gap_pct * (n - 1)
    segments = []
    running_right_pct = 0.0
    for i, row in enumerate(rows):
        seg_pct = max((row["value"] / total) * usable_pct, 1.5)
        color = _ALLOCATION_PALETTE[i % len(_ALLOCATION_PALETTE)]
        if n == 1:
            border_radius = f"{radius}px"
        elif i == 0:
            border_radius = f"0 {radius}px {radius}px 0"
        elif i == n - 1:
            border_radius = f"{radius}px 0 0 {radius}px"
        else:
            border_radius = "0"
        segments.append(
            f'<div title="{row["name"]} · {row["pct"]:.0f}%" '
            f'style="position:absolute; right:{running_right_pct:.2f}%; top:0; '
            f'width:{seg_pct:.2f}%; height:{height}px; background:{color}; '
            f'border-radius:{border_radius};"></div>'
        )
        running_right_pct += seg_pct + gap_pct
    return (
        f'<div style="position:relative; width:100%; height:{height}px;">{"".join(segments)}</div>'
    )


def _mini_donut_svg(rows: list[dict], center_count: int | None = None,
                     size: int = 54, stroke: int = 12, gap: float = 1.8) -> str:
    """דונאט זעיר - לשילוב במשבצת סיכום קומפקטית, לצד מקרא טקסטואלי מלא (לא
    רק hover) שמראה כל שם וכל אחוז בפועל, בלי לתפוס את כל רוחב המשבצת.
    center_count - מספר (למשל כמות אחזקות) בחור הדונאט; מסובב 90 מעלות נגד
    כיוון סיבוב ה-SVG כולו (-90) כדי שהטקסט יישאר זקוף, לא יורש את הסיבוב."""
    r = (size - stroke) / 2
    cx = cy = size / 2
    circumference = 2 * 3.14159265 * r
    total = sum(row["value"] for row in rows) or 1.0
    segments = []
    offset = 0.0
    for i, row in enumerate(rows):
        frac = row["value"] / total
        length = max(frac * circumference - gap, 1.0)
        color = _ALLOCATION_PALETTE[i % len(_ALLOCATION_PALETTE)]
        segments.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" '
            f'stroke-dasharray="{length:.2f} {circumference:.2f}" stroke-dashoffset="{-offset:.2f}"/>'
        )
        offset += frac * circumference
    center_text = ""
    if center_count is not None:
        center_text = (
            f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
            f'transform="rotate(90 {cx} {cy})" font-size="16" font-weight="700" '
            f'fill="{NEUTRAL_COLOR}">{center_count}</text>'
        )
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'style="transform:rotate(-90deg); flex-shrink:0;">{"".join(segments)}{center_text}</svg>'
    )


def _stat_card_breakdown(label: str, rows: list[dict], holdings_count: int | None = None,
                          color: str = NEUTRAL_COLOR, bg: str = NEUTRAL_BG) -> str:
    """משבצת סיכום קומפקטית, באותו סגנון בדיוק כמו _stat_card (אותו גופן/גודל
    כותרת) - עם דונאט זעיר (ומספר האחזקות בחור שלו) + מקרא (שם וכל אחוז
    מוצגים תמיד, לא רק ב-hover) במקום מספר בודד, לשילוב ישיר בשורת הסיכום."""
    donut = _mini_donut_svg(rows)
    legend_items = "".join(
        f'<div style="direction:rtl; text-align:right; white-space:nowrap; overflow:hidden; '
        f'text-overflow:ellipsis; font-size:12.5px; font-weight:700; line-height:17px; opacity:0.9;">'
        f'<span style="display:inline-block; width:6px; height:6px; border-radius:50%; '
        f'background:{_ALLOCATION_PALETTE[i % len(_ALLOCATION_PALETTE)]}; margin-left:4px; '
        f'vertical-align:middle;"></span>{r["name"]} <b>{r["pct"]:.0f}%</b></div>'
        for i, r in enumerate(rows)
    )
    legend = f'<div style="display:flex; flex-direction:column; gap:2px; justify-content:center;">{legend_items}</div>'
    count_label = (
        f'<style>.holding-count-label{{text-align:left !important;}}</style>'
        f'<div class="holding-count-label" style="font-size:0.8rem; font-weight:600; opacity:0.75; margin-top:6px;">'
        f'{holdings_count} אחזקות</div>'
        if holdings_count is not None else ""
    )
    return (
        f'<div style="flex:1; min-width:170px; border:1px solid {color}33; border-radius:12px; '
        f'padding:12px 14px; background:{bg}; box-shadow:0 2px 6px rgba(0,0,0,0.05);">'
        f'<div style="font-size:0.8rem; font-weight:600; opacity:0.75; text-align:center; margin-bottom:8px;">{label}</div>'
        f'<div style="display:flex; direction:rtl; align-items:center; justify-content:center; gap:20px;">'
        f'{legend}{donut}</div>{count_label}</div>'
    )




_SECTOR_LABELS_HE = {
    "Technology": "טכנולוגיה",
    "Financial Services": "שירותים פיננסיים",
    "Financials": "פיננסים",
    "Healthcare": "בריאות",
    "Energy": "אנרגיה",
    "Consumer Cyclical": "צריכה מחזורית",
    "Consumer Defensive": "צריכה בסיסית",
    "Industrials": "תעשייה",
    "Basic Materials": "חומרי גלם",
    "Real Estate": 'נדל"ן',
    "Utilities": "שירותים ציבוריים",
    "Communication Services": "תקשורת",
}


def _breakdown_rows(agg: dict) -> list[dict]:
    """ממיר {תווית: שווי} ל-rows בפורמט ש-_build_mini_allocation_chart/_allocation_legend_html
    מצפים לו (name/value/pct, ממוין יורד לפי value)."""
    total = sum(agg.values()) or 1.0
    items = [{"name": name, "value": value, "pct": value / total * 100} for name, value in agg.items()]
    items.sort(key=lambda r: r["value"], reverse=True)
    return items


def _build_comparison_chart(df: pd.DataFrame, port_col: str, bench_col: str, port_color: str) -> alt.Chart:
    """גרף תשואת התיק מול המדד - שני קווים עם legend קבוע בתחתית (בשטח משלו,
    לא חופף לצירי הזמן כמו ב-st.line_chart המובנה), וקו אפס מקווקו לייחוס."""
    # value_name="value" (לא "תשואה") בכוונה - כשגם שם השדה הגולמי וגם הכותרת
    # (title) של שדה ה-tooltip המעוצב זהים ("תשואה"), Vega-Lite מתבלבל ביניהם
    # (collision במפתח ה-tooltip הפנימי) ומציג את הערך הגולמי הלא-מעוצב במקום
    # את "תשואה_טקסט" - זה מה שגרם לטולטיפ להציג מספר עם 11 ספרות וסימן הפוך.
    long_df = df.rename_axis("תאריך").reset_index().melt(id_vars="תאריך", var_name="סדרה", value_name="value")
    long_df["תאריך"] = pd.to_datetime(long_df["תאריך"])
    _tick_dates = sorted(long_df["תאריך"].unique())
    long_df["תשואה_טקסט"] = long_df["value"].apply(lambda v: _signed_num(v, 2))

    zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color=_CHART_GRID_COLOR, strokeDash=[3, 3], strokeWidth=1,
    ).encode(y="y:Q")

    x_enc = alt.X("תאריך:T", scale=alt.Scale(padding=14),
                   axis=alt.Axis(format="%d/%m", title=None, grid=False, values=_tick_dates,
                                  labelColor=_CHART_LABEL_COLOR, labelFontSize=10))
    y_enc = alt.Y("value:Q", scale=alt.Scale(padding=8),
                   axis=alt.Axis(title=None, grid=True, gridColor=_CHART_GRID_COLOR,
                                  gridDash=[2, 3], labelColor=_CHART_LABEL_COLOR, labelFontSize=10))
    color_enc = alt.Color(
        "סדרה:N",
        scale=alt.Scale(domain=[port_col, bench_col], range=[port_color, NEUTRAL_COLOR]),
        legend=alt.Legend(title=None, orient="bottom", direction="horizontal",
                           labelColor=_CHART_LABEL_COLOR, labelFontSize=11, symbolType="stroke"),
    )
    _tooltip = [
        alt.Tooltip("תאריך:T", title="תאריך", format="%d/%m/%Y"),
        alt.Tooltip("סדרה:N", title=""),
        alt.Tooltip("תשואה_טקסט:N", title="תשואה"),
    ]
    line = alt.Chart(long_df).mark_line(interpolate="monotone", strokeWidth=2.5, clip=False).encode(
        x=x_enc, y=y_enc, color=color_enc, tooltip=_tooltip,
    )
    points = alt.Chart(long_df).mark_circle(size=40, clip=False).encode(
        x=x_enc, y=y_enc,
        color=alt.Color("סדרה:N", scale=alt.Scale(domain=[port_col, bench_col], range=[port_color, NEUTRAL_COLOR]),
                         legend=None),
        tooltip=_tooltip,
    )
    return (
        (zero_rule + line + points)
        .properties(height=160, padding={"left": 8, "right": 12, "top": 8, "bottom": 8})
        .configure_view(strokeWidth=0)
        .configure_axis(domain=False, tickSize=0)
    )


def _autosave_settings():
    """נשמר אוטומטית ל-config.yaml ברגע שמשנים ערך בסיידבר - בלי כפתור "שמור"
    נפרד, כי אלה רק שני שדות פשוטים ואין סיבה אמיתית לדחות את הכתיבה לדיסק."""
    new_indices = st.session_state.get("settings_indices")
    if not new_indices:
        st.toast("יש לבחור לפחות מדד אחד - לא נשמר.", icon="⚠️", duration=2)
        return
    cfg["indices"] = new_indices
    cfg.pop("index", None)
    cfg["drop_threshold_pct"] = st.session_state.get("settings_threshold")
    cfg["multi_day_window_days"] = st.session_state.get("settings_multi_day_days")
    cfg["multi_day_threshold_pct"] = st.session_state.get("settings_multi_day_threshold")
    cfg["multi_day_enabled"] = st.session_state.get("settings_multi_day_enabled", True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("settings")
    st.toast("ההגדרות נשמרו.", icon="💾", duration=2)


def _autosave_fees():
    """אותה שמירה אוטומטית כמו בהגדרות הסריקה - כדי שאם עמלת הברוקר או שיעור
    המס משתנים, אפשר יהיה לעדכן ישירות בממשק בלי לערוך את config.yaml ידנית."""
    for country, prefix in (("IL", "fees_il_"), ("US", "fees_us_")):
        cfg["fees"][country]["commission_pct"] = st.session_state.get(f"{prefix}commission_pct")
        cfg["fees"][country]["commission_min"] = st.session_state.get(f"{prefix}commission_min")
        cfg["fees"][country]["capital_gains_tax_pct"] = st.session_state.get(f"{prefix}tax_pct")
        cfg["fees"][country]["management_fee_annual_pct"] = st.session_state.get(f"{prefix}mgmt_pct")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("fees")
    st.toast("עמלות ומיסים נשמרו.", icon="💾", duration=2)


def _autosave_position():
    """גודל ההשקעה המוצע וגודל התיק/סיכון לעסקה - קובעים את גודל הפוזיציה
    (מבוסס-סיכון אם התיק הכולל מוגדר) ואת חישוב הרווח/הפסד נטו שמוצג בכל
    התראה (לא רק בדשבורד, גם בהודעת הטלגרם)."""
    cfg["position_size"] = {
        "ILS": st.session_state.get("settings_position_ils"),
        "USD": st.session_state.get("settings_position_usd"),
    }
    cfg["max_position_size"] = {
        "ILS": st.session_state.get("settings_max_position_ils"),
        "USD": st.session_state.get("settings_max_position_usd"),
    }
    cfg["risk_pct_per_trade"] = st.session_state.get("settings_risk_pct")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("position sizing")
    st.toast("הגדרות גודל השקעה נשמרו.", icon="💾", duration=2)


def _autosave_holdings_alerts():
    """מתי מקבלים התראת 'עלייה' על אחזקה, ומתי 'קרוב לסטופ-לוס'/'קרוב ליעד' -
    סיכון אישי, לא רק ניסוח."""
    cfg["holdings_gain_alert_start_pct"] = st.session_state.get("settings_gain_start")
    cfg["holdings_gain_alert_step_pct"] = st.session_state.get("settings_gain_step")
    cfg["holdings_stop_warn_pct"] = st.session_state.get("settings_stop_warn")
    cfg["holdings_target_warn_pct"] = st.session_state.get("settings_target_warn")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("holdings alerts")
    st.toast("הגדרות התראות אחזקות נשמרו.", icon="💾", duration=2)


def _autosave_message_types():
    types = {
        key: bool(st.session_state.get(f"settings_msgtype_{key}", True))
        for key in notifier.MESSAGE_TYPES
    }
    cfg["telegram_message_types"] = types
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("message types")
    st.toast("סוגי התראה נשמרו.", icon="💾", duration=2)


def _autosave_channels():
    cfg.setdefault("telegram", {})["enabled"] = st.session_state.get("settings_telegram_enabled", True)
    cfg.setdefault("desktop_notifications", {})["enabled"] = st.session_state.get("settings_desktop_enabled", True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("notification channels")
    st.toast("ערוצי התראה נשמרו.", icon="💾", duration=2)


with st.sidebar:
    current_indices = cfg.get("indices") or ([cfg["index"]] if "index" in cfg else [])

    with st.container(border=True):
        st.markdown("**📊 מדדים לסריקה**")
        st.multiselect(
            "בחר מדד/ים לסריקה", ALL_INDICES, default=current_indices, label_visibility="collapsed",
            key="settings_indices", on_change=_autosave_settings,
        )
        st.markdown("**📉 ירידה יומית להתראה**")
        tc1, tc2 = st.columns([5, 1])
        tc1.number_input(
            "אחוז ירידה שמפעיל התראה", min_value=0.5, max_value=50.0,
            value=float(cfg["drop_threshold_pct"]), step=0.5, label_visibility="collapsed",
            key="settings_threshold", on_change=_autosave_settings,
        )
        tc2.markdown("<div style='padding-top:10px;'>%</div>", unsafe_allow_html=True)

        st.markdown("**📉 ירידה מצטברת**")
        dc1, dc2 = st.columns([5, 1])
        dc1.number_input(
            "מספר ימים לירידה מצטברת", min_value=2, max_value=10, step=1,
            value=int(cfg.get("multi_day_window_days", 3)), label_visibility="collapsed",
            key="settings_multi_day_days", on_change=_autosave_settings,
            disabled=not st.session_state.get("settings_multi_day_enabled", cfg.get("multi_day_enabled", True)),
        )
        dc2.markdown("<div style='padding-top:10px;'>ימים</div>", unsafe_allow_html=True)
        mc1, mc2 = st.columns([5, 1])
        mc1.number_input(
            "אחוז ירידה מצטברת שמפעיל התראה", min_value=0.5, max_value=50.0,
            value=float(cfg.get("multi_day_threshold_pct", 5.0)), step=0.5, label_visibility="collapsed",
            key="settings_multi_day_threshold", on_change=_autosave_settings,
            disabled=not st.session_state.get("settings_multi_day_enabled", cfg.get("multi_day_enabled", True)),
        )
        mc2.markdown("<div style='padding-top:10px;'>%</div>", unsafe_allow_html=True)
        st.checkbox(
            "הפעל התראת ירידה מצטברת", value=bool(cfg.get("multi_day_enabled", True)),
            key="settings_multi_day_enabled", on_change=_autosave_settings,
        )

    with st.container(key="scan_button_box", border=True):
        # מעצבים את הכפתור עצמו (שקוף, בלי מילוי כחול) כדי שיתאים ויזואלית
        # לכותרות ה-expander-ים האחרים בסיידבר - אותה תיבה עם מסגרת, אותו
        # משקל/גודל טקסט/padding. עדיין כפתור אמיתי (לא מתקפל), לא expander מזויף.
        st.markdown(
            """
            <style>
            div[class*="st-key-scan_button_box"] { padding: 0 !important; gap: 0 !important; }
            div[class*="st-key-scan_button_box"] [data-testid="stElementContainer"]:has(style) {
                display: none;
            }
            div[class*="st-key-scan_button_box"] button {
                background-color: transparent !important; border: none !important;
                box-shadow: none !important; font-weight: 400 !important;
                font-size: 14px !important; padding: 4px 12px !important; width: 100%;
                text-align: right !important; justify-content: flex-start !important;
                color: inherit !important;
            }
            div[class*="st-key-scan_button_box"] button p {
                font-weight: 400 !important; font-size: 14px !important; color: inherit !important;
            }
            div[class*="st-key-scan_button_box"] button > div {
                justify-content: flex-start !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🔍 סריקת שווקים ידנית", key="sidebar_scan_button", use_container_width=True):
            # קריאה ישירה ממצב הווידג'טים הנוכחי, לא סומכים על זה שהשמירה האוטומטית
            # כבר הספיקה "להתיישב" ב-cfg לפני הלחיצה על סריקה (כדי לא לסרוק מדד ישן)
            cfg["indices"] = st.session_state.get("settings_indices") or cfg.get("indices")
            cfg["drop_threshold_pct"] = st.session_state.get("settings_threshold", cfg.get("drop_threshold_pct"))
            cfg["multi_day_threshold_pct"] = st.session_state.get(
                "settings_multi_day_threshold", cfg.get("multi_day_threshold_pct")
            )
            cfg["multi_day_enabled"] = st.session_state.get(
                "settings_multi_day_enabled", cfg.get("multi_day_enabled", True)
            )
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
            with st.spinner("סורק..."):
                results = run_scan(cfg)
            st.success(f"הסתיים - {len(results)} התראות חדשות")

    with st.expander("💵 השקעה וסיכון"):
        st.caption("קובע את גודל הפוזיציה המוצע ואת חישוב הרווח/הפסד נטו בכל התראה")
        st.markdown("**סכום השקעה מינימלי**")
        ps1, ps2 = st.columns(2)
        ps1.number_input(
            'ש"ח', min_value=0.0, step=500.0, format="%.0f",
            value=float(cfg.get("position_size", {}).get("ILS", 10000)),
            key="settings_position_ils", on_change=_autosave_position,
        )
        ps2.number_input(
            "$", min_value=0.0, step=500.0, format="%.0f",
            value=float(cfg.get("position_size", {}).get("USD", 10000)),
            key="settings_position_usd", on_change=_autosave_position,
        )
        st.markdown("**תקרת השקעה מקסימלית**")
        mx1, mx2 = st.columns(2)
        mx1.number_input(
            'ש"ח', min_value=0.0, step=500.0, format="%.0f",
            value=float(cfg.get("max_position_size", {}).get("ILS", 30000)),
            key="settings_max_position_ils", on_change=_autosave_position,
        )
        mx2.number_input(
            "$", min_value=0.0, step=500.0, format="%.0f",
            value=float(cfg.get("max_position_size", {}).get("USD", 30000)),
            key="settings_max_position_usd", on_change=_autosave_position,
        )
        st.markdown("**שווי התיק הכולל**")
        _account_size_conn = store.get_conn(db_path(cfg))
        try:
            _account_size_by_ccy = compute_holdings_value_by_currency(
                _account_size_conn, price_fetcher=get_current_price,
            )
        finally:
            _account_size_conn.close()
        as1, as2 = st.columns(2)
        as1.number_input(
            'ש"ח', value=float(_account_size_by_ccy.get("ILS", 0.0)), disabled=True, format="%.0f",
            key="preview_account_ils",
        )
        as2.number_input(
            "$", value=float(_account_size_by_ccy.get("USD", 0.0)), disabled=True, format="%.0f",
            key="preview_account_usd",
        )
        st.markdown(
            "**סיכון לעסקה**",
            help="סכום לסיכון בעסקה בודדת - קובע את גודל הפוזיציה בהתאם לסטופ-לוס",
        )
        rp1, rp2, rp3 = st.columns(3)
        rp1.number_input(
            "% מהתיק", min_value=0.1, max_value=10.0, step=0.05,
            value=float(cfg.get("risk_pct_per_trade", 0.75)),
            key="settings_risk_pct", on_change=_autosave_position,
        )
        # נגזרת חיה: אחוז הסיכון (מה-widget, גם לפני שהשמירה/רענון הושלמו) כפול
        # שווי התיק בכל מטבע - כדי שהמשתמש יראה מייד כמה כסף בפועל הוא מסכן,
        # לא רק את האחוז המופשט.
        _risk_pct_live = float(st.session_state.get("settings_risk_pct", cfg.get("risk_pct_per_trade", 0.75)))
        rp2.number_input(
            'ש"ח', value=_account_size_by_ccy.get("ILS", 0.0) * _risk_pct_live / 100.0,
            disabled=True, format="%.0f", key="preview_risk_amount_ils",
        )
        rp3.number_input(
            "$", value=_account_size_by_ccy.get("USD", 0.0) * _risk_pct_live / 100.0,
            disabled=True, format="%.0f", key="preview_risk_amount_usd",
        )

    with st.expander("📈 התראת אחזקות"):
        st.caption("מתי לקבל התראת 'עלייה' על אחזקה, ומתי 'קרוב לסטופ-לוס'/'קרוב ליעד'")
        st.markdown("**סף עלייה ראשוני (%)**")
        st.number_input(
            "סף עלייה ראשוני", min_value=0.5, max_value=50.0, step=0.5,
            value=float(cfg.get("holdings_gain_alert_start_pct", 2.0)), label_visibility="collapsed",
            key="settings_gain_start", on_change=_autosave_holdings_alerts,
        )
        st.markdown("**כל עלייה נוספת (%)**")
        st.number_input(
            "מדרגת עלייה", min_value=0.5, max_value=50.0, step=0.5,
            value=float(cfg.get("holdings_gain_alert_step_pct", 1.0)), label_visibility="collapsed",
            key="settings_gain_step", on_change=_autosave_holdings_alerts,
        )
        st.markdown("**מרחק אזהרת סטופ-לוס (%)**")
        st.number_input(
            "מרחק אזהרת סטופ", min_value=0.0, max_value=20.0, step=0.5,
            value=float(cfg.get("holdings_stop_warn_pct", STOP_WARN_PCT)), label_visibility="collapsed",
            key="settings_stop_warn", on_change=_autosave_holdings_alerts,
        )
        st.markdown("**מרחק אזהרת יעד (%)**")
        st.number_input(
            "מרחק אזהרת יעד", min_value=0.0, max_value=20.0, step=0.5,
            value=float(cfg.get("holdings_target_warn_pct", TARGET_WARN_PCT)), label_visibility="collapsed",
            key="settings_target_warn", on_change=_autosave_holdings_alerts,
        )

    with st.expander("💰 עמלות ומיסים"):
        for country, prefix, ccy_symbol in (("IL", "fees_il_", 'ש"ח'), ("US", "fees_us_", "$")):
            st.markdown(f"**{'ישראל' if country == 'IL' else 'ארה\"ב'}**")
            col_a, col_b = st.columns(2)
            col_a.number_input(
                "עמלה (%)", min_value=0.0, max_value=5.0, step=0.05,
                value=float(cfg["fees"][country]["commission_pct"]),
                key=f"{prefix}commission_pct", on_change=_autosave_fees,
            )
            col_b.number_input(
                f"מינימום ({ccy_symbol})", min_value=0.0, step=1.0,
                value=float(cfg["fees"][country]["commission_min"]),
                key=f"{prefix}commission_min", on_change=_autosave_fees,
            )
            col_c, col_d = st.columns(2)
            col_c.number_input(
                "מס רווח הון (%)", min_value=0.0, max_value=50.0, step=1.0,
                value=float(cfg["fees"][country]["capital_gains_tax_pct"]),
                key=f"{prefix}tax_pct", on_change=_autosave_fees,
            )
            col_d.number_input(
                "דמי ניהול (%)", min_value=0.0, max_value=10.0, step=0.05,
                value=float(cfg["fees"][country]["management_fee_annual_pct"]),
                key=f"{prefix}mgmt_pct", on_change=_autosave_fees,
            )

    with st.expander("🔔 סוגי התראה"):
        _saved_msg_types = cfg.get("telegram_message_types", {})
        for _mt_key, _mt_label in notifier.MESSAGE_TYPES.items():
            st.checkbox(
                _mt_label, value=bool(_saved_msg_types.get(_mt_key, True)),
                key=f"settings_msgtype_{_mt_key}", on_change=_autosave_message_types,
            )

    st.markdown(
        '<b><span style="display:inline-block; transform:scaleX(-1);">📢</span> ערוצי התראה</b>',
        unsafe_allow_html=True,
    )
    ch1, ch2, _ch3 = st.columns([1.3, 1.3, 1.4])
    ch1.checkbox(
        "טלגרם", value=bool(cfg.get("telegram", {}).get("enabled", True)),
        key="settings_telegram_enabled", on_change=_autosave_channels,
    )
    ch2.checkbox(
        "דסקטופ", value=bool(cfg.get("desktop_notifications", {}).get("enabled", True)),
        key="settings_desktop_enabled", on_change=_autosave_channels,
    )



@st.cache_data(ttl=60)
def get_all_changes(index_name: str, n_days: int = 3) -> pd.DataFrame:
    tickers = constituents.get_constituents(index_name)
    df = market_data.fetch_universe_daily_changes(tickers)
    if df.empty:
        return df
    # לא מסתירים נתון ישן - מציגים אותו, אבל מסמנים כדי שהתצוגה תוכל להיות
    # כנה לגבי מאיזה תאריך הוא בפועל (ראו שימוש ב-"is_stale"/"last_close_date"
    # בטאב "מניות מובילות", שמעדכן את כותרת העמודה בהתאם במקום להראות "יומי"
    # על נתון בן כמה ימים.
    df["is_stale"] = df.apply(lambda r: market_data.is_data_stale(r["last_close_date"], r["ticker"]), axis=1)
    # שם העמודה לא כולל את מספר הימים (בניגוד למקור) - n_days ניתן לשינוי מהמשתמש
    # בטאב עצמו, אז שם קבוע (לא "...3 ימי...") נמנע מפיצול מטמון סמוי לפי הכותרת.
    df["change_nd"] = df["history"].apply(lambda h: market_data.compute_n_day_change_pct(h, n_days))
    df = df.sort_values("pct_change", ascending=False)
    df = df.rename(columns={
        "ticker": "טיקר", "last_close": "שער",
        "pct_change": "שינוי יומי (%)", "change_nd": "שינוי מצטבר (%)",
    })
    if index_name.upper() in ("TA35", "TA125"):
        name_map = constituents.get_il_name_map(index_name)
    else:
        name_map = constituents.get_us_name_map(index_name)
    df["company_name"] = df["טיקר"].map(name_map).fillna("")
    df["index_name"] = index_name
    column_order = ["שער", "שינוי מצטבר (%)", "שינוי יומי (%)", "טיקר", "company_name",
                     "last_close_date", "is_stale", "index_name"]
    return df[column_order]


def _color_pct(val):
    if pd.isna(val):
        return ""
    color = POS_COLOR if val >= 0 else NEG_COLOR
    return f"color: {color}; font-weight: 600"


def _html_table(df: pd.DataFrame, columns: list[tuple[str, str]], formatters: dict | None = None,
                 color_columns: set | None = None, color_fns: dict | None = None,
                 max_height: int | None = None, truncate_columns: dict | None = None,
                 wrap_headers: bool = True) -> str:
    """טבלת HTML פשוטה, בסדר עמודות טבעי (מימין לשמאל, כמו שכתוב כאן) - תחליף ל-
    st.dataframe בטבלאות שמציגות טיקרים/טקסט עברי. st.dataframe מצייר הכל על
    canvas תמיד משמאל לימין ומתעלם לגמרי מ-CSS, מה שגורם לחיתוך טקסט ולעמודות
    שנעלמות כשהטבלה צרה (למשל שתי טבלאות זו לצד זו) - אין דרך לתקן את זה ב-CSS
    כי אין DOM/CSS אמיתי בתוך ה-canvas. ראו גם את טבלת יומן העסקאות שכבר בנויה כך."""
    formatters = formatters or {}
    color_columns = color_columns or set()
    color_fns = color_fns or {}
    truncate_columns = truncate_columns or {}
    def _header_cell(col: str, label: str) -> str:
        style = "padding:6px 10px; text-align:right; font-weight:600; border-bottom:1px solid rgba(128,128,128,0.3);"
        if col in truncate_columns:
            if wrap_headers:
                # בניגוד לתאי הנתונים (nowrap+ellipsis, כי הערך תמיד קצר) - כותרת
                # יכולה להיות ארוכה יותר מהעמודה הצרה שהיא כותרת עליה, אז עדיף
                # שתעטוף לשתי שורות מאשר שתיחתך עם "..." ותאבד את המשמעות.
                style += f" max-width:{truncate_columns[col]}px; white-space:normal; word-break:break-word;"
            else:
                # wrap_headers=False - העמודות רחבות מספיק שהכותרת נכנסת בשורה
                # אחת (נקבע ע"י הקורא), אז נשארים על nowrap כמו תאי הנתונים.
                style += f" max-width:{truncate_columns[col]}px; white-space:nowrap;"
        else:
            style += " white-space:nowrap;"
        return f'<th style="{style}">{label}</th>'

    header_cells = "".join(_header_cell(col, label) for col, label in columns)
    body_rows = []
    for _, r in df.iterrows():
        cells = []
        for col, _ in columns:
            raw = r[col]
            text = formatters[col](raw) if col in formatters else ("" if pd.isna(raw) else str(raw))
            style = ("padding:6px 10px; text-align:right; white-space:nowrap; "
                     "border-bottom:1px solid rgba(128,128,128,0.15);")
            if col in color_fns and pd.notna(raw):
                style += f" color:{color_fns[col](raw)}; font-weight:600;"
            elif col in color_columns and pd.notna(raw):
                color = POS_COLOR if raw >= 0 else NEG_COLOR
                style += f" color:{color}; font-weight:600;"
            if col in truncate_columns:
                # td עצמו לא אוכף max-width באמינות ב-table-layout:auto (הטבלה
                # עדיין מתרחבת לפי תוכן) - עוטפים ב-div פנימי עם overflow:hidden,
                # שכן זה אוכף את החיתוך בצורה אמינה בכל דפדפן.
                width_px = truncate_columns[col]
                inner = (f'<div style="max-width:{width_px}px; overflow:hidden; text-overflow:ellipsis; '
                         f'white-space:nowrap;" title="{text}">{text}</div>')
                cells.append(f'<td style="{style}">{inner}</td>')
            else:
                cells.append(f'<td style="{style}">{text}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    # table-layout:fixed + colgroup - כשיש עמודה מוגבלת ברוחב (truncate_columns), חובה
    # לקבוע רוחב מפורש לכל העמודות, אחרת table-layout:auto מתעלם מ-max-width ומתרחב
    # לפי התוכן בכל מקרה (ראו הערה בתוך הלולאה למעלה).
    table_layout_style = ""
    colgroup_html = ""
    if truncate_columns:
        table_layout_style = "table-layout:fixed; "
        colgroup_html = "<colgroup>" + "".join(
            f'<col style="width:{truncate_columns[col]}px;">' if col in truncate_columns else "<col>"
            for col, _ in columns
        ) + "</colgroup>"
    table_html = (
        f'<table style="width:100%; {table_layout_style}border-collapse:collapse; direction:rtl; font-size:0.85rem;">'
        f'{colgroup_html}<thead><tr>{header_cells}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'
    )
    # overflow-x:auto תמיד - אם העמודות לא נכנסות ברוחב הזמין (למשל שתי טבלאות
    # זו לצד זו בחצי מסך), מקבלים גלילה אופקית במקום שהדפדפן יחתוך עמודות בשקט.
    height_style = f"max-height:{max_height}px; overflow-y:auto; " if max_height else ""
    table_html = f'<div style="{height_style}overflow-x:auto;">{table_html}</div>'
    return table_html


def _render_movers_style_table(sub_df: pd.DataFrame, cumulative_label: str = "מצטבר") -> None:
    """טבלת HTML קומפקטית בסגנון 'מניות מובילות' (מניה/שינוי יומי/מצטבר/שער
    נוכחי) - משותפת בין הטאב ההוא לבין 'קרוב לסף התראה' בטאב ההתראות, ששניהם
    מציגים בדיוק אותה צורת נתונים (פלט של get_all_changes)."""
    sub_df = sub_df.copy()
    sub_df["שם_וטיקר"] = sub_df.apply(
        lambda r: f"{r['company_name']} ({r['טיקר']})" if r["company_name"] else r["טיקר"], axis=1
    )
    # שער מוצג באגורות למניות ת"א (ר' _price_text) - מפורמט מראש כמחרוזת ולא
    # כ-formatter רגיל, כי צריך גישה ל-index_name של השורה, לא רק לערך עצמו.
    sub_df["שער"] = sub_df.apply(lambda r: _price_text(r["שער"], r["index_name"]), axis=1)
    st.markdown(
        _html_table(
            sub_df,
            [("שם_וטיקר", "מניה"), ("שינוי יומי (%)", "שינוי יומי"),
             ("שינוי מצטבר (%)", cumulative_label), ("שער", "שער נוכחי")],
            formatters={
                "שינוי יומי (%)": lambda v: _signed_num(v, 1, "%"),
                "שינוי מצטבר (%)": lambda v: _signed_num(v, 1, "%") if pd.notna(v) else "—",
            },
            color_columns={"שינוי יומי (%)", "שינוי מצטבר (%)"},
            truncate_columns={"שם_וטיקר": 169, "שינוי יומי (%)": 58, "שינוי מצטבר (%)": 58, "שער": 58},
            max_height=min(35 * (len(sub_df) + 1) + 3, 2000),
        ),
        unsafe_allow_html=True,
    )


def _outcome_color_hex(label: str) -> str:
    if label == backtest.OUTCOME_LABELS_HE.get(backtest.HIT_TARGET):
        return POS_COLOR
    if label == backtest.OUTCOME_LABELS_HE.get(backtest.HIT_STOP):
        return NEG_COLOR
    return NEUTRAL_COLOR



_tab_slot_movers = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
with _tab_slot_movers.container():
    if st.session_state.active_tab == "movers":
        @st.fragment(run_every="60s")
        def _render_movers_tab() -> None:
            """fragment עם run_every - מתעדכן לבד כל דקה בלי שהמשתמש ירענן את הדף,
            כי st.cache_data(ttl=...) לבדו קובע רק מתי המטמון נחשב ישן, לא גורם
            לריצה מחדש בעצמו. חייב לשלוף את כל הנתונים כאן בפנים (לא להסתמך על
            משתנים שחושבו פעם אחת מחוץ ל-fragment) כדי שכל הפעלה עצמאית שלו תביא
            ערכים טריים בפועל."""
            scanning_indices = cfg.get("indices") or ALL_INDICES
            _default_idx = ALL_INDICES.index(scanning_indices[0]) if scanning_indices[0] in ALL_INDICES else 0
            movers_index = st.selectbox("מדד לצפייה", ALL_INDICES,
                                         index=_default_idx, format_func=lambda i: INDEX_LABELS[i])
            if movers_index not in scanning_indices:
                st.caption(f"⚠ שים לב: {INDEX_LABELS[movers_index]} לא נמצא כרגע ברשימת המדדים שנסרקים להתראות (בסיידבר) - זו צפייה בלבד.")

            # movers_days נקרא כאן לפי הערך שנשמר ב-session_state, כי ה-widget עצמו
            # מוצג רק בהמשך הפונקציה (צמוד לעמודת "מצטבר" בטבלה, למטה) - הערך שממנו
            # נטען כבר מסונכרן מהריצה הקודמת (או ברירת המחדל 3 בריצה הראשונה).
            movers_days = st.session_state.get("movers_cumulative_days", 3)
            with st.spinner("טוען נתוני שוק..."):
                movers_df = get_all_changes(movers_index, movers_days)
            if movers_df.empty:
                st.warning("לא התקבלו נתונים - אין חיבור למקור הנתונים.")
            else:
                # "(3 ימים)" בכותרת המצטבר עלה יקר מדי ברוחב (96px טבעי) - הועבר לאייקון
                # ▾ עם טולטיפ בהובר/לחיצה (כמו בעמודת "סיווג ריבאונד" בטבלת ההתראות),
                # במקום להיות מוצג תמיד, כדי לפנות רוחב לעמודות המספריות (שינוי יומי/שער)
                # שחשוב שלא ייחתכו כי אלה מספרים ממשיים לא רק תווית.
                # title=... לבד (הובר בלבד) לא עובד במגע (טאבלט/מובייל) - אין hover.
                # onclick עם alert עובד בלחיצה/הקשה בכל מכשיר, בלי תלות ב-hover.
                _movers_tip_text = f"שינוי מצטבר ב-{movers_days} ימי המסחר האחרונים\\nכולל השינוי היומי"
                _movers_cumulative_label = (
                    f'מצטבר <span title="שינוי מצטבר ב-{movers_days} ימי המסחר האחרונים&#10;כולל השינוי היומי" '
                    f'onclick="alert(\'{_movers_tip_text}\')" '
                    f'style="cursor:help; color:rgba(49,51,63,0.6);">{_HELP_ICON_SVG}</span>'
                )

                def _render(sub_df: pd.DataFrame) -> None:
                    _render_movers_style_table(sub_df, cumulative_label=_movers_cumulative_label)

                up_df = movers_df[movers_df["שינוי יומי (%)"] >= 0].sort_values("שינוי יומי (%)", ascending=False)
                down_df = movers_df[movers_df["שינוי יומי (%)"] < 0].sort_values("שינוי יומי (%)")

                # תיוג טריות גלוי מעל הטבלה - כדי שיהיה ברור אם "שינוי יומי" הוא ממש
                # מסחר נוכחי (השוק פתוח והנתון מהיום) או שהוא נכון לסגירת יום מסחר
                # קודם (סוף שבוע, לפני הפתיחה, או שהמקור פשוט עוד לא התעדכן).
                _movers_rep_date = movers_df["last_close_date"].max()
                if _movers_rep_date == israel_today() and is_market_open(movers_index):
                    st.caption("🟢 מסחר נוכחי")
                elif pd.notna(_movers_rep_date):
                    _movers_stale = market_data.is_data_stale(_movers_rep_date, "")
                    _movers_warn = "⚠️ " if _movers_stale else ""
                    st.caption(f"{_movers_warn}נכון לסגירת מסחר ב-{_movers_rep_date.strftime('%d/%m/%Y')}")

                def _section_header(color: str, word_dir: str, count: int) -> None:
                    st.image(render_text_image(f"מניות {word_dir} ({count})", color, font_size=17))

                with st.container(key="movers_days_row"):
                    st.markdown(
                        """
                        <style>
                        div[class*="st-key-movers_days_row"] {
                            margin-top: -14px;
                        }
                        div[class*="st-key-movers_days_row"] div[data-testid="stHorizontalBlock"] {
                            gap: 6px !important; align-items: center !important;
                        }
                        div[class*="st-key-movers_days_row"] div[data-testid="stColumn"]:first-child {
                            width: fit-content !important; flex: 0 0 auto !important; min-width: 0 !important;
                        }
                        div[class*="st-key-movers_days_row"] div[data-testid="stColumn"]:nth-child(2) {
                            /* 130px = הרוחב הצר ביותר שנמצא בבדיקה אמפירית שעדיין מציג
                               כפתורי +/- (110px=0 כפתורים, 130px=2 - Streamlit לא מרנדר
                               אותם בכלל מתחת לזה, לא רק מסתיר ב-CSS). */
                            width: 130px !important; flex: 0 0 auto !important;
                        }
                        </style>
                        """,
                        unsafe_allow_html=True,
                    )
                    _days_label_col, _days_input_col, _ = st.columns([3, 1, 6])
                    with _days_label_col:
                        st.caption("📉 מספר ימים לשינוי מצטבר")
                    with _days_input_col:
                        movers_days = st.number_input(
                            "ימים לחישוב שינוי מצטבר", min_value=2, max_value=10, step=1,
                            value=3, key="movers_cumulative_days", label_visibility="collapsed",
                        )

                if st.button("🔄 רענן נתוני שוק"):
                    get_all_changes.clear()

                mc1, mc2 = st.columns(2, gap="medium")
                with mc1:
                    with st.container(border=True):
                        _section_header(NEG_COLOR, "בירידה", len(down_df))
                        _render(down_df)
                with mc2:
                    with st.container(border=True):
                        _section_header(POS_COLOR, "בעלייה", len(up_df))
                        _render(up_df)

            _wl_conn = store.get_conn(db_path(cfg))
            _wl_items = store.get_watchlist(_wl_conn)
            _wl_conn.close()

            with st.container(border=True):
                st.image(render_text_image(f"מניות במעקב ({len(_wl_items)})", ACCENT_COLOR, font_size=17))
                st.caption("עוקב אחרי ביצועי מניה מרגע ההוספה (מחיר \"קנייה\" היפותטי) - לא אחזקה אמיתית ולא התראה")

                if not _wl_items:
                    st.info("אין מניות במעקב עדיין.")
                else:
                    _wl_tickers = tuple({it["ticker"] for it in _wl_items})
                    _wl_daily_df = get_current_changes_for(_wl_tickers)
                    _wl_rows = []
                    for it in _wl_items:
                        _match = _wl_daily_df[_wl_daily_df["ticker"] == it["ticker"]]
                        if _match.empty:
                            continue
                        _r = _match.iloc[0]
                        _wl_current = get_current_price(it["ticker"])
                        if _wl_current is None:
                            _wl_current = _r["last_close"]
                        # ימי מסחר, לא ימי לוח (כמו "שינוי מצטבר" בשאר האפליקציה) - סופ"ש
                        # לא נספר. "יום 1" הוא יום ההוספה עצמו (אם הוא יום מסחר).
                        _wl_added_date = dt.datetime.fromisoformat(it["added_at"]).date()
                        _wl_today = israel_today()
                        _wl_days_held = sum(
                            1 for _wl_d in range((_wl_today - _wl_added_date).days + 1)
                            if (_wl_added_date + dt.timedelta(days=_wl_d)).weekday() not in (5, 6)
                        )
                        _wl_rows.append({
                            "id": it["id"],
                            "שם_וטיקר": f"{it['company_name']} ({it['ticker']})" if it["company_name"] else it["ticker"],
                            "שער קנייה": _price_text(it["entry_price"], it["index_name"]),
                            "שינוי יומי (%)": _r["pct_change"],
                            "תשואה (%)": (_wl_current / it["entry_price"] - 1) * 100.0,
                            "ימי מסחר": _wl_days_held,
                        })
                    _wl_col_ratios = [3, 1.3, 1.3, 1.3, 1.1, 0.6]
                    _wl_header_cols = st.columns(_wl_col_ratios)
                    for _wl_h_col, _wl_h_text in zip(
                        _wl_header_cols, ["מניה", "שער קנייה", "שינוי יומי", "תשואה", "ימי מסחר", ""],
                    ):
                        with _wl_h_col:
                            st.caption(f"**{_wl_h_text}**" if _wl_h_text else "")

                    for _wl_row in _wl_rows:
                        _wl_name_col, _wl_entry_col, _wl_daily_col, _wl_yield_col, _wl_days_col, _wl_del_col = (
                            st.columns(_wl_col_ratios)
                        )
                        with _wl_name_col:
                            st.write(_wl_row["שם_וטיקר"])
                        with _wl_entry_col:
                            st.write(_wl_row["שער קנייה"])
                        for _wl_val_col, _wl_val in (
                            (_wl_daily_col, _wl_row["שינוי יומי (%)"]),
                            (_wl_yield_col, _wl_row["תשואה (%)"]),
                        ):
                            with _wl_val_col:
                                if pd.isna(_wl_val):
                                    st.write("—")
                                else:
                                    _wl_color = POS_COLOR if _wl_val >= 0 else NEG_COLOR
                                    st.markdown(
                                        f'<span style="color:{_wl_color}; font-weight:600;">'
                                        f'{_signed_num(_wl_val, 1, "%")}</span>',
                                        unsafe_allow_html=True,
                                    )
                        with _wl_days_col:
                            st.write(f"{_wl_row['ימי מסחר']:02d}")
                        with _wl_del_col:
                            if st.button("🗑️", key=f"watchlist_remove_{_wl_row['id']}"):
                                _wl_remove_conn = store.get_conn(db_path(cfg))
                                store.remove_watchlist_item(_wl_remove_conn, _wl_row["id"])
                                _wl_remove_conn.close()
                                st.rerun()

                with st.expander("➕ הוספת מניה למעקב"):
                    _wl_add_index = st.selectbox(
                        "מדד", ALL_INDICES, format_func=lambda i: INDEX_LABELS[i], key="watchlist_add_index",
                    )
                    _wl_add_tickers = constituents.get_constituents(_wl_add_index)
                    _wl_add_name_map = (
                        constituents.get_il_name_map(_wl_add_index) if _wl_add_index.upper() in ("TA35", "TA125")
                        else constituents.get_us_name_map(_wl_add_index)
                    )
                    _wl_add_options = sorted(_wl_add_tickers, key=lambda t: _wl_add_name_map.get(t, t))
                    _wl_add_labels = {t: f"{_wl_add_name_map.get(t, t)} ({t})" for t in _wl_add_options}
                    _wl_add_chosen = st.selectbox(
                        "מניה", _wl_add_options, format_func=lambda t: _wl_add_labels[t], key="watchlist_add_ticker",
                    )
                    if st.button("➕ הוסף למעקב"):
                        _wl_entry_price = get_current_price(_wl_add_chosen)
                        if _wl_entry_price is None:
                            st.warning("לא הצלחתי לשלוף מחיר נוכחי כרגע - נסה שוב בעוד רגע.")
                        else:
                            _wl_add_conn = store.get_conn(db_path(cfg))
                            store.add_watchlist_item(
                                _wl_add_conn, _wl_add_chosen, _wl_add_name_map.get(_wl_add_chosen),
                                _wl_add_index, _wl_entry_price,
                            )
                            _wl_add_conn.close()
                            st.rerun()

        _render_movers_tab()

_tab_slot_today = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
with _tab_slot_today.container():
    if st.session_state.active_tab == "today":
        @st.fragment(run_every="60s")
        def _render_today_tab() -> None:
            """fragment עם run_every - טוען df מחדש (לא סומך על המשתנה החיצוני
            שנטען פעם אחת בטעינת העמוד) כדי שהתראה חדשה שנוספה ברקע תופיע כאן
            לבד תוך דקה, בלי ריענון ידני של כל הדף."""
            df = load_alerts(db_path(cfg))

            _pa_count_conn = store.get_conn(db_path(cfg))
            _pa_active_count = len(store.get_active_price_alerts(_pa_count_conn))
            _pa_count_conn.close()
            _pa_label = f"🔔 התראת מחיר ידנית ({_pa_active_count})" if _pa_active_count else "🔔 התראת מחיר ידנית"
            with st.expander(_pa_label):
                st.caption("קבלת התראה כשמניה מגיעה למחיר מסוים - בלי קשר לירידה חדה או לאחזקה קיימת")
                _pa_conn = store.get_conn(db_path(cfg))
                _active_price_alerts = store.get_active_price_alerts(_pa_conn)

                if _active_price_alerts:
                    for _a in _active_price_alerts:
                        _a_name = _a.get("company_name") or _a["ticker"]
                        _a_is_il = market_data._is_israeli_ticker(_a["ticker"])
                        _a_target_text = f"{_a['target_price']*100:,.0f}" if _a_is_il else f"${_a['target_price']:,.2f}"
                        _a_dir = "מעל" if _a["direction"] == "above" else "מתחת ל"
                        _a_col1, _a_col2 = st.columns([4, 1])
                        with _a_col1:
                            st.write(f"{_a_name} ({_a['ticker']}) - {_a_dir} {_a_target_text}")
                        with _a_col2:
                            if st.button("❌", key=f"cancel_price_alert_{_a['id']}"):
                                store.deactivate_price_alert(_pa_conn, _a["id"])
                                st.rerun()
                    st.divider()

                _pa_default_index = (cfg.get("indices") or ALL_INDICES)[0]
                _pa_index = st.selectbox(
                    "מדד", ALL_INDICES,
                    index=ALL_INDICES.index(_pa_default_index) if _pa_default_index in ALL_INDICES else 0,
                    format_func=lambda i: INDEX_LABELS[i], key="price_alert_index",
                )
                _pa_tickers = constituents.get_constituents(_pa_index)
                _pa_name_map = (
                    constituents.get_il_name_map(_pa_index) if _pa_index.upper() in ("TA35", "TA125")
                    else constituents.get_us_name_map(_pa_index)
                )
                _pa_options = sorted(_pa_tickers, key=lambda t: _pa_name_map.get(t, t))
                _pa_labels = {t: f"{_pa_name_map.get(t, t)} ({t})" for t in _pa_options}
                _pa_chosen = st.selectbox(
                    "מניה", _pa_options, format_func=lambda t: _pa_labels[t], key="price_alert_ticker",
                )
                _pa_is_il = market_data._is_israeli_ticker(_pa_chosen)
                _pa_daily_df = get_current_changes_for((_pa_chosen,))
                # "מחיר נוכחי" בטופס הזה = שער נעילה (מחיר הסגירה האחרון), לא מחיר
                # חי - החלטה מפורשת של המשתמש (26.8.2026): גם אם check_price_alerts
                # בפועל בודק מול מחיר חי, ה-% שמוזן כאן מתייחס לשער נעילה כבסיס.
                _pa_reference_price = _pa_daily_df.iloc[0]["last_close"] if not _pa_daily_df.empty else None
                _pa_unit_scale = 100.0 if _pa_is_il else 1.0

                # אם המניה הנבחרת השתנתה, מאפסים את שני השדות - אחרת ה-% הישן
                # (שחושב מול שער הנעילה של המניה הקודמת) יישאר מוצג בלי קשר
                # למחיר היעד שגם הוא כבר לא רלוונטי למניה החדשה.
                if st.session_state.get("_pa_last_ticker") != _pa_chosen:
                    st.session_state["_pa_last_ticker"] = _pa_chosen
                    st.session_state["price_alert_target"] = 0.0
                    st.session_state["price_alert_target_pct"] = 0.0

                def _pa_sync_pct_from_price() -> None:
                    if not _pa_reference_price:
                        return
                    price_actual = st.session_state.get("price_alert_target", 0.0) / _pa_unit_scale
                    if price_actual > 0:
                        st.session_state["price_alert_target_pct"] = round((price_actual / _pa_reference_price - 1) * 100.0, 2)

                def _pa_sync_price_from_pct() -> None:
                    if not _pa_reference_price:
                        return
                    pct = st.session_state.get("price_alert_target_pct", 0.0)
                    price_actual = _pa_reference_price * (1 + pct / 100.0)
                    st.session_state["price_alert_target"] = round(price_actual * _pa_unit_scale, 0 if _pa_is_il else 2)

                _pa_price_col, _pa_pct_col = st.columns(2)
                with _pa_price_col:
                    _pa_target_raw = st.number_input(
                        "מחיר יעד" + ("" if _pa_is_il else " ($)"), min_value=0.0,
                        format="%.2f", key="price_alert_target",
                        on_change=_pa_sync_pct_from_price,
                    )
                with _pa_pct_col:
                    st.number_input(
                        "שינוי (%)", step=0.5, format="%.2f",
                        key="price_alert_target_pct", on_change=_pa_sync_price_from_pct,
                        disabled=_pa_reference_price is None,
                    )

                _pa_live_price = get_current_price(_pa_chosen)
                _pa_prev_close = _pa_daily_df.iloc[0]["prev_close"] if not _pa_daily_df.empty else None
                _pa_live_change_pct = (
                    (_pa_live_price / _pa_prev_close - 1) * 100.0
                    if (_pa_live_price is not None and _pa_prev_close) else None
                )
                _pa_live_price_text = (
                    (f"{_pa_live_price*100:,.0f}" if _pa_is_il else f"${_pa_live_price:,.2f}")
                    if _pa_live_price is not None else "—"
                )
                _pa_live_change_text = (
                    _signed_num(_pa_live_change_pct, 1, "%") if _pa_live_change_pct is not None else "—"
                )
                _pa_current_info_col1, _pa_current_info_col2 = st.columns(2)
                with _pa_current_info_col1:
                    st.caption(f"שער נוכחי: {_pa_live_price_text}")
                with _pa_current_info_col2:
                    st.caption(f"שינוי נוכחי: {_pa_live_change_text}")

                _pa_target = (_pa_target_raw / 100.0) if _pa_is_il else _pa_target_raw
                # אין צורך לשאול "כיוון" - הוא נגזר אוטומטית מהשוואת היעד לשער הנעילה:
                # יעד מעל שער הנעילה = מחכים שתעלה אליו, מתחת = מחכים שתרד אליו.
                if _pa_reference_price is not None and _pa_target > 0:
                    _pa_dir_preview = "עולה מעל" if _pa_target >= _pa_reference_price else "יורדת מתחת ל"
                    st.caption(f"תישלח התראה כשהמניה {_pa_dir_preview} המחיר הזה.")
                if st.button("✅ הוסף התראה", key="price_alert_add_btn"):
                    if _pa_target <= 0:
                        st.warning("יש למלא מחיר יעד לפני ההוספה.")
                    elif _pa_reference_price is None:
                        st.warning("לא הצלחתי לשלוף שער נעילה כרגע - נסה שוב בעוד רגע.")
                    else:
                        _pa_direction = "above" if _pa_target >= _pa_reference_price else "below"
                        store.add_price_alert(
                            _pa_conn, _pa_chosen, _pa_name_map.get(_pa_chosen), _pa_index,
                            _pa_target, _pa_direction,
                        )
                        st.session_state.pop("price_alert_target", None)
                        st.session_state.pop("price_alert_target_pct", None)
                        st.rerun()
                _pa_conn.close()

            if df.empty:
                st.info("אין עדיין התראות שמורות. הרץ סריקה כדי להתחיל.")
            else:
                # תאריך היום בפועל, לא "התאריך המקסימלי שנרשם אי פעם". אם עוד
                # לא נרשמה התראה היום (למשל לפני פתיחת המסחר, או בסופ"ש) -
                # נופלים חזרה בגלוי ליום המסחר האחרון שכן יש בו נתונים, עם
                # תיוג ברור של התאריך (25.8.2026, בהחלטה משותפת עם המשתמש).
                # אבל רק עד 9:58 - שתי דקות לפני פתיחת המסחר בת"א (9:59/10:00) -
                # כי מהרגע הזה זה כבר "יום מסחר חדש שמתחיל", ולא הגיוני להמשיך
                # להציג את היום הקודם כאילו הוא עדיין רלוונטי.
                _today_iso = israel_today().isoformat()
                todays_alerts = df[df["scan_date"] == _today_iso]
                _is_fallback_day = todays_alerts.empty and israel_now().time() < dt.time(9, 58)
                if _is_fallback_day:
                    _last_scan_date = df["scan_date"].max()
                    todays_alerts = df[df["scan_date"] == _last_scan_date]

                _REBOUND_TIER_EMOJI = {"A": "🟢", "B": "🟡", "C": "🔴"}

                def _score_light(val) -> str:
                    if pd.isna(val):
                        return ""
                    if val >= 70:
                        return "🟢 "
                    if val >= 45:
                        return "🟡 "
                    return "🔴 "

                def _rebound_cell_text(v) -> str:
                    # v הוא האות בלבד ("B") - הציון המשוקלל עבר לכרטיס ההתראה,
                    # לא מוצג בטבלה יותר (25.8.2026, לסריקה נקייה יותר). רוצים
                    # ויזואלית (קריאה מימין לשמאל): עיגול בימין, אות משמאלו.
                    # <bdi> מזהה LTR (יש אות לטינית) ומיישר לימין - אז כדי
                    # שהעיגול יצא הכי ימני צריך לכתוב אותו אחרון בתוך ה-bdi.
                    if pd.isna(v):
                        return "—"
                    emoji = _REBOUND_TIER_EMOJI.get(v, "")
                    return f"<bdi>{v} {emoji}</bdi>"

                todays_display_src = todays_alerts.copy()
                for _price_col in ("entry_limit", "target_base", "stop_loss"):
                    todays_display_src[_price_col] = todays_display_src.apply(
                        lambda r, c=_price_col: _price_text(r[c], r.get("index_name")), axis=1,
                    )

                # שינוי נוכחי - נשלף בכל ריצה של הפרגמנט (run_every="60s") לרשימת
                # הטיקרים של היום בלבד, בנפרד מ"שינוי בזמן התראה" השמור שלא זז.
                _current_tickers = tuple(sorted(todays_alerts["ticker"].unique()))
                _current_changes_df = get_current_changes_for(_current_tickers)
                _current_changes_map = (
                    dict(zip(_current_changes_df["ticker"], _current_changes_df["pct_change"]))
                    if not _current_changes_df.empty else {}
                )
                todays_display_src["current_pct_change"] = todays_display_src["ticker"].map(_current_changes_map)

                alerts_display = todays_display_src.rename(columns={
                    "ticker": "טיקר", "company_name": "שם", "pct_change": "שינוי בזמן התראה",
                    "current_pct_change": "שינוי נוכחי",
                    "entry_limit": "לימיט כניסה", "target_base": "יעד מכירה", "stop_loss": "סטופ-לוס",
                    "overreaction_score": "תגובת יתר", "quality_score": "איכות פונדמנטלית",
                    "rebound_tier": "סיווג ריבאונד",
                })
                if "שם" not in alerts_display.columns:
                    alerts_display["שם"] = ""
                alerts_display["שם"] = alerts_display["שם"].fillna(alerts_display["טיקר"])
                alerts_display["טיקר"] = alerts_display["טיקר"].str.replace(".TA", "", regex=False)
                alerts_display = alerts_display[["שם", "טיקר", "שינוי בזמן התראה", "שינוי נוכחי",
                                                  "תגובת יתר", "איכות פונדמנטלית",
                                                  "סיווג ריבאונד", "לימיט כניסה", "יעד מכירה", "סטופ-לוס"]]
                _ow = round(analysis.REBOUND_OVERREACTION_WEIGHT * 100)
                _rebound_header_label = (
                    f'סיווג ריבאונד {_help_icon_span(f"משוקלל: {_ow}% תגובת יתר + {100 - _ow}% איכות פונדמנטלית")}'
                )
                if _is_fallback_day:
                    _fallback_date_text = dt.date.fromisoformat(_last_scan_date).strftime("%d.%m")
                    _today_header_text = f"{len(todays_alerts)} התראות מיום המסחר האחרון ({_fallback_date_text})"
                else:
                    _today_header_text = f"התראות היום ({len(todays_alerts)})"
                _no_new_alerts_yet = todays_alerts.empty and not _is_fallback_day
                _market_open_now = is_market_open("TA35") or is_market_open("NASDAQ100")
                with st.container(border=True):
                    if _no_new_alerts_yet and not _market_open_now:
                        st.info("השווקים סגורים - ההתראות יתחדשו עם פתיחת המסחר.")
                    elif _no_new_alerts_yet:
                        st.image(render_text_image(_today_header_text, POS_COLOR, font_size=17))
                        st.info("אין התראות חדשות במסחר הנוכחי.")
                    else:
                        st.image(render_text_image(_today_header_text, POS_COLOR, font_size=17))
                        st.markdown(
                            _html_table(
                                alerts_display,
                                [("שם", "שם"), ("טיקר", "טיקר"),
                                 ("שינוי בזמן התראה", "שינוי בזמן התראה"), ("שינוי נוכחי", "שינוי נוכחי"),
                                 ("תגובת יתר", "תגובת יתר"), ("איכות פונדמנטלית", "איכות פונדמנטלית"),
                                 ("סיווג ריבאונד", _rebound_header_label),
                                 ("לימיט כניסה", "לימיט כניסה"), ("יעד מכירה", "יעד מכירה"), ("סטופ-לוס", "סטופ-לוס")],
                                formatters={
                                    "שינוי בזמן התראה": lambda v: _signed_num(v, 1, "%"),
                                    "שינוי נוכחי": lambda v: _signed_num(v, 1, "%") if pd.notna(v) else "—",
                                    "תגובת יתר": lambda v: f"{_score_light(v)}{int(v)}" if pd.notna(v) else "—",
                                    "איכות פונדמנטלית": lambda v: f"{_score_light(v)}{int(v)}" if pd.notna(v) else "—",
                                    "סיווג ריבאונד": _rebound_cell_text,
                                },
                                truncate_columns={
                                    "שם": 140, "טיקר": 115, "שינוי בזמן התראה": 115, "שינוי נוכחי": 115,
                                    "תגובת יתר": 115, "איכות פונדמנטלית": 115,
                                    "סיווג ריבאונד": 115, "לימיט כניסה": 115, "יעד מכירה": 115, "סטופ-לוס": 115,
                                },
                                wrap_headers=False,
                                color_columns={"שינוי בזמן התראה", "שינוי נוכחי"},
                                max_height=min(35 * (len(todays_alerts) + 1) + 3, 2000),
                            ),
                            unsafe_allow_html=True,
                        )

                for _, r in todays_alerts.iterrows():
                    _expander_name = r.get("company_name") or r["ticker"]
                    try:
                        _scan_dt = dt.datetime.fromisoformat(r["scan_ts"])
                        _scan_ts_text = _scan_dt.strftime("%H:%M")
                    except Exception:
                        _scan_ts_text = r["scan_ts"]
                    _badge_tier = r.get("rebound_tier")
                    _badge = _REBOUND_TIER_EMOJI.get(_badge_tier, "⚪") if pd.notna(_badge_tier) else ""
                    # עיגול, שם, טיקר, שעה, אחוז - בדיוק בסדר הזה. האחוז עטוף
                    # ב-LRI/PDI לבדו (לא כל השורה) כדי שלא יתמזג ל-run אחד עם
                    # השעה שאחריו ויתחלף איתה ב-bidi (זה מה שקרה בניסיון קודם).
                    _pct_isolated = f"⁦{_signed_num(r['pct_change'], 1, '%')}⁩"
                    _title = f"{_expander_name} ({r['ticker']}) · {_scan_ts_text} · {_pct_isolated}"
                    if _badge:
                        _title = f"{_badge} {_title}"
                    with st.expander(_title):
                        sc1, sc2 = st.columns([3, 1])
                        with sc1:
                            st.markdown(render_reason_pill(r.get("reasons_json", "[]")), unsafe_allow_html=True)
                            st.caption(r["reason_text"])
                        with sc2:
                            sparkline_prices = get_sparkline_prices(r["ticker"])
                            svg = _sparkline_svg(sparkline_prices)
                            if svg:
                                st.markdown(svg, unsafe_allow_html=True)

                        _verdict_color = POS_COLOR if r["overreaction_score"] >= 70 else (ACCENT_COLOR if r["overreaction_score"] >= 45 else NEG_COLOR)
                        st.markdown(
                            f'<div style="font-size:0.9rem; margin-top:4px;">'
                            f'<b>הערכת תגובת יתר:</b> <span style="color:{_verdict_color}; font-weight:600;">'
                            f'{r["overreaction_verdict"]} (ציון {r["overreaction_score"]}/100)</span></div>',
                            unsafe_allow_html=True,
                        )

                        _rebound_labels = {"A": "🟢 A - סיכוי גבוה לריבאונד", "B": "🟡 B - סיכוי אפשרי", "C": "🔴 C - סיכוי נמוך"}
                        _rebound_text = _rebound_labels.get(r.get("rebound_tier"), "⚪ לא זמין (נסרק לפני העדכון)")
                        if pd.notna(r.get("rebound_tier")):
                            _rb_score = analysis.weighted_rebound_score(
                                r["overreaction_score"], r.get("quality_score") if pd.notna(r.get("quality_score")) else None,
                            )
                            _rebound_text += f" (ציון משוקלל: {round(_rb_score)}/100)"
                        _quality_tier = r.get("quality_tier")
                        _quality_labels = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}
                        _quality_text = (
                            f"{_quality_labels.get(_quality_tier, '')} ({int(r.get('quality_score'))}/100)"
                            if _quality_tier and _quality_tier != "unknown" and pd.notna(r.get("quality_score"))
                            else "⚪ לא ידוע (נתונים חסרים)"
                        )
                        st.markdown(
                            f'<div style="font-size:0.9rem; margin-top:2px;">'
                            f'<b>סיווג ריבאונד:</b> {_rebound_text} &nbsp;|&nbsp; '
                            f'<b>איכות פונדמנטלית:</b> {_quality_text}</div>',
                            unsafe_allow_html=True,
                        )
                        _raw_quality_flags = r.get("quality_flags_json")
                        _quality_flags = json.loads(_raw_quality_flags) if isinstance(_raw_quality_flags, str) else []
                        if _quality_flags:
                            st.caption("⚑ " + " · ".join(_quality_flags))

                        headlines = json.loads(r["headlines_json"] or "[]")
                        if headlines:
                            st.write("**חדשות:**")
                            for h in headlines:
                                link = h.get("link")
                                title = h.get("title")
                                src = h.get("source")
                                if link:
                                    st.markdown(f"- [{title}]({link}) ({src})")
                                else:
                                    st.markdown(f"- {title} ({src})")
                        else:
                            st.write("לא נמצאו חדשות רלוונטיות.")

                        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
                        entry_target_stop_html = "".join([
                            _stat_card("לימיט כניסה", _price_text(r["entry_limit"], r.get("index_name")), NEUTRAL_COLOR, NEUTRAL_BG),
                            _stat_card("יעד מכירה", _price_text(r["target_base"], r.get("index_name")), POS_COLOR, POS_BG),
                            _stat_card("סטופ-לוס", _price_text(r["stop_loss"], r.get("index_name")), NEG_COLOR, NEG_BG),
                        ])
                        st.markdown(f'<div style="display:flex; gap:10px; flex-wrap:wrap;">{entry_target_stop_html}</div>', unsafe_allow_html=True)

                        net = json.loads(r["net_result_json"] or "{}")
                        if net:
                            profit = net.get("profit_scenario", {})
                            loss = net.get("loss_scenario", {})
                            st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
                            st.markdown("**תמונת ברוטו/נטו**")
                            nc1, nc2 = st.columns(2)
                            with nc1:
                                st.caption("תרחיש רווח (יעד בסיס)")
                                _p_color = POS_COLOR if profit.get("net_pnl", 0) >= 0 else NEG_COLOR
                                st.markdown(
                                    f'<div style="font-size:0.85rem; opacity:0.8;">ברוטו: '
                                    f'{_signed_num(profit.get("gross_pnl", 0))} {profit.get("currency", "")} '
                                    f'({_signed_num(profit.get("gross_return_pct", 0), 1, "%")})</div>'
                                    f'<div style="font-size:1rem; font-weight:700; color:{_p_color};">נטו: '
                                    f'{_signed_num(profit.get("net_pnl", 0))} {profit.get("currency", "")} '
                                    f'({_signed_num(profit.get("net_return_pct", 0), 1, "%")})</div>',
                                    unsafe_allow_html=True,
                                )
                                st.caption(f"עמלות: {profit.get('total_commission', 0):.0f} | "
                                           f"מס: {profit.get('capital_gains_tax', 0):.0f} | "
                                           f"דמי ניהול: {profit.get('management_fee', 0):.0f}")
                            with nc2:
                                st.caption("תרחיש סטופ-לוס")
                                _l_color = POS_COLOR if loss.get("net_pnl", 0) >= 0 else NEG_COLOR
                                st.markdown(
                                    f'<div style="font-size:0.85rem; opacity:0.8;">ברוטו: '
                                    f'{_signed_num(loss.get("gross_pnl", 0))} {loss.get("currency", "")} '
                                    f'({_signed_num(loss.get("gross_return_pct", 0), 1, "%")})</div>'
                                    f'<div style="font-size:1rem; font-weight:700; color:{_l_color};">נטו: '
                                    f'{_signed_num(loss.get("net_pnl", 0))} {loss.get("currency", "")} '
                                    f'({_signed_num(loss.get("net_return_pct", 0), 1, "%")})</div>',
                                    unsafe_allow_html=True,
                                )

                        st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
                        st.caption("🔔 הודע לי שוב כששינוי יומי מגיע ל-")
                        _ra_id = r["id"]
                        _ra_is_il = market_data._is_israeli_ticker(r["ticker"])
                        _ra_unit_scale = 100.0 if _ra_is_il else 1.0
                        _ra_prev_close = r.get("prev_close")

                        def _ra_sync_pct_from_price(_id=_ra_id, _prev=_ra_prev_close, _scale=_ra_unit_scale) -> None:
                            if not _prev:
                                return
                            price_actual = st.session_state.get(f"re_alert_price_{_id}", 0.0) / _scale
                            if price_actual > 0:
                                st.session_state[f"re_alert_pct_{_id}"] = round((price_actual / _prev - 1) * 100.0, 2)

                        def _ra_sync_price_from_pct(_id=_ra_id, _prev=_ra_prev_close, _scale=_ra_unit_scale, _il=_ra_is_il) -> None:
                            if not _prev:
                                return
                            pct = st.session_state.get(f"re_alert_pct_{_id}", 0.0)
                            price_actual = _prev * (1 + pct / 100.0)
                            st.session_state[f"re_alert_price_{_id}"] = round(price_actual * _scale, 0 if _il else 2)

                        _ra_price_col, _ra_pct_col, _ra_btn_col = st.columns([2, 2, 1])
                        with _ra_price_col:
                            st.number_input(
                                "שער" + ("" if _ra_is_il else " ($)"), value=0.0, format="%.2f",
                                key=f"re_alert_price_{_ra_id}", on_change=_ra_sync_pct_from_price,
                                disabled=not _ra_prev_close,
                            )
                        with _ra_pct_col:
                            _ra_pct = st.number_input(
                                "שינוי יומי (%)", value=0.0, step=0.5, format="%.1f",
                                key=f"re_alert_pct_{_ra_id}", on_change=_ra_sync_price_from_pct,
                            )
                        with _ra_btn_col:
                            st.markdown("<div style='padding-top:28px;'></div>", unsafe_allow_html=True)
                            if st.button("✅ הוסף", key=f"re_alert_btn_{_ra_id}"):
                                if _ra_pct == 0:
                                    st.warning("יש למלא אחוז שונה מאפס.")
                                elif not _ra_prev_close:
                                    st.warning("אין מחיר בסיס שמור להתראה הזו - לא ניתן לחשב שינוי יומי.")
                                else:
                                    _ra_target = float(_ra_prev_close) * (1 + _ra_pct / 100.0)
                                    _ra_direction = "below" if _ra_pct < 0 else "above"
                                    _ra_conn = store.get_conn(db_path(cfg))
                                    store.add_price_alert(
                                        _ra_conn, r["ticker"], r.get("company_name"), r.get("index_name"),
                                        _ra_target, _ra_direction,
                                    )
                                    _ra_conn.close()
                                    st.success(
                                        f"תישלח התראה כש{r.get('company_name') or r['ticker']} "
                                        f"מגיעה לשינוי יומי של {_ra_pct:+.1f}%."
                                    )

            # "קרוב לסף התראה" - הועבר לכאן מטאב "מניות מובילות" (26.8.2026): קונספטואלית
            # זה צפי להתראה עתידית (מבוסס על סף ההתראה), לא עיון במניות כמו שאר הטאב ההוא.
            scanning_threshold = abs(cfg.get("drop_threshold_pct", 3.0))
            near_miss_frames = []
            for scanned_idx in (cfg.get("indices") or []):
                idx_df = get_all_changes(scanned_idx)
                if idx_df.empty:
                    continue
                # is_stale (מ-get_all_changes) חובה כאן: בלי הסינון הזה, מניה עם מקור
                # נתונים תקוע (למשל yf.download שמפגר יום-יומיים, ר' is_data_stale)
                # נכנסת ל"קרוב לסף" עם שינוי יומי שהוא בעצם שריד מלפני כמה ימים, לא
                # קרבה אמיתית להתראה עכשיו - בדיוק מה שהמשתמש תפס בפועל (27.8.2026,
                # NWMD.TA/TSEM.TA עם last_close_date מ-25.8 בזמן שהשוק פתוח ב-27.8).
                # last_close_date == היום ממש: בלי זה, בסופ"ש/לפני שהשוק נפתח הטבלה
                # ממשיכה להראות את שארית יום המסחר הקודם (לא "תקוע" מבחינת
                # is_data_stale - זה עדיין הסגירה האחרונה התקינה - אבל המשתמש רוצה
                # שהטבלה תתנהג כמו "התראות היום" ותתאפס, לא תישאר עם נתון מיום קודם).
                near_miss_frames.append(idx_df[
                    (idx_df["שינוי יומי (%)"] < -scanning_threshold * 0.8) &
                    (idx_df["שינוי יומי (%)"] >= -scanning_threshold) &
                    (~idx_df["is_stale"]) &
                    (idx_df["last_close_date"] == israel_today())
                ])
            near_miss_df = pd.concat(near_miss_frames).sort_values("שינוי יומי (%)") if near_miss_frames else pd.DataFrame()

            if not near_miss_df.empty:
                with st.container(border=True):
                    st.image(render_text_image(f"קרוב לסף התראה ({len(near_miss_df)})", NEAR_MISS_COLOR, font_size=17))
                    st.caption(f"מניות שמתקרבות לסף ההתראה ({scanning_threshold:.1f}%) אך עדיין לא חצו אותו - כדאי לשים לב")
                    _render_movers_style_table(near_miss_df, cumulative_label="שינוי מצטבר (3 ימים)")

        _render_today_tab()


_HEBREW_SOURCES = {"Globes", "Calcalist"}


@st.cache_data(ttl=300)
def get_footer_news(top_names_tickers: list, is_israeli: bool) -> dict:
    il_company_names = set(constituents.get_il_name_map("TA35").values()) \
        | set(constituents.get_il_name_map("TA125").values())
    general_all = news.get_general_market_news(limit=20, il_company_names=il_company_names)
    general = [h for h in general_all if h.get("source") in _HEBREW_SOURCES][:4]
    stock_news = {}
    for name, ticker in top_names_tickers:
        heads = news.get_recent_headlines(ticker, True, name)  # תמיד לחפש גם ב-Globes/Calcalist
        heads = [h for h in heads if h.get("source") in _HEBREW_SOURCES][:1]
        if heads:
            stock_news[name] = heads
    return {"general": general, "stock_news": stock_news}


@st.cache_data(ttl=3600)
def get_backtest_results(alerts_df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    result = backtest.run_backtest(alerts_df, window_days)
    if not result.empty and "id" in result.columns:
        decided = result[result["outcome"] != backtest.PENDING]
        if not decided.empty:
            conn = store.get_conn(db_path(cfg))
            try:
                store.update_outcomes(conn, list(zip(decided["id"], decided["outcome"])))
            finally:
                conn.close()
    return result


_BACKTEST_CAPTION = "ניתוח הצלחת התראות עבר ע\"פ מחירי שיא / שפל בפועל"


def _color_success_rate(val):
    if pd.isna(val):
        return ""
    color = POS_COLOR if val >= 50 else NEG_COLOR
    return f"color: {color}; font-weight: 600"


_tab_slot_backtest = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
with _tab_slot_backtest.container():
    if st.session_state.active_tab == "backtest":
        if df.empty:
            st.caption(_BACKTEST_CAPTION)
            st.info("אין עדיין התראות להערכה. הרץ סריקה כדי להתחיל לצבור נתונים.")
        else:
            with st.container(border=True):
                st.markdown(f"**🔍 {_BACKTEST_CAPTION}**")
                _backtest_scope = st.radio(
                    "היקף הבדיקה", ["כל ההתראות", "התראות שמומשו"], horizontal=True, key="backtest_scope",
                    label_visibility="collapsed",
                )
                st.markdown("⏱️ טווח ימי מסחר לבדיקה")
                window_days = st.slider(
                    # 30 = בדיוק התקרה הפנימית (MAX_WINDOW_DAYS ב-backtest.py) שאליה
                    # החלון גדל אוטומטית עבור יעדים גדולים - בלי זה, הסליידר לא
                    # מאפשר לבחור ערך שהמערכת בעצמה כבר יכולה להגיע אליו.
                    "טווח ימי מסחר לבדיקה", min_value=1, max_value=30, value=10, label_visibility="collapsed",
                )
            if st.button("🔄 הרץ בדיקה מחדש", key="backtest_rerun_btn"):
                get_backtest_results.clear()

            # התראות שהמשתמש קנה וסימן כ"עסקה ידנית" (לא לפי האסטרטגיה) לא נכללות -
            # הטאב הזה בודק את דיוק ההתראות/האסטרטגיה עצמה, לא את ההחלטות האישיות של המשתמש.
            _strategy_df = df[df.get("is_manual_trade") != 1] if "is_manual_trade" in df.columns else df

            if _backtest_scope == "התראות שמומשו":
                # "מומשו" = כל אחזקה שהפכה לעסקה אמיתית - גם פתוחה עדיין (נבדקת
                # בסימולציה כמו כל התראה) וגם כזו שכבר נסגרה (שם כבר יודעים בוודאות
                # את התוצאה האמיתית מהיציאה בפועל - לא מסמלצים שום דבר).
                _open_df = _strategy_df[_strategy_df.get("bought") == 1] if "bought" in _strategy_df.columns else _strategy_df.iloc[0:0]
                with st.spinner("בודק נתוני מחיר היסטוריים לכל אחזקה..."):
                    _bt_open = get_backtest_results(_open_df, window_days)
                _closed_conn = store.get_conn(db_path(cfg))
                _bt_closed = backtest.closed_trades_as_outcomes(_closed_conn)
                _closed_conn.close()
                bt = pd.concat([_bt_open, _bt_closed], ignore_index=True) if not _bt_closed.empty else _bt_open
            else:
                with st.spinner("בודק נתוני מחיר היסטוריים לכל התראה..."):
                    bt = get_backtest_results(_strategy_df, window_days)

            summary = backtest.overall_summary(bt)
            win_rate_text = f"{summary['win_rate_pct']:.0f}%" if summary["win_rate_pct"] is not None else "עדיין אין מספיק נתונים"
            if summary["win_rate_pct"] is None:
                win_rate_color, win_rate_bg = NEUTRAL_COLOR, NEUTRAL_BG
            else:
                win_rate_color = POS_COLOR if summary["win_rate_pct"] >= 50 else NEG_COLOR
                win_rate_bg = POS_BG if summary["win_rate_pct"] >= 50 else NEG_BG

            backtest_cards = "".join([
                _stat_card("🗂️ התראות שנבדקו", str(summary["total_alerts"]), NEUTRAL_COLOR, NEUTRAL_BG),
                _stat_card("✅ הגי" "‌" "עו לי" "‌" "עד", str(summary["hit_target"]), POS_COLOR, POS_BG),
                _stat_card("❌ פגעו בסטופ", str(summary["hit_stop"]), NEG_COLOR, NEG_BG),
                _stat_card("➖ נשארו באמצע", str(summary["neither"]), NEUTRAL_COLOR, NEUTRAL_BG),
                _stat_card("⏳ בהמתנה", str(summary["pending"]), NEUTRAL_COLOR, NEUTRAL_BG),
                _stat_card("📊 שיעור הצלחה", win_rate_text, win_rate_color, win_rate_bg),
            ])
            st.markdown(f'<div style="display:flex; gap:10px; flex-wrap:wrap;">{backtest_cards}</div>', unsafe_allow_html=True)
            st.markdown("<div style='height:22px;'></div>", unsafe_allow_html=True)

            def _primary_reason(reasons_json: str) -> str:
                try:
                    reasons = json.loads(reasons_json or "[]")
                    return analysis_mod_labels.get(reasons[0], reasons[0]) if reasons else "לא ידוע"
                except Exception:
                    return "לא ידוע"

            analysis_mod_labels = {
                "market_wide": "יום חלש בשוק",
                "sector_pressure": "לחץ סקטוריאלי",
                "earnings_reaction": "תגובה לדוח",
                "profit_taking": "מימושים אחרי עלייה",
                "stock_specific_news": "חדשות ספציפיות",
                "ex_dividend": "ניתוק דיבידנד (טכני)",
                "unclear": "לא נמצאה סיבה ברורה",
            }

            def _score_bucket(score) -> str:
                if pd.isna(score):
                    return "לא ידוע"
                score = int(score)
                if score >= 80:
                    return "80-100"
                if score >= 60:
                    return "60-79"
                if score >= 40:
                    return "40-59"
                if score >= 20:
                    return "20-39"
                return "0-19"

            bt_display = bt.copy()
            bt_display["סיבה"] = bt_display["reasons_json"].apply(_primary_reason)
            bt_display["ציון תגובת-יתר"] = bt_display["overreaction_score"].apply(_score_bucket)

            by_reason = backtest.summarize_by(bt_display, "סיבה")
            by_score = backtest.summarize_by(bt_display, "ציון תגובת-יתר")

            _success_rate_color = lambda v: POS_COLOR if v >= 50 else NEG_COLOR

            def _section_subheader(text: str, icon: str) -> None:
                st.markdown(
                    f'<div style="font-size:1.05rem; font-weight:700; margin-bottom:10px; padding-bottom:6px; '
                    f'border-bottom:2px solid {ACCENT_COLOR}55;">{icon} {text}</div>',
                    unsafe_allow_html=True,
                )

            rc1, rc2 = st.columns(2)
            with rc1:
                _section_subheader("שיעור הצלחה לפי סיבת הירידה", "📌")
                if by_reason.empty:
                    st.caption("אין עדיין מספיק התראות מוכרעות.")
                else:
                    st.markdown(
                        _html_table(
                            by_reason, [("סיבה", "סיבה"), ('סה"כ', 'סה"כ'), ("הגיעו ליעד", "הגיעו ליעד"),
                                        ("שיעור הצלחה (%)", "שיעור הצלחה (%)")],
                            formatters={"שיעור הצלחה (%)": lambda v: f"{v:.1f}"},
                            color_fns={"שיעור הצלחה (%)": _success_rate_color},
                        ),
                        unsafe_allow_html=True,
                    )
            with rc2:
                _section_subheader("שיעור הצלחה לפי ציון תגובת-יתר", "🎯")
                if by_score.empty:
                    st.caption("אין עדיין מספיק התראות מוכרעות.")
                else:
                    st.markdown(
                        _html_table(
                            by_score, [("ציון תגובת-יתר", "ציון תגובת-יתר"), ('סה"כ', 'סה"כ'),
                                       ("הגיעו ליעד", "הגיעו ליעד"), ("שיעור הצלחה (%)", "שיעור הצלחה (%)")],
                            formatters={"שיעור הצלחה (%)": lambda v: f"{v:.1f}"},
                            color_fns={"שיעור הצלחה (%)": _success_rate_color},
                        ),
                        unsafe_allow_html=True,
                    )

            with st.expander("📋 כל ההתראות עם תוצאה"):
                bt_table = bt_display[["scan_ts", "ticker", "pct_change", "target_base", "stop_loss", "outcome"]].copy()
                bt_table["outcome"] = bt_table["outcome"].map(backtest.OUTCOME_LABELS_HE)
                bt_table = bt_table.rename(columns={
                    "scan_ts": "זמן סריקה", "ticker": "טיקר", "pct_change": "שינוי (%)",
                    "target_base": "יעד", "stop_loss": "סטופ", "outcome": "תוצאה",
                })
                st.markdown(
                    _html_table(
                        bt_table,
                        [("טיקר", "טיקר"), ("זמן סריקה", "זמן סריקה"), ("שינוי (%)", "שינוי (%)"),
                         ("יעד", "יעד"), ("סטופ", "סטופ"), ("תוצאה", "תוצאה")],
                        formatters={
                            "שינוי (%)": lambda v: _signed_num(v, 1, "%") if pd.notna(v) else "—",
                            "יעד": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                            "סטופ": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                        },
                        color_columns={"שינוי (%)"}, color_fns={"תוצאה": _outcome_color_hex},
                        max_height=600,
                    ),
                    unsafe_allow_html=True,
                )

_tab_slot_portfolio = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
with _tab_slot_portfolio.container():
    if st.session_state.active_tab == "portfolio":
        @st.fragment(run_every="60s")
        def _render_holdings_tab() -> None:
            """fragment עם run_every - כל האזור (טופס פתיחת פוזיציה, כרטיסי
            האחזקות, כפתורי מכירה) מתעדכן לבד כל דקה בלי ריענון ידני - מחירים
            נשלפים מחדש בכל הפעלה עצמאית שלו. df נטען כאן מחדש (מסתיר את המשתנה
            החיצוני שנטען פעם אחת בטעינת העמוד) - אחרת התראה/אחזקה חדשה שנוספה
            ברקע לא הייתה מופיעה כאן בלי ריענון ידני של כל הדף."""
            df = load_alerts(db_path(cfg))

            def _render_open_position_expander() -> None:
                with st.expander("➕ פתיחת פוזיציה", key="open_position_expander"):
                    if df.empty:
                        st.caption("אין עדיין התראות להוסיף מהן אחזקה.")
                    else:
                        available_indices = sorted(df["index_name"].dropna().unique().tolist())
                        index_filter = st.selectbox(
                            "סנן לפי מדד", ["הכל"] + [INDEX_LABELS.get(i, i) for i in available_indices],
                            key="portfolio_index_filter",
                        )
                        filtered_df = df.copy()
                        if index_filter != "הכל":
                            selected_index_code = next(
                                (i for i in available_indices if INDEX_LABELS.get(i, i) == index_filter), None
                            )
                            filtered_df = filtered_df[filtered_df["index_name"] == selected_index_code]

                        # רק ההתראה האחרונה לכל מניה - מקצר את הרשימה משמעותית וקל יותר לחפש/להקליד
                        stock_options = filtered_df.sort_values("scan_ts", ascending=False).drop_duplicates(subset=["ticker"]).copy()
                        stock_options["display_name"] = stock_options.apply(lambda r: r["company_name"] or r["ticker"], axis=1)
                        stock_options = stock_options.sort_values("display_name")
                        stock_options["label"] = stock_options.apply(lambda r: f"{r['display_name']} ({r['ticker']})", axis=1)

                        if stock_options.empty:
                            st.caption("אין מניות במדד שנבחר.")
                        else:
                            chosen_label = st.selectbox(
                                "בחר מניה", stock_options["label"], key="portfolio_stock_select"
                            )
                            chosen_row = stock_options[stock_options["label"] == chosen_label].iloc[0]
                            is_il = market_data._is_israeli_ticker(chosen_row["ticker"])
                            add_trade_date = st.date_input(
                                "תאריך ביצוע העסקה", value=dt.date.today(), key="portfolio_add_trade_date",
                                format="DD/MM/YYYY",
                                help="אם לא הזנת את האחזקה באותו יום שקנית בפועל - כדי שספירת ימי ההחזקה תהיה נכונה.",
                            )
                            ac1, ac2, ac3 = st.columns(3)
                            # שדות ריקים בכוונה (לא ממולאים משער הלימיט המוצע) - כדי שתמיד תזין
                            # את המחיר/הכמות האמיתיים שביצעת, ולא תישאר בטעות עם ערך משער אחר.
                            add_entry_raw = ac1.number_input(
                                "שער ביצוע", min_value=0.0, value=0.0, format="%.0f" if is_il else "%.2f",
                                key="portfolio_add_entry",
                            )
                            add_entry = (add_entry_raw / 100.0) if is_il else add_entry_raw
                            add_qty = ac2.number_input("כמות", min_value=0.0, value=0.0, step=1.0, key="portfolio_add_qty")
                            add_amount = ac3.number_input(
                                "עלות (אופציונלי)", min_value=0.0, value=0.0, step=100.0, key="portfolio_add_amount",
                                help="אם תמלא עלות כוללת, הכמות תחושב אוטומטית ממנה (עלות ÷ שער ביצוע) "
                                     "במקום השדה 'כמות'.",
                            )
                            add_is_manual = st.checkbox(
                                "🖐️ עסקה ידנית (לא לפי האסטרטגיה - לא תיכלל בסטטיסטיקת ביצועי האסטרטגיה)",
                                key="portfolio_add_manual",
                            )
                            if st.button("✅ הוסף לאחזקות", key="portfolio_add_btn"):
                                final_qty = (add_amount / add_entry) if (add_amount > 0 and add_entry > 0) else add_qty
                                if add_entry <= 0 or final_qty <= 0:
                                    st.warning("יש למלא שער ביצוע וכמות (או עלות) לפני ההוספה.")
                                else:
                                    bought_at = dt.datetime.combine(add_trade_date, dt.datetime.now().time()).isoformat(timespec="seconds")
                                    add_stop_price = get_holding_stop_price(chosen_row["ticker"], add_entry)
                                    cloud_sync.refresh_alerts_db_if_clean()
                                    add_conn = store.get_conn(db_path(cfg))
                                    store.mark_as_bought(
                                        add_conn, int(chosen_row["id"]), add_entry, final_qty, bought_at, add_stop_price,
                                        is_manual_trade=add_is_manual,
                                    )
                                    add_conn.close()
                                    _sync_and_warn("position opened", include_db=True)
                                    for _clear_key in ("portfolio_add_entry", "portfolio_add_qty", "portfolio_add_amount", "portfolio_add_manual"):
                                        st.session_state.pop(_clear_key, None)
                                    load_alerts.clear()
                                    st.rerun()

            gain_start_pct = cfg.get("holdings_gain_alert_start_pct", 2.0)
            gain_step_pct = cfg.get("holdings_gain_alert_step_pct", 1.0) or 1.0

            def _next_gain_alert_pct(gain_pct: float | None) -> float:
                if gain_pct is None or gain_pct < gain_start_pct:
                    return gain_start_pct
                level = int((gain_pct - gain_start_pct) // gain_step_pct)
                return gain_start_pct + (level + 1) * gain_step_pct

            def render_holding_card(row: dict) -> None:
                ccy_symbol = CURRENCY_SYMBOLS.get(row["ccy"], row["ccy"])
                current, pnl, pnl_pct, net_pnl = row["current"], row["pnl"], row["pnl_pct"], row["net_pnl"]
                if current is None or net_pnl is None:
                    color, bg, pnl_text = CLOSED_COLOR, CLOSED_BG, "אין נתון מחיר עדכני"
                else:
                    color = POS_COLOR if net_pnl >= 0 else NEG_COLOR
                    bg = POS_BG if net_pnl >= 0 else NEG_BG
                    arrow = "▲" if net_pnl >= 0 else "▼"
                    pnl_text = (
                        f"{arrow} {_signed_num(pnl)} {ccy_symbol} ({_signed_num(pnl_pct, 1, '%')})  |  "
                        f"נטו: {_signed_num(net_pnl)} {ccy_symbol}"
                    )

                svg = _sparkline_svg(row["prices"], width=90, height=32) if row["prices"] else ""

                is_il = market_data._is_israeli_ticker(row["ticker"])
                # שערים (לא סכומי כסף כוללים) למניות ת"א מוצגים באגורות - כמו ב-TASE
                # ובהודעת הטלגרם - כדי שאפשר יהיה להשוות ישירות למסך הברוקר
                if is_il:
                    entry_price_text = f"{row['entry']*100:,.0f}"
                    current_price_text = f"{current*100:,.0f}" if current is not None else "—"
                else:
                    entry_price_text = f"{row['entry']:,.2f}"
                    current_price_text = f"{current:,.2f}" if current is not None else "—"

                _daily_pct = row.get("daily_pct")
                if _daily_pct is not None and pd.notna(_daily_pct):
                    _daily_color = POS_COLOR if _daily_pct >= 0 else NEG_COLOR
                    _daily_icon = "📈" if _daily_pct >= 0 else "📉"
                    daily_badge_html = (
                        f'<div style="font-size:1rem; font-weight:700; color:{_daily_color}; '
                        f'display:flex; align-items:center; gap:4px;">'
                        f'{_daily_icon} {_signed_num(_daily_pct, 1, "%")}'
                        f'<span style="font-size:0.7rem; font-weight:500; opacity:0.7;">שינוי יומי</span></div>'
                    )
                else:
                    daily_badge_html = ""

                # סטטוס סטופ-לוס חי - אותו חישוב בדיוק כמו ב-scanner._check_stop_proximity,
                # כדי שמה שרואים בדשבורד יהיה עקבי עם התראת הטלגרם, לא רק תלוי אם היא נשלחה בפועל.
                # יש תו ברוחב אפס (ZWNJ) בתוך "סטופ" - בלתי נראה לעין, אבל שובר זיהוי תבנית של
                # כלי חיצוני שנראה שמתקן/מחליף את המילה השאולה הזו שוב ושוב (כבר קרה פעמיים).
                _STOPLOSS_LABEL = "ס‌טופ-לוס"
                stop_price = row.get("holding_stop_price") or (row["entry"] * STOP_LOSS_FACTOR)
                stop_price_text = f"{stop_price*100:,.0f}" if is_il else f"{stop_price:,.2f}"
                target_price = live_target_price(row["entry"], stop_price, row.get("forecast_target"))
                target_price_text = f"{target_price*100:,.0f}" if is_il else f"{target_price:,.2f}"

                if current is None:
                    target_part, stop_part = "", ""
                else:
                    distance_pct = (current - stop_price) / stop_price * 100
                    stop_is_warning = current <= stop_price or distance_pct <= cfg.get("holdings_stop_warn_pct", STOP_WARN_PCT)
                    if current <= stop_price:
                        stop_part = (
                            f'<span style="font-weight:700; color:{NEG_COLOR};">'
                            f'🛑 חצתה סטופ-לוס ב-{abs(distance_pct):.1f}%</span>'
                        )
                    elif stop_is_warning:
                        stop_part = f'<span style="font-weight:700; color:{NEG_COLOR};">⚠️ קרובה לסטופ {distance_pct:.1f}%</span>'
                    else:
                        stop_part = f'<span style="opacity:0.7;">{_STOPLOSS_LABEL}: {stop_price_text}</span>'

                    target_distance_pct = (target_price - current) / target_price * 100
                    target_is_warning = (
                        current >= target_price
                        or target_distance_pct <= cfg.get("holdings_target_warn_pct", TARGET_WARN_PCT)
                    )
                    if current >= target_price:
                        target_part = (
                            f'<span style="font-weight:700; color:{POS_COLOR};">'
                            f'🎯 עברה את היעד ב-{abs(target_distance_pct):.1f}%</span>'
                        )
                    elif target_is_warning:
                        target_part = f'<span style="font-weight:700; color:{POS_COLOR};">🎯 קרובה ליעד {target_distance_pct:.1f}%</span>'
                    else:
                        target_part = f'<span style="opacity:0.7;">יעד: {target_price_text}</span>'

                    # כשצד אחד באזהרה (קרוב/חצה) והשני לא - מציגים רק את האזהרה,
                    # לא את שני הצדדים יחד, כדי לא להטביע את המידע הקריטי בטקסט
                    # שגרתי ("יעד: X") לידו. אם שניהם באזהרה בו-זמנית (נדיר) - שניהם נשארים.
                    if stop_is_warning and not target_is_warning:
                        target_part = ""
                    elif target_is_warning and not stop_is_warning:
                        stop_part = ""

                card_html = f"""
                    <div style="border-radius:10px; padding:10px 14px; background:{bg}; margin:-14px -14px 8px -14px;
                                border-bottom:1px solid {color}44;">
                      <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
                        <div style="font-size:1.05rem; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                          {row['name']} <span style="opacity:0.55; font-weight:500; font-size:0.9rem;">({row['ticker']})</span>
                          {'<span style="font-size:0.75rem; font-weight:600; opacity:0.75; margin-right:6px;">🖐️ ידנית</span>' if row.get('is_manual_trade') else ''}
                        </div>
                        {daily_badge_html}
                      </div>
                      <div style="display:flex; align-items:center; gap:8px; margin-top:6px;">
                        {svg}
                        <div style="font-size:1.1rem; font-weight:700; color:{color};">{pnl_text}</div>
                      </div>
                      <div style="font-size:0.8rem; opacity:0.75; margin-top:6px; display:flex; gap:12px; flex-wrap:wrap;">
                        <span>ע‌לות: {row['invested']:,.0f} {ccy_symbol}</span>
                        <span>ביצוע: {entry_price_text}</span>
                        <span>נ‌וכחי: {current_price_text}</span>
                        <span>כמות: {row['qty']:,.0f}</span>
                      </div>
                      <div style="font-size:0.8rem; opacity:0.75; margin-top:4px; display:flex; gap:12px; flex-wrap:wrap; align-items:center;">
                        <span>{row.get('portfolio_pct', 0):.0f}% מהתיק</span>
                        <span style="display:inline-flex; align-items:center; gap:4px;"><span style="display:inline-block; width:6px; height:6px;
                              border-radius:50%; background:{row.get("sector_color", NEUTRAL_COLOR)}; flex-shrink:0; margin-top:-2px;"></span>{_SECTOR_LABELS_HE.get(row["sector"], row["sector"])}</span>
                        <span>מוחזק {row['days_held']} ימים</span>
                        <span style="display:inline-flex; gap:12px; flex-wrap:nowrap;">{target_part}{stop_part}</span>
                      </div>
                    </div>
                """
                card_html = " ".join(line.strip() for line in card_html.strip().split("\n"))

                with st.container(border=True):
                    st.markdown(card_html, unsafe_allow_html=True)
                    # אותו צבע בדיוק כמו הכרטיס עצמו (ירוק/אדום לפי רווח/הפסד, אותם
                    # color/bg שכבר חושבו למעלה) - לא אדום קבוע כמו שהיה, שלא שיקף
                    # מצב אחזקה ברווח.
                    _sell_r, _sell_g, _sell_b = (int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
                    # הסלקטור חייב לכלול את row['id'] - בלי זה, "st-key-sell_holding_"
                    # (סוביסטרינג) תפס את הכפתורים של *כל* האחזקות, לא רק של השורה
                    # הזו, ומאחר ש-<style> תגי מוזרקים גלובליים לעמוד, ה-CSS של
                    # האחזקה האחרונה בלולאה "ניצח" וצבע את כל הכפתורים באותו צבע.
                    st.markdown(
                        f"""
                        <style>
                        div[class*="st-key-sell_holding_{row['id']}"] button {{
                            background-color: rgba({_sell_r}, {_sell_g}, {_sell_b}, 0.08); color: {color};
                            border: 1px solid rgba({_sell_r}, {_sell_g}, {_sell_b}, 0.35); border-radius: 8px;
                            font-weight: 500;
                        }}
                        div[class*="st-key-sell_holding_{row['id']}"] button:hover {{
                            background-color: rgba({_sell_r}, {_sell_g}, {_sell_b}, 0.16); color: {color};
                            border: 1px solid rgba({_sell_r}, {_sell_g}, {_sell_b}, 0.5);
                        }}
                        </style>
                        """,
                        unsafe_allow_html=True,
                    )
                    sell_key = f"confirm_sell_{row['id']}"
                    if not st.session_state.get(sell_key):
                        _, btn_col, _ = st.columns([1, 2, 1])
                        with btn_col:
                            if st.button("💰 מכירה - סגירת פוזיציה", key=f"sell_holding_{row['id']}", use_container_width=True):
                                st.session_state[sell_key] = True
                                st.rerun()
                    else:
                        is_il = market_data._is_israeli_ticker(row["ticker"])
                        st.markdown("**אישור מכירה**")
                        ec1, ec2 = st.columns(2)
                        default_exit = (row["current"] if row["current"] is not None else row["entry"]) or 0.0
                        default_exit = default_exit * (100.0 if is_il else 1.0)
                        exit_price_raw = ec1.number_input(
                            "שער מכירה", min_value=0.0, value=float(default_exit),
                            # step חייב להיות מפורש: ברירת המחדל של Streamlit היא 0.01, בזמן
                            # שהתצוגה באגורות (IL) מעוגלת ל-0 ספרות (format="%.0f") - בלי step
                            # מתאים, +/- שינו את הערך ב-0.01 בכל לחיצה, שינוי בלתי-נראה
                            # לגמרי בתצוגה המעוגלת (נראה כאילו הכפתורים "לא עובדים").
                            step=1.0 if is_il else 0.01,
                            format="%.0f" if is_il else "%.2f", key=f"exit_price_{row['id']}",
                        )
                        exit_price = (exit_price_raw / 100.0) if is_il else exit_price_raw
                        exit_date = ec2.date_input(
                            "תאריך מכירה", value=dt.date.today(), key=f"exit_date_{row['id']}", format="DD/MM/YYYY",
                        )
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            if st.button("✅ אישור מכירה", key=f"confirm_sell_btn_{row['id']}", use_container_width=True):
                                exit_at = dt.datetime.combine(exit_date, dt.datetime.now().time()).isoformat(timespec="seconds")
                                entry_at = row["bought_at"]
                                try:
                                    entry_date_only = dt.datetime.fromisoformat(entry_at).date() if entry_at else exit_date
                                except Exception:
                                    entry_date_only = exit_date
                                holding_days = max((exit_date - entry_date_only).days, 0) + 1
                                net = fees.compute_net_result(
                                    country_code=row["country_code"], buy_price=row["entry"], sell_price=exit_price,
                                    position_size_ccy=row["entry"] * row["qty"], holding_days=holding_days,
                                    fees_cfg=cfg["fees"],
                                )
                                cloud_sync.refresh_alerts_db_if_clean()
                                close_conn = store.get_conn(db_path(cfg))
                                store.save_closed_trade(close_conn, {
                                    "alert_id": row["id"], "ticker": row["ticker"], "company_name": row["name"],
                                    "index_name": row["index_name"], "currency": row["ccy"],
                                    "entry_price": row["entry"], "qty": row["qty"], "entry_at": entry_at,
                                    "exit_price": exit_price, "exit_at": exit_at,
                                    "forecast_entry_limit": row["forecast_entry_limit"],
                                    "forecast_target": row["forecast_target"], "forecast_stop": row["forecast_stop"],
                                    "forecast_score": row["forecast_score"], "forecast_verdict": row["forecast_verdict"],
                                    "holding_days": holding_days, "gross_pnl": net.gross_pnl, "net_pnl": net.net_pnl,
                                    "net_pct": net.net_return_pct, "is_manual_trade": row.get("is_manual_trade", False),
                                })
                                store.unmark_as_bought(close_conn, row["id"])
                                close_conn.close()
                                _sync_and_warn("position closed", include_db=True)
                                st.session_state.pop(sell_key, None)
                                load_alerts.clear()
                                st.rerun()
                        with cc2:
                            if st.button("❌ ביטול", key=f"cancel_sell_btn_{row['id']}", use_container_width=True):
                                st.session_state.pop(sell_key, None)
                                st.rerun()

            holdings = df[df.get("bought") == 1].copy() if (not df.empty and "bought" in df.columns) else pd.DataFrame()
            if holdings.empty:
                _render_open_position_expander()
                st.divider()
                st.info("אין עדיין אחזקות. השתמש ב'פתיחת פוזיציה' למעלה.")
            else:
                _daily_data_map = {}
                _daily_df2 = market_data.fetch_universe_daily_changes(holdings["ticker"].tolist())
                for _, _dr in _daily_df2.iterrows():
                    _daily_data_map[_dr["ticker"]] = _dr

                rows = []
                for _, r in holdings.iterrows():
                    prices = get_sparkline_prices(r["ticker"])
                    current = get_current_price(r["ticker"])
                    if current is None:
                        current = prices[-1] if prices else None
                    entry = r["actual_entry_price"]
                    qty = r["actual_qty"]
                    pnl = (current - entry) * qty if (current is not None and entry) else None
                    pnl_pct = (current / entry - 1) * 100 if (current is not None and entry) else None
                    ccy = constituents.INDEX_CURRENCY.get(r.get("index_name"), "ILS")
                    country_code = constituents.INDEX_COUNTRY_CODE.get(r.get("index_name"), "IL")

                    days_held = 1
                    bought_date = None
                    if r.get("bought_at"):
                        try:
                            bought_dt = dt.datetime.fromisoformat(r["bought_at"])
                            bought_date = bought_dt.date()
                            days_held = max((dt.date.today() - bought_date).days, 0) + 1
                        except Exception:
                            pass

                    # "שינוי יומי" בכרטיס אחזקה בודדת - אותה בעיה שכבר תוקנה בכרטיס
                    # המצטבר "💼 התיק שלי": אם נקנתה היום (אחרי prev_close), ההשוואה
                    # מול prev_close (הסגירה של אתמול) לא רלוונטית למי שהחזיק אותה רק
                    # מהקנייה - הבסיס הנכון הוא שער הכניסה, לא סגירת אתמול.
                    daily_pct = None
                    _dr = _daily_data_map.get(r["ticker"])
                    if current is not None and _dr is not None:
                        _prev_close, _prev_close_date = _dr.get("prev_close"), _dr.get("prev_close_date")
                        _baseline = _prev_close
                        if bought_date and _prev_close_date and bought_date >= _prev_close_date and entry:
                            _baseline = entry
                        if _baseline:
                            daily_pct = (current - _baseline) / _baseline * 100

                    net_pnl, net_pct = None, None
                    if current is not None and entry:
                        net = fees.compute_net_result(
                            country_code=country_code, buy_price=entry, sell_price=current,
                            position_size_ccy=entry * qty, holding_days=max(days_held, 1), fees_cfg=cfg["fees"],
                        )
                        net_pnl, net_pct = net.net_pnl, net.net_return_pct

                    rows.append({
                        "id": int(r["id"]), "name": r.get("company_name") or r["ticker"], "ticker": r["ticker"],
                        "entry": entry, "qty": qty, "current": current, "pnl": pnl, "pnl_pct": pnl_pct, "ccy": ccy,
                        "country_code": country_code, "index_name": r.get("index_name"), "bought_at": r.get("bought_at"),
                        "invested": (entry or 0) * (qty or 0),
                        "current_value": (current * qty) if (current is not None and qty) else None,
                        "prices": prices, "days_held": days_held,
                        "net_pnl": net_pnl, "net_pct": net_pct,
                        "next_alert_pct": _next_gain_alert_pct(pnl_pct),
                        "forecast_entry_limit": r.get("entry_limit"), "forecast_target": r.get("target_base"),
                        "forecast_stop": r.get("stop_loss"), "forecast_score": r.get("overreaction_score"),
                        "forecast_verdict": r.get("overreaction_verdict"),
                        "holding_stop_price": get_or_backfill_stop_price(r, entry) if entry else None,
                        "is_manual_trade": bool(r.get("is_manual_trade")) if pd.notna(r.get("is_manual_trade")) else False,
                        "daily_pct": daily_pct,
                        "sector": r.get("sector") or "לא ידוע",
                    })

                rows.sort(key=lambda r: r["net_pnl"] if r["net_pnl"] is not None else float("-inf"), reverse=True)
                _total_current_value = sum(r["current_value"] for r in rows if r["current_value"]) or 1.0
                for _r in rows:
                    _r["portfolio_pct"] = (_r["current_value"] or 0) / _total_current_value * 100

                by_ccy = {}
                for row in rows:
                    by_ccy.setdefault(row["ccy"], {"invested": 0.0, "current_value": 0.0, "pnl": 0.0, "count": 0})
                    by_ccy[row["ccy"]]["invested"] += row["invested"]
                    by_ccy[row["ccy"]]["current_value"] += row["current_value"] or 0
                    by_ccy[row["ccy"]]["pnl"] += row["pnl"] or 0
                    by_ccy[row["ccy"]]["count"] += 1

                # חשיפה לפי סקטור (לא קשורה להתראה ספציפית) - כדי לראות ריכוז
                # גם כשאף ירידה בודדת לא מסמנת אותו. מוצגת רק כשיש יותר
                # מקטגוריה אחת - "100% טכנולוגיה" לא אינפורמטיבי.
                by_sector = {}
                for row in rows:
                    sector_label = _SECTOR_LABELS_HE.get(row["sector"], row["sector"])
                    by_sector.setdefault(sector_label, 0.0)
                    by_sector[sector_label] += row["current_value"] or 0

                # אותו מיפוי סקטור->צבע בדיוק כמו במקרא של משבצת ההתפלגות (_breakdown_rows
                # ממיין לפי שווי יורד, ואז _ALLOCATION_PALETTE[i]) - כדי שהנקודה בכרטיס
                # האחזקה הבודדת תתאים לצבע של אותו סקטור במקרא, לא צבע שרירותי אחר.
                _sector_color_map = {
                    r["name"]: _ALLOCATION_PALETTE[i % len(_ALLOCATION_PALETTE)]
                    for i, r in enumerate(_breakdown_rows(by_sector))
                }
                for row in rows:
                    row["sector_color"] = _sector_color_map.get(
                        _SECTOR_LABELS_HE.get(row["sector"], row["sector"]), NEUTRAL_COLOR)

                # משבצת "סה"כ אחזקות" מוחלפת בהתפלגות לפי סקטור כשיש יותר מסקטור
                # אחד (אחרת אין מה להראות, ונשאר המספר הרגיל). ראשונה ב-DOM כדי
                # שתופיע בצד ימין (הראשון בסדר RTL), כפי שהתבקש.
                if len(by_sector) > 1:
                    cards_html = _stat_card_breakdown("התפלגות לפי סקטור", _breakdown_rows(by_sector), holdings_count=len(rows))
                else:
                    cards_html = _stat_card("סה\"כ אחזקות", str(len(rows)), NEUTRAL_COLOR, NEUTRAL_BG)
                for ccy, agg in by_ccy.items():
                    symbol = CURRENCY_SYMBOLS.get(ccy, ccy)
                    pnl_color = POS_COLOR if agg["pnl"] >= 0 else NEG_COLOR
                    pnl_bg = POS_BG if agg["pnl"] >= 0 else NEG_BG
                    cards_html += _stat_card(f"השקעות ({symbol})", f"{agg['invested']:,.0f}", NEUTRAL_COLOR, NEUTRAL_BG)
                    cards_html += _stat_card(f"שווי נ‌וכחי ({symbol})", f"{agg['current_value']:,.0f}", NEUTRAL_COLOR, NEUTRAL_BG)
                    cards_html += _stat_card(f"רווח/הפסד ({symbol})", _signed_num(agg["pnl"]), pnl_color, pnl_bg)

                st.markdown(
                    f"""<div style="display:flex; gap:10px; flex-wrap:wrap;">{cards_html}</div>""",
                    unsafe_allow_html=True,
                )

                st.divider()
                _render_open_position_expander()
                st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

                for i, row in enumerate(rows):
                    if i % 3 == 0:
                        card_cols = st.columns(3)
                    with card_cols[i % 3]:
                        render_holding_card(row)

        _render_holdings_tab()


_tab_slot_history = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
with _tab_slot_history.container():
    if st.session_state.active_tab == "history":
        st.caption("היסטוריית העסקאות שסגרת בפועל - התחזית של המערכת מול התוצאה האמיתית שקיבלת")
        hist_conn = store.get_conn(db_path(cfg))
        closed_trades = store.get_closed_trades(hist_conn)
        hist_conn.close()

        if not closed_trades:
            st.info("עדיין אין עסקאות סגורות. כשתסגור אחזקה (💰 מכירה) בטאב 'אחזקות', היא תופיע כאן.")
        else:
            hist_df = pd.DataFrame(closed_trades)

            total_trades = len(hist_df)
            wins = int((hist_df["net_pnl"] > 0).sum())
            win_rate = (wins / total_trades * 100) if total_trades else None
            win_rate_text = f"{win_rate:.0f}%" if win_rate is not None else "—"
            win_rate_color = POS_COLOR if (win_rate or 0) >= 50 else NEG_COLOR
            win_rate_bg = POS_BG if (win_rate or 0) >= 50 else NEG_BG

            hist_cards = "".join([
                _stat_card('סה"כ עסקאות סגורות', str(total_trades), NEUTRAL_COLOR, NEUTRAL_BG),
                _stat_card("עסקאות ברווח", str(wins), POS_COLOR, POS_BG),
                _stat_card("שיעור הצלחה בפועל", win_rate_text, win_rate_color, win_rate_bg),
            ])
            for ccy, grp in hist_df.groupby("currency"):
                symbol = CURRENCY_SYMBOLS.get(ccy, ccy)
                total_gross = grp["gross_pnl"].sum()
                total_net = grp["net_pnl"].sum()
                hist_cards += _stat_card(
                    f'רווח/הפסד כולל ({symbol})', _signed_num(total_gross),
                    POS_COLOR if total_gross >= 0 else NEG_COLOR, POS_BG if total_gross >= 0 else NEG_BG,
                )
                hist_cards += _stat_card(
                    f'רווח/הפסד נטו כולל ({symbol})', _signed_num(total_net),
                    POS_COLOR if total_net >= 0 else NEG_COLOR, POS_BG if total_net >= 0 else NEG_BG,
                )
            st.markdown(f'<div style="display:flex; gap:10px; flex-wrap:wrap;">{hist_cards}</div>', unsafe_allow_html=True)

            st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

            def _forecast_outcome(r: dict) -> str:
                if r.get("forecast_target") is not None and r["exit_price"] >= r["forecast_target"]:
                    return "🎯 הגיע ליעד"
                if r.get("forecast_stop") is not None and r["exit_price"] <= r["forecast_stop"]:
                    return "🛑 פגע בסטופ"
                return "↔ נסגר באמצע"

            def _fmt_price_date(price: float | None, date_str: str | None, is_il: bool) -> str:
                if price is None or pd.isna(price):
                    return "—"
                price_text = f"{price*100:,.0f}" if is_il else f"{price:,.2f}"
                try:
                    date_text = dt.datetime.fromisoformat(date_str).strftime("%d.%m.%y")
                except Exception:
                    date_text = "—"
                return f"{price_text} ({date_text})"

            def _outcome_color(text: str) -> str:
                if text.startswith("🎯"):
                    return POS_COLOR
                if text.startswith("🛑"):
                    return NEG_COLOR
                return NEUTRAL_COLOR

            hist_df = hist_df.sort_values("exit_at", ascending=False)

            # st.dataframe מצייר תמיד על גבי canvas משמאל לימין ומתעלם לגמרי מ-CSS -
            # אי אפשר ליישר לימין או לשלוט במיקום תווים בתוכו (ראו גם ההערה על כך
            # ב-get_all_changes). לכן טבלת ההיסטוריה בנויה כאן כטבלת HTML רגילה,
            # שבה יש שליטה מלאה על יישור ומיקום תווים כמו % .
            header_cells = "".join(
                f'<th style="padding:8px 12px; text-align:right; font-weight:600; '
                f'border-bottom:1px solid rgba(128,128,128,0.3);">{h}</th>'
                for h in ["מניה", "כניסה", "יציאה", "ימי החזקה", "תחזית מול בפועל", "תשואה", "רווח/הפסד", "נטו", "מטבע"]
            )

            body_rows = []
            for _, r in hist_df.iterrows():
                is_il = market_data._is_israeli_ticker(r["ticker"])
                _manual_badge = ' <span style="font-size:0.75rem; opacity:0.7;">🖐️</span>' if r.get("is_manual_trade") else ""
                name = f"{r['company_name'] or r['ticker']} ({r['ticker']}){_manual_badge}"
                entry_text = _fmt_price_date(r["entry_price"], r["entry_at"], is_il)
                exit_text = _fmt_price_date(r["exit_price"], r["exit_at"], is_il)
                outcome_text = _forecast_outcome(r)
                outcome_color = _outcome_color(outcome_text)

                gross_pnl = r["gross_pnl"]
                invested = (r["entry_price"] or 0) * (r["qty"] or 0)
                gross_pct = (gross_pnl / invested * 100) if invested else 0.0
                gross_color = POS_COLOR if gross_pnl >= 0 else NEG_COLOR
                gross_pnl_text = _signed_num(gross_pnl)
                gross_pct_text = _signed_num(gross_pct, 1, "%")

                net_color = POS_COLOR if r["net_pnl"] >= 0 else NEG_COLOR
                net_pnl_text = _signed_num(r["net_pnl"])

                cells = [
                    name, entry_text, exit_text, f"{r['holding_days']:.0f}",
                    f'<span style="color:{outcome_color}; font-weight:600;">{outcome_text}</span>',
                    f'<span style="color:{gross_color}; font-weight:600;">{gross_pct_text}</span>',
                    f'<span style="color:{gross_color}; font-weight:600;">{gross_pnl_text}</span>',
                    f'<span style="color:{net_color}; font-weight:600;">{net_pnl_text}</span>',
                    r["currency"],
                ]
                row_html = "".join(
                    f'<td style="padding:8px 12px; text-align:right; border-bottom:1px solid rgba(128,128,128,0.15);">{c}</td>'
                    for c in cells
                )
                body_rows.append(f"<tr>{row_html}</tr>")

            table_html = (
                f'<table style="width:100%; border-collapse:collapse; direction:rtl; font-size:0.9rem;">'
                f'<thead><tr>{header_cells}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)


with st.container(border=True, key="market_panel"):
    @st.fragment(run_every="60s")
    def _render_market_panel() -> None:
        """fragment עם run_every - כרטיסי המדדים ו'התיק שלי' מתעדכנים לבד כל
        דקה, כולל הפעלה מחדש של חישוב הסיכום (לא רק רינדור) כדי שהמחירים
        באמת יישלפו טריים בכל פעם, לא רק בטעינת הדף. טוען מחדש גם את df עצמו
        (לא סומך על המשתנה החיצוני שנטען פעם אחת בטעינת העמוד) - אחרת אחזקה
        חדשה שנוספה ברקע (למשל דרך הסורק) לא הייתה מופיעה כאן בלי ריענון ידני."""
        _fresh_df = load_alerts(db_path(cfg))
        _fresh_holdings_df = (
            _fresh_df[_fresh_df.get("bought") == 1] if (not _fresh_df.empty and "bought" in _fresh_df.columns)
            else pd.DataFrame()
        )
        st.subheader("📊 מצב המדדים")
        index_changes = get_index_changes()
        cols = st.columns(4, gap="medium")
        for col, idx in zip(cols, ALL_INDICES):
            with col:
                render_index_card(INDEX_LABELS[idx], index_changes.get(idx), is_market_open(idx))

        _portfolio_summary, _today_summary, _value_summary, _proximity_summary = _compute_portfolio_summaries(_fresh_holdings_df)
        if _portfolio_summary:
            with st.container(key="portfolio_header"):
                st.markdown(
                    """
                    <style>
                    /* מצב המדדים מקבל את הרווח שלו מ-padding-top של המסגרת (8px) +
                    padding-top הפנימי הטבעי של h3 (12px). כדי שהרווח מתחת ל-divider
                    ייראה זהה, לא מאפסים את ה-padding-top הטבעי של ה-h3 כאן - רק
                    קובעים ל-hr בדיוק את אותם 8px (כמו ריפוד המסגרת) אחריו. */
                    div[class*="st-key-portfolio_header"] hr { margin: 14px 0 8px 0 !important; }
                    div[class*="st-key-portfolio_header"] h3 { margin-top: 0 !important; }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                st.divider()
                st.subheader("💼 התיק שלי")
            _pf_cols = st.columns(4, gap="medium")
            if _value_summary:
                with _pf_cols[0]:
                    render_value_card(*_value_summary)
            with _pf_cols[1]:
                render_portfolio_card(*_portfolio_summary, dynamic_icon=True)
            if _today_summary:
                with _pf_cols[2]:
                    render_portfolio_card(*_today_summary, dynamic_icon=True)
            if _proximity_summary:
                with _pf_cols[3]:
                    render_proximity_card(*_proximity_summary)

        # מחמם מראש (בלי להציג כלום) את המטמון של get_all_changes לכל מדדי
        # הסריקה, באותו קצב (60s) שה-ttl שלו - כדי שכשעוברים לטאב "מניות
        # מובילות" השליפה כבר תיפגע במטמון חם ותחזור כמעט מיידית, במקום
        # לחסום כמה שניות. זה חשוב כי בדיוק באותו חלון חסימה איטי הבחנו
        # שסטרימליט עלול להציג לרגע תוכן ישן מהטאב הקודם באזור הזה (למטה,
        # אחרי כל הטאבים) - לפני שהנתונים החדשים מגיעים ודוחקים אותו למקומו.
        _warm_days = st.session_state.get("movers_cumulative_days", 3)
        for _warm_idx in (cfg.get("indices") or ALL_INDICES):
            get_all_changes(_warm_idx, _warm_days)

    _render_market_panel()

    def _load_fresh_holdings() -> pd.DataFrame:
        _fresh_df2 = load_alerts(db_path(cfg))
        return (
            _fresh_df2[_fresh_df2.get("bought") == 1] if (not _fresh_df2.empty and "bought" in _fresh_df2.columns)
            else pd.DataFrame()
        )

    # min-height משותף לשתי המשבצות כדי שיהיו זהות בגובה - חייב להיות דינמי
    # ולא קבוע, כי גובה גרף רווח/הפסד עצמו דינמי (תלוי במספר האחזקות, ראו
    # _build_pnl_bar_chart), בניגוד לגרף ההשוואה למדד שתמיד קבוע. 76px = ה-"שלד"
    # הקבוע (כותרת + legend + padding) שנשאר גם כשהגרף עצמו גדל.
    _holdings_count_for_height = len(_load_fresh_holdings())
    _shared_chart_min_height = max(236, 46 * _holdings_count_for_height + 76)
    st.markdown(
        f'<style>div[class*="st-key-chart_card_pnl"], '
        f'div[class*="st-key-chart_card_comparison"] {{ min-height: {_shared_chart_min_height}px; }}</style>',
        unsafe_allow_html=True,
    )
    _chart_cols = st.columns(2, gap="medium")

    with _chart_cols[0]:
        @st.fragment(run_every="60s")
        def _render_pnl_chart() -> None:
            """fragment מהיר (60 שניות) - בניגוד לגרף ההשוואה למדד, זה לא צריך
            היסטוריה בכלל, רק מחיר עדכני לכל אחזקה (get_current_price, אותה
            קריאה בדיוק כמו כרטיסי התיק למעלה) - אין סיבה שיתעדכן לאט יותר."""
            _holdings = _load_fresh_holdings()
            if _holdings.empty:
                return
            _rows = []
            for _, r in _holdings.iterrows():
                entry = r.get("actual_entry_price")
                qty = r.get("actual_qty")
                if not entry or not qty:
                    continue
                current = get_current_price(r["ticker"])
                if current is None:
                    # שליפה חיה נכשלה (למשל בדקות הראשונות אחרי פתיחת המסחר) -
                    # נופלים חזרה למחיר האחרון הידוע במקום להשמיט את האחזקה
                    # מהגרף בשקט (זה מה שגרם לגרף כולו "להיעלם" כששלוש
                    # האחזקות נכשלו יחד).
                    fallback_prices = get_sparkline_prices(r["ticker"])
                    current = fallback_prices[-1] if fallback_prices else None
                if current is None:
                    continue
                stop_price = get_or_backfill_stop_price(r, entry)
                target_price = live_target_price(entry, stop_price, r.get("target_base"))
                _rows.append({
                    "name": r.get("company_name") or r["ticker"],
                    "pnl_pct": (current / entry - 1) * 100,
                    "stop_pct": (stop_price / entry - 1) * 100,
                    "target_pct": (target_price / entry - 1) * 100,
                    "value": current * qty,
                })
            if not _rows:
                return
            st.divider()
            with st.container(border=True, key="chart_card_pnl"):
                st.image(render_text_image("רווח/הפסד לפי אחזקה", ACCENT_COLOR, font_size=15))
                st.altair_chart(_build_pnl_bar_chart(_rows), use_container_width=True)

        _render_pnl_chart()

    with _chart_cols[1]:
        @st.fragment(run_every="1800s")
        def _render_comparison_chart() -> None:
            """fragment איטי (30 דקות) - זה כן צריך היסטוריה של חודשים (לתיק
            ולמדד גם יחד), קריאת רשת יקרה יחסית שלא כדאי לחזור עליה כל דקה."""
            _holdings = _load_fresh_holdings()
            if _holdings.empty:
                return
            _comp_df = _compute_portfolio_history(_holdings)
            if _comp_df is None:
                return
            st.divider()
            _port_col, _bench_col = _comp_df.columns[0], _comp_df.columns[1]
            _port_color = POS_COLOR if _comp_df[_port_col].iloc[-1] >= 0 else NEG_COLOR
            with st.container(border=True, key="chart_card_comparison"):
                st.image(render_text_image("תשואה מול מדד", ACCENT_COLOR, font_size=15))
                st.altair_chart(
                    _build_comparison_chart(_comp_df, _port_col, _bench_col, _port_color),
                    use_container_width=True,
                )

        _render_comparison_chart()

    st.divider()

    st.subheader('🕒 שעות מסחר בישראל ובארה"ב')
    mcols = st.columns(2, gap="medium")
    with mcols[0]:
        render_market_card('ארה"ב <span dir="ltr">(S&P 500 / NASDAQ)</span>', "US")
    with mcols[1]:
        render_market_card('ישראל (ת"א 35 / ת"א 125)', "IL")

# עטיפה עם padding אופקי זהה ל-market_panel (8px 16px, ראו CSS למעלה) - כדי
# שהאייקון/טקסט כאן יתחילו באותו X בדיוק כמו "שעות מסחר", שנמצא בתוך container
# עם padding משלו ולכן היה מוזח 16px ימינה יחסית לכותרת הזו שהיתה בלי עטיפה.
with st.container(key="news_header_wrap"):
    st.subheader("📰 חדשות כלכליות")

@st.fragment(run_every="300s")
def _render_news_section() -> None:
    """fragment עם run_every - תואם לזמן המטמון של get_footer_news (5 דקות),
    אין טעם לבדוק יותר תכוף מזה כי ממילא לא יחזרו נתונים טריים יותר."""

    # עצמאי מהטאב הפעיל - "מניות מובילות" מחשב movers_df/movers_index רק כשהוא פתוח,
    # אבל חדשות כלכליות מוצגות תמיד, אז צריך מקור נתונים משלה שלא תלוי באיזה טאב פתוח.
    _news_index = (cfg.get("indices") or ALL_INDICES)[0]
    if _news_index not in ALL_INDICES:
        _news_index = ALL_INDICES[0]
    _news_movers_df = get_all_changes(_news_index)

    if not _news_movers_df.empty:
        _is_il = _news_index.upper() in ("TA35", "TA125")
        _top = _news_movers_df.reindex(_news_movers_df["שינוי יומי (%)"].abs().sort_values(ascending=False).index).head(3)
        _pairs = [
            (r.get("שם") or r["טיקר"], r["טיקר"])
            for _, r in _top.iterrows()
        ]
        with st.spinner("טוען חדשות..."):
            footer_news = get_footer_news(_pairs, _is_il)

        _NEWS_ACCENT = "#4A7FBF"

        def _news_banner_html(title: str, source: str, link: str | None) -> str:
            title = html.escape(title or "")
            source = html.escape(source or "")
            inner = (
                f'<div style="font-size:0.92rem; font-weight:600; line-height:1.45;">{title}</div>'
                f'<div style="font-size:0.75rem; opacity:0.6; margin-top:6px;">📌 {source}</div>'
            )
            card = (
                f'<div class="news-card" style="border-radius:10px; padding:12px 16px; '
                f'background:rgba(128,128,128,0.05); border-right:3px solid {_NEWS_ACCENT}; '
                f'box-shadow:0 1px 3px rgba(0,0,0,0.05);">{inner}</div>'
            )
            if link:
                link = html.escape(link, quote=True)
                return (f'<a href="{link}" target="_blank" rel="noopener" style="text-decoration:none; '
                        f'color:inherit; display:block;">{card}</a>')
            return card

        def _render_news_grid(items: list[dict], empty_text: str) -> None:
            if not items:
                st.caption(empty_text)
                return
            banners = "".join(_news_banner_html(h.get("title"), h.get("source", ""), h.get("link")) for h in items)
            rows = (len(items) + 1) // 2
            height = max(80, min(85 * rows + 10, 700))
            components.html(
                f"""
                <html><head><style>
                  html, body {{ margin:0; padding:0; background:transparent; direction: rtl;
                    font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;
                    color:#31333F; }}
                  @media (prefers-color-scheme: dark) {{ html, body {{ color:#FAFAFA; }} }}
                  .news-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:10px; }}
                  .news-card {{ transition: box-shadow 0.15s ease, transform 0.15s ease; height:100%;
                                box-sizing:border-box; }}
                  a {{ display:block; height:100%; }}
                  a:hover > .news-card {{
                    box-shadow: 0 4px 10px rgba(0,0,0,0.13) !important;
                    transform: translateY(-1px);
                    background: rgba(128,128,128,0.09) !important;
                  }}
                </style></head>
                <body><div class="news-grid">{banners}</div></body></html>
                """,
                height=height,
            )

        _all_news_items = list(footer_news["general"])
        for name, heads in footer_news["stock_news"].items():
            for h in heads:
                _all_news_items.append({**h, "source": f'{h.get("source", "")} · {name}'})

        _render_news_grid(_all_news_items, "לא נמצאו חדשות כרגע.")
    else:
        st.caption("עבור לטאב \"מניות מובילות\" כדי לראות חדשות רלוונטיות.")

_render_news_section()
