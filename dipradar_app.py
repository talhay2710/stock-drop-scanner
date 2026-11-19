"""דשבורד צפייה חיה בהתראות - הרצה: streamlit run dashboard.py"""
import concurrent.futures
import datetime as dt
import html
import json
import os
import re
import sys
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml








sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# פריסה לשרת שכבר רץ (Streamlit Cloud, fileWatcherType=none) מחליפה את dashboard.py אבל מודולי src נשארים במטמון של התהליך -
# dashboard חדש מול ui_v3 ישן נתן AttributeError (18.10.2026). בפעם הראשונה שגרסת הקובץ הזו רצה בתהליך מוחקים את מודולי src
# מהמטמון, והייבואים שלמטה טוענים אותם מחדש מהדיסק.
_DASH_MTIME = os.path.getmtime(os.path.abspath(__file__))
if getattr(sys, "_dipradar_dash_mtime", None) != _DASH_MTIME:
    for _mod_name in [n for n in list(sys.modules) if n == "src" or n.startswith("src.")]:
        del sys.modules[_mod_name]
    sys._dipradar_dash_mtime = _DASH_MTIME

from src.config import load_config, db_path, CONFIG_PATH, ROOT_DIR
from src.scanner import run_scan, STOP_LOSS_FACTOR, STOP_WARN_PCT, TARGET_WARN_PCT, compute_holdings_value_by_currency
from src.strategy import ATR_STOP_MULTIPLIER, live_target_price, stop_distance_pct, target_distance_pct
from src import strategy as strategy_mod, post_alert, strategy_stats, ui_v3, scan_status
from src.names import fix_name
from src import market_data, constituents, news, backtest, store, analysis, fees, cloud_sync, notifier
from src.market_hours import is_trading_day, MARKET_HOURS, get_market_status, format_countdown, is_market_open, israel_today, israel_now, has_closed_today, bought_after_close

_UI_PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ui_prefs.json")
_PERF_PREF_KEYS = ("perf_scope", "perf_market", "perf_signal", "perf_target", "perf_hold")


_UI_PREFS_ON = (bool(load_config().get("ui_prefs", False)) or bool(os.environ.get("TESTER_USER"))) and os.environ.get("DIPRADAR_NO_PREFS") != "1"  # רק מקומית (ר' cloud_sync)


def _load_ui_prefs() -> dict:
    if not _UI_PREFS_ON:
        return {}
    try:
        return json.loads(open(_UI_PREFS_FILE, encoding="utf-8").read())
    except Exception:
        return {}


def _save_ui_prefs(updates: dict) -> None:
    """שומר העדפות תצוגה מקומיות (הבחירה האחרונה של המשתמש) - רק כשמשהו השתנה."""
    if not _UI_PREFS_ON:
        return
    prefs = _load_ui_prefs()
    if all(prefs.get(k) == v for k, v in updates.items()):
        return
    prefs.update(updates)
    try:
        open(_UI_PREFS_FILE, "w", encoding="utf-8").write(json.dumps(prefs, ensure_ascii=False, indent=1))
    except Exception:
        pass


def _restore_filter_prefs(spec: dict) -> None:
    """משחזר את הבחירה האחרונה של מסנני טאב (כשמצב הווידג'ט נמחק - מעבר טאב/רענון); בלי בחירה שמורה (או ערך שכבר לא חוקי) - ברירת מחדל.
    spec: {מפתח: (ברירת מחדל, [אפשרויות חוקיות])}."""
    prefs = _load_ui_prefs()
    for key, (default, options) in spec.items():
        if st.session_state.get(key) is None:
            saved = prefs.get(key)
            st.session_state[key] = saved if saved in options else default


def _save_filter_prefs(keys: tuple) -> None:
    _save_ui_prefs({k: st.session_state.get(k) for k in keys if st.session_state.get(k) is not None})




# עיצוב v3 (15.10.2026, "Ivory + Radar", מוקאפים שאושרו בטאב-אחר-טאב): ui_v3 ב-config.yaml. חזרה = ui_v3: false + רענון.
# שכבת CSS אחת שנטענת אחרונה (מנצחת את הכללים הישנים); יום/לילה: ברירת מחדל לפי הגדרת המערכת, ובורר ידני (יום/לילה בכותרת)
# שקובע data-theme על <html> - כל הצבעים כאן הם משתני --v3-*, ולכן הווידג'טים של Streamlit נצבעים מחדש גם הם.
_V3_CSS = """
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
        [data-testid='stMain'], [data-testid='stSidebar'] { opacity: 1 !important; animation: none !important; }
        :root {
            --v3-bg:#F6F4F0; --v3-surface:#F9F6EF; --v3-ink:#24211D; --v3-soft:#59534C; --v3-dim:#6F6A62; --v3-rule:#DAD5CC;
            --v3-accent:#2F5D50; --v3-gain:#2F6B4F; --v3-loss:#9B3F2F; --v3-warn:#8A6A1F; --v3-hover:#EFECE6;
            --v3-side:#F2EFE9; --v3-rule-strong:#24211D; --v3-dash:#A8A196; --v3-dot-off:#A8A196;
        }
        @media (prefers-color-scheme: dark) {
            :root:not([data-theme="light"]) {
                --v3-bg:#1A1814; --v3-surface:#211E19; --v3-ink:#ECE8E0; --v3-soft:#C4BFB5; --v3-dim:#9A948A; --v3-rule:#34302A;
                --v3-accent:#8DBBA6; --v3-gain:#7DBF9C; --v3-loss:#D98672; --v3-warn:#D8B05A; --v3-hover:#221F1A;
                --v3-side:#15130F; --v3-rule-strong:#5A554C; --v3-dash:#7A746A; --v3-dot-off:#5A554C; color-scheme: dark;
            }
        }
        :root[data-theme="dark"] {
            --v3-bg:#1A1814; --v3-surface:#211E19; --v3-ink:#ECE8E0; --v3-soft:#C4BFB5; --v3-dim:#9A948A; --v3-rule:#34302A;
            --v3-accent:#8DBBA6; --v3-gain:#7DBF9C; --v3-loss:#D98672; --v3-warn:#D8B05A; --v3-hover:#221F1A;
            --v3-side:#15130F; --v3-rule-strong:#5A554C; --v3-dash:#7A746A; --v3-dot-off:#5A554C; color-scheme: dark;
        }
        html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"], header[data-testid="stHeader"] {
            background: var(--v3-bg) !important; color: var(--v3-ink);
            font-family: 'Heebo', system-ui, sans-serif !important;
        }
        [data-testid="stMainBlockContainer"] { max-width: 1080px; margin-inline: auto; padding-inline: 16px; }
        [data-testid="stSidebar"] { background: var(--v3-bg) !important; border-inline-start: 1px solid var(--v3-rule); }
        /* סיידבר מקופל: בלי קו שנשאר בקצה (15.10.2026) */
        [data-testid="stSidebar"][aria-expanded="false"], [data-testid="stSidebar"][data-collapsed="true"] { border: 0 !important; box-shadow: none !important; }
        [data-testid="stSidebar"][aria-expanded="false"] *, [data-testid="stSidebar"][data-collapsed="true"] * { border-color: transparent !important; }
        h1, h2, h3 { font-weight: 500 !important; letter-spacing: 0 !important; }
        /* הכותרת הישנה (לוגו מרכזי) מוחלפת בכותרת-ניווט בשורה אחת */
        div[class*="st-key-main_title_wrap"] { display: none !important; }
        div[class*="st-key-nav_tabs_row"] {
            background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--v3-rule) !important;
            border-radius: 0 !important; box-shadow: none !important; padding: 8px 0 4px !important;
        }
        div[class*="st-key-nav_tabs_row"] [data-testid="stHorizontalBlock"] { gap: 30px !important; align-items: center !important; }
        div[class*="st-key-nav_tabs_row"] [data-testid="stColumn"] { width: auto !important; flex: 0 0 auto !important; min-width: 0 !important; }
        div[class*="st-key-nav_tabs_row"] [data-testid="stColumn"]:last-child { flex: 1 1 auto !important; }
        div[class*="st-key-navtab_"] button {
            background: transparent !important; border: 0 !important; border-bottom: 2px solid transparent !important;
            border-radius: 0 !important; box-shadow: none !important; padding: 8px 0 2px !important;
            color: var(--v3-dim) !important; font-size: 15px !important; font-weight: 400 !important; min-height: 0 !important;
        }
        div[class*="st-key-navtab_"] button:hover { color: var(--v3-accent) !important; background: transparent !important; }
        div[class*="st-key-navtab_"] button[kind="primary"] {
            color: var(--v3-accent) !important; font-weight: 500 !important; border-bottom-color: var(--v3-accent) !important;
        }
        div[class*="st-key-navtab_"] button p { font-size: inherit !important; font-weight: inherit !important; }
        .v3brand { display: inline-flex; align-items: center; gap: 10px; position: relative; top: 3px; font-weight: 600; font-size: 19px; color: var(--v3-ink) !important;
                   text-decoration: none !important; letter-spacing: -0.01em; white-space: nowrap; }
        .v3brand svg circle { stroke: var(--v3-accent); }
        .v3brand svg circle.dot { fill: var(--v3-accent); stroke: none; }
        @media (max-width: 480px) {
            /* רווח בתחתית הדף: השורה האחרונה יכולה לגלול מעל כפתורי הצף של Streamlit (למשל "Manage app" לבעלים) */
            [data-testid="stMain"] .block-container { padding-bottom: 110px !important; }
            div[class*="st-key-nav_tabs_row"] [data-testid="stHorizontalBlock"] { gap: 6px 18px !important; flex-wrap: wrap !important; }
            div[class*="st-key-nav_tabs_row"] [data-testid="stColumn"]:first-child { flex: 1 1 100% !important; }
            /* בורר יום/לילה בנייד: בקצה השמאלי של שורת הלוגו (התאריך מוסתר בתוך ה-iframe הצר) */
            div[class*="st-key-nav_tabs_row"] [data-testid="stHorizontalBlock"] { position: relative !important; }
            div[class*="st-key-nav_tabs_row"] [data-testid="stColumn"]:last-child { position: absolute !important; left: 0 !important; top: -4px !important; width: 110px !important; flex: none !important; z-index: 2; }
            /* חמש לשוניות בשורה אחת, תאים שווים, שמות קצרים */
            div[class*="st-key-nav_tabs_row"] [data-testid="stHorizontalBlock"] { gap: 6px 0 !important; align-items: stretch !important; }
            div[class*="st-key-nav_tabs_row"] [data-testid="stColumn"]:not(:first-child):not(:last-child) { flex: 1 1 18% !important; width: auto !important; min-width: 0 !important; max-width: 20% !important; }
            div[class*="st-key-navtab_"] { width: 100% !important; }
            div[class*="st-key-navtab_"] button { width: 100% !important; padding: 8px 2px 6px !important; justify-content: center !important; }
            div[class*="st-key-navtab_"] button p { text-align: center !important; white-space: nowrap !important; }
            div[class*="st-key-navtab_movers"] button p { font-size: 0 !important; }
            div[class*="st-key-navtab_movers"] button p::after { content: "מניות"; font-size: 15px; }
            div[class*="st-key-navtab_today"] button p { font-size: 0 !important; }
            div[class*="st-key-navtab_today"] button p::after { content: "התראות"; font-size: 15px; }
            div[class*="st-key-navtab_portfolio"] button p { font-size: 0 !important; }
            div[class*="st-key-navtab_portfolio"] button p::after { content: "אחזקות"; font-size: 15px; }
            div[class*="st-key-navtab_history"] button p { font-size: 0 !important; }
            div[class*="st-key-navtab_history"] button p::after { content: "יומן"; font-size: 15px; }
            div[class*="st-key-navtab_backtest"] button p { font-size: 0 !important; }
            div[class*="st-key-navtab_backtest"] button p::after { content: "ביצועים"; font-size: 15px; }
            /* האתר לא "רוקד" ימינה ושמאלה בטלפון: חותכים גלישה אופקית ברמת המסמך (טבלאות עם גלילה פנימית ממשיכות לגלול בתוך המכל שלהן) */
            html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"] { overflow-x: clip !important; overscroll-behavior-x: none !important; max-width: 100vw; }
            [data-testid="stMainBlockContainer"] { max-width: 100% !important; overflow-x: clip; }
            /* פס אנכי דק שנראה לפעמים בטלפון: קו הצד של הסיידבר כשהוא סגור/מוסתר */
            [data-testid="stSidebar"] { border: 0 !important; box-shadow: none !important; }
            /* סיידבר בנייד: נפתח על כל המסך (בלי תוכן חצי-חתוך מאחוריו) */
            [data-testid="stSidebar"][aria-expanded="true"], [data-testid="stSidebar"][data-collapsed="false"] { width: 100vw !important; min-width: 100vw !important; max-width: 100vw !important; }
        }
"""

_V3_CSS += """
        /* ווידג'טים של Streamlit בכל מצב תצוגה (גם כשהבורר הידני סותר את ערכת הנושא של Streamlit): צבעים מהמשתנים */
        [data-testid="stApp"] [data-testid="stWidgetLabel"] p, [data-testid="stApp"] [data-testid="stCheckbox"] p,
        [data-testid="stApp"] [data-testid="stExpander"] summary p, [data-testid="stApp"] [data-testid="stCaptionContainer"] p,
        [data-testid="stApp"] [data-testid="stMarkdownContainer"] p { color: var(--v3-soft) !important; }
        [data-testid="stApp"] [data-baseweb="select"] > div, [data-testid="stApp"] [data-baseweb="input"],
        [data-testid="stApp"] [data-baseweb="base-input"], [data-testid="stApp"] [data-baseweb="textarea"] {
            background-color: var(--v3-surface) !important; color: var(--v3-ink) !important; border-color: var(--v3-rule) !important;
        }
        [data-testid="stApp"] [data-baseweb="select"] *, [data-testid="stApp"] input, [data-testid="stApp"] textarea { color: var(--v3-ink) !important; }
        [data-baseweb="popover"] [data-baseweb="menu"], [data-baseweb="popover"] ul[role="listbox"], [data-baseweb="popover"] > div {
            background-color: var(--v3-surface) !important; color: var(--v3-ink) !important;
        }
        [data-baseweb="popover"] li[role="option"] { background-color: transparent !important; color: var(--v3-ink) !important; }
        [data-baseweb="popover"] li[role="option"]:hover, [data-baseweb="popover"] li[aria-selected="true"] { background-color: var(--v3-hover) !important; }
        /* Streamlit 1.61: ה-selectbox הוא react-aria ComboBox (לא baseweb) - הכללים שלמעלה לא תופסים אותו, והוא נשאר בהיר בתצוגת לילה */
        [data-testid="stSelectbox"] [role="group"] { background-color: var(--v3-surface) !important; border-color: var(--v3-rule) !important; }
        [data-testid="stSelectbox"] input, [data-testid="stSelectbox"] [role="group"] * { color: var(--v3-ink) !important; }
        [data-testid="stSelectbox"] button svg, [data-testid="stSelectbox"] button svg * { color: var(--v3-dim) !important; }
        [data-testid="stSelectboxVirtualDropdown"] { background-color: var(--v3-surface) !important; border-color: var(--v3-rule) !important; }
        [data-testid="stSelectboxVirtualDropdown"] [role="option"] { background-color: transparent !important; color: var(--v3-ink) !important; }
        [data-testid="stSelectboxVirtualDropdown"] [role="option"] * { color: var(--v3-ink) !important; }
        [data-testid="stSelectboxVirtualDropdown"] [role="option"][data-focused="true"], [data-testid="stSelectboxVirtualDropdown"] [role="option"][data-selected="true"], [data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover { background-color: var(--v3-hover) !important; }
        [data-testid="stApp"] button[kind="secondary"], [data-testid="stApp"] button[kind="primary"] { color: var(--v3-ink); }
        [data-testid="stApp"] [data-testid="stAlert"] { background-color: var(--v3-surface) !important; color: var(--v3-ink) !important; border: 1px solid var(--v3-rule); }
        [data-testid="stApp"] [data-testid="stAlertContainer"] { background-color: transparent !important; }  /* Streamlit 1.61: הצבע הכחול-שקוף של st.info יושב על המכל הפנימי, לא על stAlert */
        [data-testid="stApp"] [data-testid="stAlert"] p, [data-testid="stApp"] [data-testid="stAlert"] [data-testid="stMarkdownContainer"] { color: var(--v3-ink) !important; }
        /* סיידבר v3: בלי כרטיסים - כותרות סעיף, צ'יפים, שדות עם קו תחתון, שורות מתקפלות (המוקאפ שאושר) */
        [data-testid="stSidebar"] { background: var(--v3-side) !important; }
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 6px !important; }
        /* חלון צר (עד 768px, למשל דפדפן במחשב): Streamlit מציג את הסיידבר כשכבה *מעל* העמוד, והוא היה מכסה ומחתך את הצד הימני של התוכן - עד 768px הוא נפתח על כל המסך (כמו בנייד) */
        @media (max-width: 768px) {
            [data-testid="stSidebar"][aria-expanded="true"], [data-testid="stSidebar"][data-collapsed="false"] { width: 100vw !important; min-width: 100vw !important; max-width: 100vw !important; }
        }
        @media (min-width: 769px) { [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 40px !important; } }  /* כותרת הסיידבר באותו גובה כמו כותרת האתר (DipRadar) */
        div[class*="st-key-scan_settings_card"], div[class*="st-key-exp_group_card"], div[class*="st-key-channels_card"] {
            border: 0 !important; border-radius: 0 !important; background: transparent !important; box-shadow: none !important; padding: 0 !important;
        }
        div[data-testid="stVerticalBlock"][class*="st-key-scan_settings_card"],
        div[data-testid="stVerticalBlock"][class*="st-key-exp_group_card"],
        div[data-testid="stVerticalBlock"][class*="st-key-channels_card"] { gap: 0 !important; }
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] { gap: 0 !important; }
        .v3sbt { font-weight: 600; font-size: 16px; color: var(--v3-ink); margin-top: 22px; margin-bottom: 12px; padding-bottom: 0; line-height: 1.4; }
        .v3sbt.tight { margin-bottom: 0; } .v3sbt.tight2 { margin-bottom: 4px; }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { margin: 0; }
        /* Streamlit מוסיף margin-bottom:-1rem למיכל המרקדאון - זה ביטל את הרווח מתחת לכותרות (מדדנו 6px במקום 22) */
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(> .v3sbt) { margin-bottom: 0 !important; }
        /* צ'יפים: מדדים לסריקה */
        [data-testid="stSidebar"] [data-testid="stButtonGroup"] > div[role="toolbar"] { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 0; }
        [data-testid="stSidebar"] button[data-variant="pills"] {
            border: 0 !important; border-bottom: 2px solid transparent !important; background: transparent !important; border-radius: 0 !important;
            padding: 2px 0 !important; min-height: 0 !important; color: var(--v3-dim) !important; box-shadow: none !important;
        }
        [data-testid="stSidebar"] button[data-variant="pills"] p { font-size: 15px; font-weight: 300; direction: ltr; }
        /* שורה לכל שוק (בקשה מ-15.10): ת"א 35 + ת"א 125 למעלה, NASDAQ100 + SP500 מתחת */
        [data-testid="stSidebar"] [data-testid="stButtonGroup"] > div[role="toolbar"] { display: grid; grid-template-columns: repeat(2, max-content); justify-content: start; gap: 8px 26px; }
        [data-testid="stSidebar"] button[data-variant="pills"][data-selected="true"] {
            border-bottom-color: var(--v3-accent) !important; color: var(--v3-ink) !important; background: transparent !important;
        }
        [data-testid="stSidebar"] button[data-variant="pills"][data-selected="true"] p { color: var(--v3-ink) !important; font-weight: 400; }
        /* שדה מושבת (למשל ירידה מצטברת כשהמתג כבוי): נראה בדיוק כמו שדה פעיל - Streamlit מעמעם אותו עד שבלילה לא רואים כלום */
        [data-testid="stSidebar"] [data-testid="stNumberInput"], [data-testid="stSidebar"] [data-testid="stNumberInputContainer"],
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] button { opacity: 1 !important; }
        [data-testid="stSidebar"] [data-testid="stNumberInputField"]:disabled {
            opacity: 1 !important; color: var(--v3-soft) !important; -webkit-text-fill-color: var(--v3-soft) !important;
        }
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"]:has(input:disabled) { cursor: default; }
        /* כפתורי +/- עגולים באמת בכל האתר (קודם נראו כאליפסה - ה-flex כיווץ אותם לרוחב) */
        [data-testid="stNumberInputContainer"] button {
            flex: 0 0 18px !important; width: 18px !important; min-width: 18px !important; max-width: 18px !important;
            height: 18px !important; min-height: 18px !important; aspect-ratio: 1 / 1; border-radius: 50% !important; padding: 0 !important;
            display: inline-flex !important; align-items: center; justify-content: center;
        }
        [data-testid="stNumberInputContainer"] button svg { width: 9px; height: 9px; }
        /* +/- באותו גובה (מרכז אנכי) כמו המספר, בסייד בר */
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] > div:last-child { position: relative; top: 7.5px; }
        /* שדה מספר: מספר + יחידה צמודים, כפתורי +/- בקצה השני (יחידה בימין, המספר משמאלה, כפתורים בקצה השמאלי) */
        [data-testid="stSidebar"] [data-testid="stNumberInput"] { padding-top: 0; }
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] {
            display: flex !important; align-items: center; gap: 3px; background: transparent !important; border: 0 !important;
            border-bottom: 1px solid var(--v3-rule-strong) !important; border-radius: 0 !important; padding: 0 0 6px !important; box-shadow: none !important;
        }
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"]::after { order: 1; color: var(--v3-dim); font-size: 15px; }
        [data-testid="stSidebar"] [data-testid="stNumberInputField"] {
            order: 2; flex: 0 0 5.4ch; width: 5.4ch !important; background: transparent !important; font-size: 20px; font-weight: 300;
            color: var(--v3-soft) !important; padding: 0 !important; text-align: end !important;
        }
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] > div:last-child { order: 3; margin-inline-start: auto; display: flex; gap: 6px; }
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] button {
            width: 26px; height: 26px; min-height: 0; border: 1px solid var(--v3-rule) !important; background: transparent !important;
            border-radius: 50% !important; color: var(--v3-dim) !important; padding: 0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] button:hover { border-color: var(--v3-accent) !important; color: var(--v3-accent) !important; }
        div[class*="st-key-settings_threshold"] [data-testid="stNumberInputContainer"]::after,
        div[class*="st-key-settings_multi_day_threshold"] [data-testid="stNumberInputContainer"]::after,
        div[class*="st-key-settings_gain_start"] [data-testid="stNumberInputContainer"]::after,
        div[class*="st-key-settings_gain_step"] [data-testid="stNumberInputContainer"]::after,
        div[class*="st-key-settings_stop_warn"] [data-testid="stNumberInputContainer"]::after,
        div[class*="st-key-settings_target_warn"] [data-testid="stNumberInputContainer"]::after { content: "%"; }
        div[class*="st-key-settings_multi_day_days"] [data-testid="stNumberInputContainer"]::after { content: "ימים"; }
        div[class*="st-key-settings_multi_day_days"] [data-testid="stNumberInputField"] { flex-basis: 2.8ch; width: 2.8ch !important; }
        /* "ימים" מצד שמאל והספרה מימין (קריאה טבעית בעברית: 3 ימים) - ההפך מהאחוזים, שם היחידה מימין */
        div[class*="st-key-settings_multi_day_days"] [data-testid="stNumberInputField"] { order: 1; text-align: left !important; flex-basis: 2ch; width: 2ch !important; }
        div[class*="st-key-settings_multi_day_days"] [data-testid="stNumberInputContainer"]::after { order: 2; margin-inline-start: 0; }
        /* מתג ההתראה המצטברת */
        [data-testid="stSidebar"] [data-testid="stCheckbox"] { padding-top: 12px; }
        /* מתג בנוי מחדש (בלי הידית של Streamlit שיצאה מהמסילה ב-RTL): מסילה + עיגול שזז בתוכה, כמו במוקאפ */
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label > div:nth-child(2) {
            position: relative; flex: none; width: 27px !important; height: 15px !important; border-radius: 8px !important;
            border: 1px solid var(--v3-rule-strong) !important; background: transparent !important; box-shadow: none !important;
        }
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label > div:nth-child(2) > * { display: none !important; }
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label > div:nth-child(2)::after {
            content: ""; position: absolute; top: 2px; inset-inline-start: 2px; width: 9px; height: 9px; border-radius: 50%;
            background: var(--v3-ink); transition: inset-inline-start .15s;
        }
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label[data-selected="true"] > div:nth-child(2) {
            background: var(--v3-accent) !important; border-color: var(--v3-accent) !important;
        }
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label[data-selected="true"] > div:nth-child(2)::after {
            inset-inline-start: 14px; background: var(--v3-bg);
        }
        /* אותו מתג גם בסוגי ההתראה בטלגרם (במקום תיבות הסימון הכחולות של Streamlit) */
        div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label > div:nth-child(2) {
            position: relative; flex: none; width: 27px !important; height: 15px !important; border-radius: 8px !important;
            border: 1px solid var(--v3-rule-strong) !important; background: transparent !important; box-shadow: none !important;
        }
        div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label > div:nth-child(2) > * { display: none !important; }
        div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label > div:nth-child(2)::after {
            content: ""; position: absolute; top: 2px; inset-inline-start: 2px; width: 9px; height: 9px; border-radius: 50%;
            background: var(--v3-ink); transition: inset-inline-start .15s;
        }
        div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label[data-selected="true"] > div:nth-child(2) {
            background: var(--v3-accent) !important; border-color: var(--v3-accent) !important;
        }
        div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label[data-selected="true"] > div:nth-child(2)::after {
            inset-inline-start: 14px; background: var(--v3-bg);
        }
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label, div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label { align-items: center !important; }
        div[class*="st-key-scan_settings_card"] [data-testid="stCheckbox"] label > div:nth-child(2), div[class*="st-key-exp_message_types"] [data-testid="stCheckbox"] label > div:nth-child(2) { top: -1px; }
        /* כפתור הסריקה הידנית */
        /* פעולה, לא קופסה: שורה עם קו תחתון (כמו שורות ההגדרות המתקדמות), טקסט בצבע המבטא וחץ בקצה */
        div[class*="st-key-sidebar_scan_button"] { padding-top: 6px; }
        div[class*="st-key-sidebar_scan_button"] button {
            border: 0 !important; border-bottom: 1px solid var(--v3-rule) !important; border-radius: 0 !important; padding: 9px 0 !important;
            font-size: 15px !important; font-weight: 500 !important; justify-content: space-between !important; width: 100%; min-height: 0 !important;
            color: var(--v3-accent) !important; background: transparent !important; box-shadow: none !important;
        }
        div[class*="st-key-sidebar_scan_button"] button > div { justify-content: flex-start !important; width: 100%; }
        div[class*="st-key-sidebar_scan_button"] button p { color: var(--v3-accent) !important; font-weight: 500 !important; }
        div[class*="st-key-sidebar_scan_button"] button::after {
            content: "" !important; flex: none; width: 15px; height: 15px; margin-inline-start: 8px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M19 12H5M12 19l-7-7 7-7'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M19 12H5M12 19l-7-7 7-7'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-sidebar_scan_button"] button:hover { background: transparent !important; }
        div[class*="st-key-sidebar_scan_button"] button:hover, div[class*="st-key-sidebar_scan_button"] button:hover p { color: var(--v3-ink) !important; }
        /* שורה פתוחה: גוון שנהב (לא לבן) - גם הכותרת וגם התוכן; הכותרת בלי רקע ובלי עיגול פינות */
        [data-testid="stApp"] [data-testid="stExpander"] summary { background: transparent !important; border-radius: 0 !important; box-shadow: none !important; }
        [data-testid="stSidebar"] [data-testid="stExpander"] details[open], [data-testid="stSidebar"] [data-testid="stExpanderDetails"] { background: var(--v3-bg) !important; }
        [data-testid="stSidebar"] [data-testid="stExpander"] details[open] > summary { background: var(--v3-bg) !important; }
        /* הגדרות מתקדמות: שורות מתקפלות עם קו תחתון בלבד */
        [data-testid="stSidebar"] [data-testid="stExpander"] details { border: 0 !important; border-bottom: 1px solid var(--v3-rule) !important; border-radius: 0 !important; background: transparent !important; }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary { padding: 9px 0 !important; font-size: 15px; color: var(--v3-soft); }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { background: transparent !important; color: var(--v3-accent); }
        [data-testid="stSidebar"] [data-testid="stExpander"] { margin: 0 !important; }
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { font-size: 13px; color: var(--v3-dim); }
        /* חצי פתיחה/סגירה של הסיידבר (>>): ברירת המחדל של Streamlit אפור-כהה קבוע, ובמצב לילה לא רואים אותו */
        [data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"] svg, [data-testid="stSidebarCollapseButton"] span, [data-testid="stExpandSidebarButton"] button, [data-testid="stExpandSidebarButton"] svg, [data-testid="stExpandSidebarButton"] span, [data-testid="stSidebarCollapsedControl"] button, [data-testid="stSidebarCollapsedControl"] svg, [data-testid="stSidebarCollapsedControl"] span { color: var(--v3-dim) !important; fill: var(--v3-dim) !important; }
        /* ערוצי התראה: צ'יפים */
        div[class*="st-key-channels_card"] [data-testid="stCheckbox"] { padding-top: 0; }
        div[class*="st-key-channels_card"] [data-testid="stHorizontalBlock"] { justify-content: flex-start; gap: 26px !important; }
        div[class*="st-key-channels_card"] [data-testid="stColumn"] { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
        div[class*="st-key-channels_card"] [data-testid="stCheckbox"] label {
            border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 0; height: 32px; box-sizing: border-box; display: flex; align-items: center; width: fit-content; cursor: pointer;
        }
        div[class*="st-key-channels_card"] [data-testid="stCheckbox"] label > div:nth-child(2) { display: none; }
        div[class*="st-key-channels_card"] [data-testid="stCheckbox"] label p { font-size: 15px; font-weight: 300; color: var(--v3-dim); }
        div[class*="st-key-channels_card"] [data-testid="stCheckbox"] label[data-selected="true"] { border-bottom-color: var(--v3-accent); background: transparent; }
        div[class*="st-key-channels_card"] [data-testid="stCheckbox"] label[data-selected="true"] p { color: var(--v3-ink); font-weight: 400; }
""" + ui_v3.COMPONENT_CSS + ui_v3.MOVERS_CSS + ui_v3.ALERTS_CSS + ui_v3.HOLDINGS_CSS + ui_v3.JOURNAL_CSS + ui_v3.JOURNAL_KPI_CSS + ui_v3.PERF_CSS + """
        div[class*="st-key-perf_refresh_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-perf_refresh_icon"] button p, div[class*="st-key-perf_refresh_icon"] button div { display: none !important; }
        div[class*="st-key-perf_refresh_icon"] button {
            position: absolute; top: -36px; left: 0; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-perf_refresh_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-perf_filters_hd"] { position: relative; }
        div[class*="st-key-perf_filters_hd"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
        div[class*="st-key-perf_filters_hd"] [data-testid="stElementContainer"]:has(button) { position: absolute; inset: 0 0 auto 0; width: 100% !important; height: 100%; z-index: 3; margin: 0 !important; }
        div[class*="st-key-perf_filters_hd"] button { opacity: 0; position: absolute; inset: 0; width: 100%; height: 100%; min-height: 0; padding: 0 !important; cursor: pointer; }
        div[class*="st-key-perf_filters_body"] { padding: 6px 0 12px; border-bottom: 1px solid var(--v3-rule); }
        div[class*="st-key-perf_filters_body"] [data-testid="stHorizontalBlock"] { align-items: center; gap: 16px; padding: 4px 0; }
        .v3pl { font-size: 13px; color: var(--v3-dim); }
        div[class*="st-key-perf_filters_body"] [data-testid="stButtonGroup"] > div[role="toolbar"], div[class*="st-key-perf_filters_body"] [data-testid="stButtonGroup"] > div[role="radiogroup"] { border: 0 !important; border-radius: 0 !important; flex-wrap: wrap !important; gap: 2px 22px !important; }
        div[class*="st-key-perf_filters_body"] button[data-variant="segmented_control"] {
            background: transparent !important; border-bottom: 2px solid transparent !important; padding: 2px 0 !important; color: var(--v3-dim) !important;
        }
        div[class*="st-key-perf_filters_body"] button[data-variant="segmented_control"] p { font-size: 15px; }
        div[class*="st-key-perf_filters_body"] button[data-variant="segmented_control"][data-selected="true"] {
            background: transparent !important; color: var(--v3-ink) !important; border-bottom-color: var(--v3-accent) !important;
        }
        div[class*="st-key-perf_filters_body"] button[data-variant="segmented_control"][data-selected="true"] p { color: var(--v3-ink) !important; font-weight: 500; }

        div[class*="st-key-alerts_filters"], div[class*="st-key-journal_filters"] { padding: 20px 0 14px; }
        div[class*="st-key-alerts_filters"] [data-testid="stHorizontalBlock"], div[class*="st-key-journal_filters"] [data-testid="stHorizontalBlock"] { gap: 36px !important; justify-content: flex-start !important; flex-wrap: wrap; }
        div[class*="st-key-alerts_filters"] [data-testid="stColumn"], div[class*="st-key-journal_filters"] [data-testid="stColumn"] { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
        div[class*="st-key-alerts_filters"] [data-testid="stColumn"], div[class*="st-key-journal_filters"] [data-testid="stColumn"] { position: relative; }
        div[class*="st-key-alerts_filters"] [data-testid="stColumn"] + [data-testid="stColumn"]::before, div[class*="st-key-journal_filters"] [data-testid="stColumn"] + [data-testid="stColumn"]::before { content: ""; position: absolute; inset-inline-start: -19px; top: 50%; height: 22px; width: 1px; background: var(--v3-rule); transform: translateY(-50%); }
        div[class*="st-key-v3_arowhd_"], div[class*="st-key-v3_hrowhd_"] { position: relative; }
        div[class*="st-key-v3_arowhd_"] [data-testid="stElementContainer"]:has(button[kind="secondary"]),
        div[class*="st-key-v3_hrowhd_"] [data-testid="stElementContainer"]:has(button[kind="secondary"]) { position: absolute; inset: 0 0 auto 0; width: 100% !important; height: 100%; z-index: 3; margin: 0 !important; }
        div[class*="st-key-v3_arow_"] .v3h { margin-block: 0; }  /* margin-inline נשאר -4px (מ-.tw) - כך קווי השורות באותו רוחב כמו קו הכותרת */
        div[class*="st-key-v3_arowhd_"]:hover .arow.r { background: var(--v3-hover); box-shadow: 4px 0 0 var(--v3-hover), -4px 0 0 var(--v3-hover); }  /* הגוון בריחוף יוצא 4px מעבר לקווים, כך שהטקסט הצמוד לקצה לא נוגע בקצה הרקע */
        div[class*="st-key-v3_hrowhd_"]:hover .hrow { background: var(--v3-hover); box-shadow: 4px 0 0 var(--v3-hover), -4px 0 0 var(--v3-hover); }
        div[class*="st-key-v3_hrowhd_"] button[kind="secondary"],
        div[class*="st-key-v3_arowhd_"] button[kind="secondary"] { opacity: 0; width: 100%; height: 100%; min-height: 0; cursor: pointer; padding: 0 !important; position: absolute; inset: 0; }
        div[class*="st-key-v3_arow_"] [data-testid="stVerticalBlock"], div[class*="st-key-v3_hrow_"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
        div[class*="st-key-holdings_refresh_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-holdings_refresh_icon"] button p, div[class*="st-key-holdings_refresh_icon"] button div { display: none !important; }
        div[class*="st-key-holdings_refresh_icon"] button {
            position: absolute; top: -36px; left: 0; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-holdings_refresh_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] details { border: 0 !important; border-bottom: 1px solid var(--v3-rule) !important; border-radius: 0 !important; background: transparent !important; }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] summary { padding: 18px 10px !important; color: var(--v3-soft); font-weight: 400; font-size: 17px; display: flex; justify-content: space-between; align-items: center; }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] summary [data-testid="stIconMaterial"], div[class*="st-key-open_position_expander"] [data-testid="stExpander"] summary > span > span:first-child { display: none !important; }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] summary > span { gap: 0 !important; padding: 0 !important; margin: 0 !important; }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] summary p { font-size: 17px; }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] summary::after { content: ""; width: 12px; height: 12px; flex: none; background: var(--v3-dim); transform: scaleX(-1); transition: transform .15s;
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'><path d='M9 6l6 6-6 6'/></svg>") center/contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'><path d='M9 6l6 6-6 6'/></svg>") center/contain no-repeat; }
        div[class*="st-key-open_position_expander"] [data-testid="stExpander"] details[open] summary::after { transform: scaleX(-1) rotate(90deg); }
        div[class*="st-key-journal_refresh_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-journal_refresh_icon"] button p, div[class*="st-key-journal_refresh_icon"] button div { display: none !important; }
        div[class*="st-key-journal_refresh_icon"] button {
            position: absolute; top: -36px; left: 0; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-journal_refresh_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-journal_refresh_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-journal_filter_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-journal_filter_icon"] button p, div[class*="st-key-journal_filter_icon"] button div { display: none !important; }
        div[class*="st-key-journal_filter_icon"] button {
            position: absolute; top: -48px; left: 34px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-journal_filter_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-journal_filter_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-perf_filter_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-perf_filter_icon"] button p, div[class*="st-key-perf_filter_icon"] button div { display: none !important; }
        div[class*="st-key-perf_filter_icon"] button {
            position: absolute; top: -48px; left: 34px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-perf_filter_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-perf_filter_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-holdings_filter_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-holdings_filter_icon"] button p, div[class*="st-key-holdings_filter_icon"] button div { display: none !important; }
        div[class*="st-key-holdings_filter_icon"] button {
            position: absolute; top: -36px; left: 34px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-holdings_filter_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-holdings_filter_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-movers_filter_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-movers_filter_icon"] button p, div[class*="st-key-movers_filter_icon"] button div { display: none !important; }
        div[class*="st-key-movers_filter_icon"] button {
            position: absolute; top: -48px; left: 34px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-movers_filter_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-movers_filter_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-holdings_filters"] { padding: 12px 0 14px; }
        div[class*="st-key-holdings_add_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-holdings_add_icon"] button p, div[class*="st-key-holdings_add_icon"] button div { display: none !important; }
        div[class*="st-key-holdings_add_icon"] button {
            position: absolute; top: -36px; left: 68px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-holdings_add_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-holdings_add_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-alerts_filter_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-alerts_filter_icon"] button p, div[class*="st-key-alerts_filter_icon"] button div { display: none !important; }
        div[class*="st-key-alerts_filter_icon"] button {
            position: absolute; top: -48px; left: 34px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-alerts_filter_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 5h18l-7 8.5V19l-4 2v-7.5z'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-alerts_filter_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-alerts_add_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-alerts_add_icon"] button p, div[class*="st-key-alerts_add_icon"] button div { display: none !important; }
        div[class*="st-key-alerts_add_icon"] button {
            position: absolute; top: -48px; left: 68px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-alerts_add_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-alerts_add_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-alerts_refresh_icon"], div[class*="st-key-alerts_filter_icon"], div[class*="st-key-alerts_add_icon"] { margin-bottom: -12px !important; }
        div[class*="st-key-exp_price_alert_closed"] { display: none !important; }
        /* טופס התראת מחיר ידנית: כפתור "הוסף התראה" ושדות המספר באותו סגנון כמו טפסי הפוזיציה (היה כחול של Streamlit עם טקסט כהה, ושדות באפור-כחלחל) */
        div[class*="st-key-exp_price_alert"] button[kind="primary"] { background: var(--v3-ink) !important; color: var(--v3-bg) !important; border: 0 !important; border-radius: 8px !important; min-height: 40px; padding: 0 24px !important; }
        div[class*="st-key-exp_price_alert"] button[kind="primary"] p { color: inherit !important; font-size: 15px; }
        div[class*="st-key-exp_price_alert"] [data-testid="stNumberInputContainer"] { background: var(--v3-surface) !important; border-color: var(--v3-rule) !important; }
        div[class*="st-key-exp_price_alert"]:not([class*="st-key-exp_price_alert_closed"]):not([data-testid="stExpander"]) { padding: 12px 12px 18px; border-bottom: 1px solid var(--v3-rule); }
        div[class*="st-key-v3_hpos_"] { padding-inline: 0; }
        div[class*="st-key-holdings_refresh_icon"], div[class*="st-key-holdings_filter_icon"], div[class*="st-key-holdings_add_icon"] { margin-bottom: -12px !important; }  /* שלושת האייקונים בגובה אפס - מבטלים את הרווח שזרימת Streamlit מוסיפה אחרי כל אחד */
        div[class*="st-key-alert_card_"] { background: var(--v3-surface); padding: 16px 12px 22px; border-bottom: 1px solid var(--v3-rule); gap: 20px !important; }
        div[class*="st-key-alert_card_"] .adet { background: none; padding: 0; border-bottom: 0; }
        div[class*="st-key-alert_card_"] { padding-bottom: 14px; }
        div[class*="st-key-alert_card_"]:has(div[class*="st-key-open_pos_exp_"]) { padding-bottom: 0; }  /* השורה האחרונה (פתיחת פוזיציה) כבר כוללת רווח תחתון משלה */
        div[class*="st-key-alert_card_"] .heldline { margin-bottom: -14px; }
        div[class*="st-key-alert_card_"] .amet { padding-top: 15.4px; }
        div[class*="st-key-alert_cum_row_"] { padding-top: 12px; margin-bottom: -7px; }  /* אותו רווח מעל השורה הראשונה כמו מתחת לאחרונה */
        div[class*="st-key-alert_card_"] div[class*="st-key-open_pos_exp_"] { padding-inline: 0; margin-top: 14.5px; }  /* רווח בין השורה התחתונה לקו שמתחתיה = הרווח מהקו העליון לשורה הראשונה */
        div[class*="st-key-alert_card_"] div[class*="st-key-open_pos_exp_"] [data-testid="stExpander"] details { border-bottom: 0 !important; border-top: 1px solid var(--v3-rule) !important; }
        div[class*="st-key-alert_card_"] [data-testid="stButtonGroup"] { justify-content: flex-start; }
        div[class*="st-key-alert_card_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }  /* ברירת המחדל מושכת את האלמנט הבא למעלה ב-16px */
        div[class*="st-key-alert_cum_row_"] { align-items: center; column-gap: 18px !important; }
        div[class*="st-key-alert_cum_row_"] [data-testid="stButtonGroup"] > div[role="toolbar"], div[class*="st-key-alert_cum_row_"] [data-testid="stButtonGroup"] > div[role="radiogroup"] { border: 0 !important; border-radius: 0 !important; gap: 18px !important; flex-wrap: wrap; overflow: visible; }
        div[class*="st-key-alert_cum_row_"] button[data-variant="segmented_control"] { background: transparent !important; border: 0 !important; border-bottom: 2px solid transparent !important; border-radius: 0 !important; padding: 2px 0 !important; min-height: 0 !important; color: var(--v3-dim) !important; box-shadow: none !important; }
        div[class*="st-key-alert_cum_row_"] button[data-variant="segmented_control"] p { font-size: 15px; font-weight: 300; }
        div[class*="st-key-alert_cum_row_"] button[data-variant="segmented_control"][data-selected="true"] { background: transparent !important; color: var(--v3-ink) !important; border-bottom-color: var(--v3-accent) !important; }
        div[class*="st-key-alert_cum_row_"] button[data-variant="segmented_control"][data-selected="true"] p { color: var(--v3-ink) !important; font-weight: 400; }
        .cumline { display: inline-flex; align-items: baseline; gap: 18px; white-space: nowrap; }  /* הרווח בין הכותרת לטקסט = כמו בשורת הניקוד (18px) */  /* כמו שורת "ניקוד": תווית 13px עמומה, ערכים 15px */
        .cumline small { font-size: 13px; color: var(--v3-dim); }
        .cumline b { font-size: 15px; font-weight: 400; color: var(--v3-soft); }
        .cumline b.up { color: var(--v3-gain); } .cumline b.down { color: var(--v3-loss); }
        [data-testid="stSpinner"] { display: none !important; }
        /* deploy-probe-1: מסמן גרסה כדי לוודא שדחיפה מגיעה לציבורי אוטומטית */
        /* הסבר בריחוף על אייקוני הכותרות - CSS בלבד (בלי help של Streamlit שעוטף את הכפתור ומשבש את מיקומו; בלי שינוי הסמן) */
        div[class*="st-key-movers_refresh_icon"] button:hover::after { content: "רענון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-alerts_refresh_icon"] button:hover::after { content: "רענון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-holdings_refresh_icon"] button:hover::after { content: "רענון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-journal_refresh_icon"] button:hover::after { content: "רענון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-perf_refresh_icon"] button:hover::after { content: "רענון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-movers_filter_icon"] button:hover::after { content: "סינון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-alerts_filter_icon"] button:hover::after { content: "סינון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-holdings_filter_icon"] button:hover::after { content: "סינון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-journal_filter_icon"] button:hover::after { content: "סינון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-perf_filter_icon"] button:hover::after { content: "סינון"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-alerts_add_icon"] button:hover::after { content: "התראה ידנית"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-holdings_add_icon"] button:hover::after { content: "פתיחת פוזיציה"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        div[class*="st-key-watch_manage_icon"] button:hover::after { content: "הוספת מניה למעקב"; position: absolute; top: 34px; left: 50%; transform: translateX(-50%); white-space: nowrap; direction: rtl; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 6px; background: var(--v3-ink); color: var(--v3-bg); width: auto; height: auto; inset-inline-end: auto; pointer-events: none; z-index: 30; animation: dr-tip-in .15s .35s both; }
        @keyframes dr-tip-in { from { opacity: 0; } to { opacity: 1; } }
        div[class*="st-key-sell_form_"] { padding: 16px 0 20px; gap: 18px !important; border-bottom: 1px solid var(--v3-rule); }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stWidgetLabel"] p { font-size: 12px; color: var(--v3-dim); }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stNumberInputContainer"] { background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--v3-rule-strong) !important; border-radius: 0 !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stNumberInputContainer"] input { text-align: end; font-size: 17px; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stNumberInputStepUp"], :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stNumberInputStepDown"] { display: none !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInput"] [data-baseweb="input"], :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInput"] [data-baseweb="base-input"] { background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--v3-rule-strong) !important; border-radius: 0 !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInput"] input { font-size: 17px; text-align: right !important; direction: ltr; }
        /* גרסת Streamlit חדשה (בענן): שדה התאריך הוא stDateInputField עם מקטעי יום/חודש/שנה, לא baseweb. ב-RTL המקטעים התהפכו (שנה/חודש/יום) והתיבה נשארה לבנה */
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInputField"] { direction: ltr !important; background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--v3-rule-strong) !important; border-radius: 0 !important; box-shadow: none !important; justify-content: flex-end; }
        /* Streamlit 1.61: שלושה אלמנטים מקוננים (input / base-input / שדה הקלט) קיבלו כל אחד קו תחתון -> קו עבה פי 3; נשאר רק הקו של המעטפת החיצונית */
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInput"] [data-baseweb="base-input"], :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInput"] input[data-testid="stDateInputField"] { border: 0 !important; box-shadow: none !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) [data-testid="stDateInputField"] span { font-size: 17px; color: var(--v3-ink); }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) button[kind="primary"] { background: var(--v3-ink) !important; color: var(--v3-bg) !important; border: 0 !important; border-radius: 8px !important; min-height: 40px; padding: 0 24px !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) button[kind="primary"] p, :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) button[kind="tertiary"] p { color: inherit !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) button[kind="primary"] p { font-size: 15px; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) button[kind="tertiary"] { color: var(--v3-dim) !important; min-height: 40px; padding: 0 12px !important; }
        :is(div[class*="st-key-sell_form_"], div[class*="st-key-openpos_form_"]) button[kind="tertiary"]:hover { color: var(--v3-ink) !important; background: transparent !important; }
        /* טופס פתיחת פוזיציה: החלק שמתחת לשער ולעלות - הערת התוצאה העמומה, מתג עסקה ידנית עם הסבר קטן, וכפתור הוספה בצבע האתר */
        div[class*="st-key-openpos_form_"] { gap: 18px !important; padding-top: 6px; }
        div[class*="st-key-openpos_form_"] [data-testid="stCaptionContainer"] p { font-size: 13px !important; color: var(--v3-dim) !important; line-height: 1.5; }
        div[class*="st-key-openpos_form_"] div[class*="_manualwrap"] { gap: 2px !important; }
        div[class*="st-key-openpos_form_"] div[class*="_manualwrap"] label p { font-size: 15px !important; color: var(--v3-ink) !important; }
        div[class*="st-key-openpos_form_"] div[class*="_manualwrap"] [data-testid="stElementContainer"]:has([data-testid="stToggle"]) { width: fit-content !important; }
        div[class*="st-key-sell_holding_"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 3; width: 100% !important; }
        div[class*="st-key-sell_holding_"] button p, div[class*="st-key-sell_holding_"] button div { display: none !important; }
        div[class*="st-key-sell_holding_"] button { position: absolute; top: 14px; left: 4px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 1px solid var(--v3-rule) !important; background: transparent !important; border-radius: 50% !important; color: var(--v3-dim) !important; font-size: 0 !important; }
        div[class*="st-key-sell_holding_"] button::before { content: ""; position: absolute; left: 50%; top: 50%; width: 12px; height: 2px; margin: -1px 0 0 -6px; background: currentColor; border-radius: 1px; }
        div[class*="st-key-sell_holding_"] button:hover { color: var(--v3-loss, #9B3F2F) !important; border-color: var(--v3-loss, #9B3F2F) !important; background: transparent !important; }
        div[class*="st-key-sell_holding_"] button {
            margin-top: 10px; padding: 6px 14px !important; border: 1px solid var(--v3-rule) !important; border-radius: 6px !important;
            background: transparent !important; color: var(--v3-soft) !important; font-size: 14px !important; font-weight: 400 !important; min-height: 0 !important;
        }
        div[class*="st-key-sell_holding_"] button:hover { border-color: var(--v3-ink) !important; color: var(--v3-ink) !important; }
        div[class*="st-key-alerts_refresh_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-alerts_refresh_icon"] button p, div[class*="st-key-alerts_refresh_icon"] button div { display: none !important; }
        div[class*="st-key-alerts_refresh_icon"] button {
            position: absolute; top: -36px; left: 0; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-alerts_refresh_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-open_pos_exp_"] [data-testid="stExpander"] details, div[class*="st-key-exp_price_alert"] [data-testid="stExpander"] details { border: 0 !important; border-bottom: 1px solid var(--v3-rule) !important; border-radius: 0 !important; background: transparent !important; }
        div[class*="st-key-open_pos_exp_"] [data-testid="stExpander"] summary, div[class*="st-key-exp_price_alert"] [data-testid="stExpander"] summary { padding: 14px 0 !important; color: var(--v3-accent); font-weight: 500; font-size: 15px; }
        div[class*="st-key-open_pos_exp_"] [data-testid="stExpander"] summary:hover, div[class*="st-key-exp_price_alert"] [data-testid="stExpander"] summary:hover { background: transparent !important; }
        div[class*="st-key-open_pos_exp_"] { padding-inline: 12px; }
        div[class*="st-key-exp_price_alert"] [data-testid="stExpander"] summary { padding-inline: 12px !important; }
        [data-testid="stExpander"][class*="st-key-"] summary { color: var(--v3-accent); }

        /* מניות מובילות: בורר מדד (מקטעים), ימים (מספר+טקסט+כפתורים), רענון (אייקון), "הצג את כל", ניהול מעקב */
        [data-testid="stMain"] [data-testid="stButtonGroup"] > div[role="toolbar"] { display: inline-flex; border: 1px solid var(--v3-rule); border-radius: 6px; overflow: hidden; gap: 0; }
        [data-testid="stMain"] button[data-variant="segmented_control"] {
            border: 0 !important; border-radius: 0 !important; background: transparent !important; color: var(--v3-dim) !important;
            padding: 5px 14px !important; min-height: 0 !important; box-shadow: none !important;
        }
        [data-testid="stMain"] button[data-variant="segmented_control"] p { font-size: 13px; white-space: nowrap; }
        [data-testid="stMain"] button[data-variant="segmented_control"][data-selected="true"] { background: var(--v3-ink) !important; color: var(--v3-bg) !important; }
        [data-testid="stMain"] button[data-variant="segmented_control"][data-selected="true"] p { color: var(--v3-bg) !important; }
        div[class*="st-key-movers_controls"] { padding: 20px 0 6px; }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputContainer"] {
            display: flex !important; align-items: center; gap: 8px; background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important;
        }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputContainer"] { height: 32px !important; min-height: 32px !important; align-items: center !important; justify-content: flex-end !important; width: 100% !important; }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputContainer"] > div:last-child { align-self: center !important; }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputField"] {
            order: 1; flex: 0 0 2ch; width: 2ch !important; background: transparent !important; font-size: 15px; color: var(--v3-soft) !important; padding: 0 !important; text-align: left !important;
        }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputContainer"]::after { content: "ימים לירידה מצטברת"; order: 2; font-size: 15px; color: var(--v3-soft); }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputContainer"] > div:last-child { order: 3; display: flex; gap: 6px; margin-inline-start: 8px; }
        div[class*="st-key-movers_cumulative_days"] [data-testid="stNumberInputContainer"] button {
            width: 26px; height: 26px; min-height: 0; border: 1px solid var(--v3-rule) !important; background: transparent !important; border-radius: 50% !important; color: var(--v3-dim) !important; padding: 0 !important;
        }
        div[class*="st-key-movers_refresh_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 2; width: 100% !important; }
        div[class*="st-key-movers_refresh_icon"] button p, div[class*="st-key-movers_refresh_icon"] button div { display: none !important; }
        div[class*="st-key-movers_refresh_icon"] button {
            position: absolute; top: -36px; left: 0; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important;
            background: transparent !important; font-size: 0 !important; border-radius: 50% !important;
        }
        div[class*="st-key-movers_refresh_icon"] button::before {
            content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent);
            -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
            mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 12a8 8 0 1 1-2.6-5.9'/><path d='M20 4v5h-5'/></svg>") center / contain no-repeat;
        }
        div[class*="st-key-movers_refresh_icon"] button:hover, div[class*="st-key-alerts_refresh_icon"] button:hover, div[class*="st-key-holdings_refresh_icon"] button:hover, div[class*="st-key-perf_refresh_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-home_hold_unit"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: relative; z-index: 3; width: 100% !important; }
        div[class*="st-key-home_hold_unit"] [data-testid="stElementContainer"] { position: absolute; top: 66px; left: 0; width: auto !important; }
        div[class*="st-key-home_hold_unit"] button { min-height: 28px !important; padding: 2px 12px !important; font-size: 13px !important; }
        div[class*="st-key-movers_more_"] button {
            width: 100%; justify-content: flex-start; border: 0 !important; border-bottom: 1px solid var(--v3-rule) !important; border-radius: 0 !important;
            background: transparent !important; color: var(--v3-dim) !important; padding: 14px 0 !important; font-size: 14px; min-height: 0 !important;
        }
        div[class*="st-key-movers_more_"] button:hover { color: var(--v3-accent) !important; }
        div[class*="st-key-movers_watch_section"] { position: relative; }
        div[class*="st-key-watch_manage_icon"] { height: 0 !important; min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: visible; position: absolute; top: 0; left: 0; z-index: 2; width: 100% !important; }
        div[class*="st-key-watch_manage_icon"] button p, div[class*="st-key-watch_manage_icon"] button div { display: none !important; }
        div[class*="st-key-watch_manage_icon"] button { position: absolute; top: 47px; left: -3px; width: 28px; height: 28px; min-height: 0; padding: 0 !important; border: 0 !important; background: transparent !important; font-size: 0 !important; border-radius: 50% !important; }
        div[class*="st-key-watch_manage_icon"] button::before { content: ""; position: absolute; inset: 5px; background-color: var(--v3-accent); -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>") center / contain no-repeat; mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>") center / contain no-repeat; }
        div[class*="st-key-watch_manage_icon"] button:hover { background: var(--v3-hover) !important; }
        div[class*="st-key-movers_watch_add_row"] { padding: 6px 0 10px; gap: 16px !important; }
        div[class*="st-key-movers_watch_rows"], div[class*="st-key-movers_watch_rows"] > div { gap: 0 !important; }
        div[class*="st-key-wl_row_"] { position: relative; gap: 0 !important; }
        div[class*="st-key-wl_rm_"] { position: absolute !important; inset-inline-end: 8px; top: 27.5px; transform: translateY(-50%); width: auto !important; z-index: 3; }
        div[class*="st-key-wl_rm_"] button { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 2px 4px !important; min-height: 0 !important; color: var(--v3-dim) !important; font-size: 15px !important; }
        div[class*="st-key-wl_rm_"] button:hover { color: var(--v3-loss, #9B3F2F) !important; background: transparent !important; }
        /* לוח ניהול המעקב: שקט - שדות בלי רקע ובלי מסגרת (רק קו תחתון דק), כפתורים כטקסט */
        div[class*="st-key-movers_watch_actions"] [data-baseweb="select"] > div { background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--v3-rule-strong) !important; border-radius: 0 !important; box-shadow: none !important; min-height: 34px; }
        div[class*="st-key-movers_watch_actions"] label p { font-size: 13px !important; color: var(--v3-dim) !important; }
        div[class*="st-key-movers_watch_actions"] [data-testid="stNumberInputContainer"] { background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--v3-rule-strong) !important; border-radius: 0 !important; }
        div[class*="st-key-movers_watch_actions"] [data-testid="stNumberInputContainer"] input { text-align: end; }
        div[class*="st-key-movers_watch_actions"] [data-testid="stNumberInputStepUp"], div[class*="st-key-movers_watch_actions"] [data-testid="stNumberInputStepDown"] { display: none !important; }
        div[class*="st-key-movers_watch_actions"] button { background: transparent !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important; padding: 4px 0 !important; min-height: 0 !important; color: var(--v3-accent) !important; font-size: 15px !important; white-space: nowrap; }
        div[class*="st-key-movers_watch_actions"] button:hover { text-decoration: underline; background: transparent !important; }
        div[class*="st-key-movers_watch_actions"] button p { font-size: 15px !important; font-weight: 500 !important; }
        .v3h .head > .hr.withico { padding-inline-end: 40px; }
        .v3h .head > .hr.withico2 { padding-inline-end: 74px; }
        .v3h .head > .hr.withico3 { padding-inline-end: 108px; }
"""

# תאריך + בורר יום/לילה בכותרת (iframe קטן): קובע data-theme על <html> של העמוד, שומר ב-localStorage ומסנכרן את שאר ה-iframe-ים
_V3_TOOLS_HTML = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root { --ink:#24211D; --dim:#6F6A62; --rule:#DAD5CC; --bg:#F6F4F0; }
:root[data-theme="dark"] { --ink:#ECE8E0; --dim:#9A948A; --rule:#34302A; --bg:#1A1814; }
html, body { margin:0; background:transparent; font-family:'Heebo',system-ui,sans-serif; direction:rtl; }
.tools { display:flex; align-items:center; gap:16px; height:40px; font-size:14px; color:var(--dim); }
.num { direction:ltr; unicode-bidi:isolate; display:inline-block; }
.seg { display:inline-flex; border:1px solid var(--rule); border-radius:6px; overflow:hidden; }
.seg button { font:inherit; font-size:13px; color:var(--dim); background:transparent; border:0; padding:6px 14px; cursor:pointer; }
.seg button[aria-pressed="true"] { background:var(--ink); color:var(--bg); }
.seg button:focus-visible { outline:2px solid var(--dim); outline-offset:-2px; }
.tools { justify-content:flex-end; }
@media (max-width:260px) { #d { display:none; } .tools { justify-content:flex-start; } }
</style></head><body>
<div class="tools"><span id="d"></span><div class="seg" role="group" aria-label="מצב תצוגה"><button type="button" id="b-day" aria-pressed="true">יום</button><button type="button" id="b-night" aria-pressed="false">לילה</button></div></div>
<script>
(function () {
  var KEY = 'dr_theme', P = window.parent, proot;
  try { proot = P.document.documentElement; } catch (e) { proot = null; }
  var day = document.getElementById('b-day'), night = document.getElementById('b-night');
  function stamp() { try { var d = new Date(); document.getElementById('d').innerHTML = new Intl.DateTimeFormat('he-IL', { weekday: 'long' }).format(d) + ' · <span class="num">' + String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + String(d.getFullYear()).slice(-2) + '</span> · <span class="num">' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') + '</span>'; } catch (e) {} }
  stamp(); setInterval(stamp, 15000);
  function stored() { try { return P.localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(t) { if (!proot) return; if (t) proot.setAttribute('data-theme', t); else proot.removeAttribute('data-theme'); }
  if (stored()) set(stored());
  function eff() { var t = proot && proot.getAttribute('data-theme'); if (t) return t; try { return P.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch (e) { return 'light'; } }
  function sync() { var t = eff(); document.documentElement.setAttribute('data-theme', t); day.setAttribute('aria-pressed', String(t !== 'dark')); night.setAttribute('aria-pressed', String(t === 'dark')); }
  function choose(t) { set(t); try { P.localStorage.setItem(KEY, t); } catch (e) {} sync(); }
  day.addEventListener('click', function () { choose('light'); });
  night.addEventListener('click', function () { choose('dark'); });
  sync();
  if (proot && window.MutationObserver) new MutationObserver(sync).observe(proot, { attributes: true, attributeFilter: ['data-theme'] });
})();

(function () {
  // מעבר טאב: מסתירים את התוכן הדהוי של הטאב הקודם כבר ברגע הלחיצה (ולא רק כשהסקריפט מגיע לכותרת), עד שהריצה מסתיימת
  try {
    var D = window.parent.document;
    if (!D.getElementById('dr-nav-css')) {
      var st = D.createElement('style'); st.id = 'dr-nav-css';
      st.textContent = 'html[data-dr-nav] [data-testid="stMain"] [data-stale="true"] { display: none !important; }';
      D.head.appendChild(st);
    }
    if (!window.parent.__drNavHook) {
      window.parent.__drNavHook = true;
      D.addEventListener('click', function (e) {
        var b = e.target && e.target.closest && e.target.closest('[class*="st-key-navtab_"] button');
        if (!b) return;
        var root = D.documentElement; root.setAttribute('data-dr-nav', '1');
        var t0 = Date.now(), quiet = 0;
        var iv = setInterval(function () {
          var running = !!D.querySelector('[data-testid="stStatusWidget"]');
          quiet = running ? 0 : quiet + 1;
          if ((quiet >= 3 && Date.now() - t0 > 900) || Date.now() - t0 > 90000) { root.removeAttribute('data-dr-nav'); clearInterval(iv); }
        }, 300);
      }, true);
    }
  } catch (e) {}
})();
</script></body></html>"""

_V3_BRAND_HTML = (
    '<a class="v3brand" href="./" target="_self">'
    '<svg width="24" height="24" viewBox="0 0 22 22" aria-hidden="true">'
    '<circle cx="11" cy="11" r="9.5" fill="none" stroke-width="1.3"/><circle cx="11" cy="11" r="5" fill="none" stroke-width="1"/>'
    '<circle class="dot" cx="16" cy="6.5" r="2"/></svg>DipRadar</a>'
)




st.set_page_config(page_title="DipRadar", layout="wide")

# אתר בודק עם משתמש (TESTER_USER): נתוני הבודק נשמרים בריפו פרטי כדי שלא יימחקו כשהשרת מתאפס (src/user_sync.py).
# חייב לרוץ לפני כל פתיחת DB - הורדה אחת בתהליך, ואז דחיפה ברקע של כל שינוי.
try:
    from src import config as _config_mod, user_sync as _user_sync
    _tester_user_active = _config_mod.tester_mode() and bool(_config_mod.tester_user())
except Exception as _us_err:
    print(f"user_sync import failed: {_us_err}")
    _tester_user_active = False

# כניסה בקוד אישי: כבויה כברירת מחדל (19.11.2026, החלטת הבעלים - הכתובות לא מפורסמות). להפעלה: TESTER_LOGIN=1 ב-Secrets של האתר
if _tester_user_active and _user_sync.configured() and os.environ.get("TESTER_LOGIN", "").strip() == "1":
    _tu = _config_mod.tester_user()
    if st.session_state.get("tester_auth_user") != _tu:
        st.markdown(
            '<div dir="rtl" style="max-width:420px;margin:12vh auto 0;text-align:center">'
            '<h2>DipRadar</h2><p>הכנס את קוד הגישה האישי שלך</p></div>', unsafe_allow_html=True,
        )
        with st.form("tester_login"):
            _code = st.text_input("קוד גישה", type="password", label_visibility="collapsed", placeholder="xxxx-xxxx-xxxx")
            _go = st.form_submit_button("כניסה", use_container_width=True)
        if _go:
            try:
                _login = _user_sync.attempt_login(_tu, _code)
            except Exception:
                _login = "error"
            if _login == "ok":
                st.session_state["tester_auth_user"] = _tu
                st.rerun()
            elif _login == "locked":
                st.error("יותר מדי ניסיונות. נסה שוב בעוד כמה דקות.")
            elif _login == "error":
                st.error("שגיאת חיבור. נסה שוב.")
            else:
                st.error("קוד שגוי.")
        st.stop()

# אתר בודק עם משתמש: הורדה אחת של הנתונים בתהליך + דחיפה ברקע (אחרי כניסה; חייב לרוץ לפני כל פתיחת DB)
try:
    if _tester_user_active:
        _user_sync.init_tester(
            _config_mod.tester_user(), store.user_db_path(os.path.join(ROOT_DIR, "alerts_tester.db")),
            extras={"config.yaml": CONFIG_PATH, "prefs.json": os.path.join(ROOT_DIR, "tester_prefs.json"),
                    ".ui_prefs.json": _UI_PREFS_FILE},  # גם זכירת הסינונים בטאבים (כמו אצלך מקומית)
        )
except Exception as _us_err:
    print(f"user_sync init failed: {_us_err}")

# מניעת הבזק של העיצוב הישן בטעינה (נייד): התוכן מוסתר עד שה-CSS של v3 נטען (שורה אחת למטה מבטלת את ההסתרה);
# אם משהו נכשל באמצע - אחרי 4 שניות הכל מוצג בכל מקרה
st.markdown(
    "<style>[data-testid='stMain'], [data-testid='stSidebar'] { opacity: 0; animation: drReveal .01s 4s forwards; } "
    "@keyframes drReveal { to { opacity: 1; } }</style>",
    unsafe_allow_html=True,
)

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
def _pts_chip(pts: int) -> str:
    """תג נקודות (+2 / -1) - כיווניות LTR מבודדת, כך שהסימן תמיד לפני המספר ומחוץ לזרימת העברית;
    רוחב קבוע ורקע בצבע, כדי שיקראו ברור וביישור אחיד (7.10.2026)."""
    color = POS_COLOR if pts > 0 else NEG_COLOR
    sign = "+" if pts > 0 else "\u2212"
    return (
        f'<span style="display:inline-block; min-width:30px; text-align:center; direction:ltr; unicode-bidi:isolate; '
        f'font-weight:800; border-radius:6px; padding:0 5px; background:{color}22; color:{color};">{sign}{abs(pts)}</span>'
    )




SIGNAL_COLORS = {"buy": POS_COLOR, "wait": "#C98A00", "avoid": NEG_COLOR, "unknown": "#7A8591"}  # צבעי הרמזור (🟢/🟡/🔴)
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




def _sb_title(text: str, cls: str = "") -> None:
    """כותרת סעיף בסיידבר: v3 = כותרת נקייה בלי אימוג'י (מוקאפ שאושר); אחרת מודגש כמו קודם."""
    st.markdown(f'<div class="v3sbt {cls}">{html.escape(text.partition(" ")[2] or text)}</div>', unsafe_allow_html=True)


def _nm(label: str) -> str:
    """תווית עם אימוג'י מוביל: ב-v3 בלי האימוג'י."""
    return label.partition(" ")[2]


def _signed_num(value: float, decimals: int = 0, suffix: str = "") -> str:
    """מספר עם סימן (+/-) שנשאר לפני המספר גם בתוך טקסט עברי (RTL) - עוטף
    ב-LRM (סימן כיווניות שקוף) כדי למנוע היפוך ויזואלי של הסימן ע"י מנועי טקסט."""
    if round(value, decimals) == 0:  # "-0.0%" / "+0.0%" מבלבל - אפס בלי סימן
        return f"‎{0:,.{decimals}f}{suffix}"
    return f"‎{value:+,.{decimals}f}{suffix}"




def _level_text(value: float, is_il: bool, usd: bool = False) -> str:
    """שער יעד/סטופ/לימיט (לא נתוני אמת): מספר עגול - מ-100 ומעלה לעשרות הקרובות, מתחת לשלם. ת"א באגורות."""
    v = value * 100 if is_il else value
    v = round(v / 10) * 10 if abs(v) >= 100 else round(v)
    return f"${v:,.0f}" if usd else f"{v:,.0f}"


def _price_text(value, index_name, whole: bool = False) -> str:
    """שער (לא סכום כסף כולל) לפי מדד - ת"א נסחר באגורות (ולא בש"ח עשרוני),
    בדיוק כמו שכבר נהוג בכל שאר האתר (למשל _format_price ב-scanner.py, וכרטיס
    האחזקה בטאב "אחזקות") - כדי שאפשר יהיה להשוות ישירות למסך הברוקר. משותף בין
    כל מקום בדשבורד שמציג שער בודד של מניה, כדי לא לשכפל את הבדיקה שוב ושוב.
    whole=True: שערי יעד/סטופ/לימיט (לא נתוני אמת) - מספר שלם."""
    if pd.isna(value):
        return "—"
    ccy = constituents.INDEX_CURRENCY.get(index_name, "ILS")
    if whole:
        return _level_text(value, ccy == "ILS", usd=ccy != "ILS")
    if ccy == "ILS":
        return f"{value*100:,.0f}"
    return f"${value:,.2f}"









@st.cache_data(ttl=60)
def get_current_price(ticker: str) -> float | None:
    """מחיר עדכני אמיתי לטיקר בודד (regularMarketPrice) - בשימוש לאחזקות בפועל,
    כי ל-fetch_universe_daily_changes (הורדה בבת אחת להרבה טיקרים) יש לפעמים
    פער/עיכוב בנתון היומי, ואצל אחזקות שלך זה קריטי (בשונה מרשימת "מניות מובילות")."""
    return market_data.fetch_current_price(ticker)


_PRICE_POOL = None


def _price_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _PRICE_POOL
    if _PRICE_POOL is None:
        _PRICE_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="price")
    return _PRICE_POOL


@st.cache_data(ttl=60)
def get_current_prices_batch(tickers: tuple[str, ...]) -> dict[str, float | None]:
    """כמו get_current_price, אבל לכמה טיקרים במקביל (ThreadPoolExecutor) -
    נקרא פעם אחת עם כל הטיקרים של האחזקות, כדי לא לחכות לכל אחד בתור (כל
    אחד עד כמה שניות, כולל ניסיונות חוזרים) - זו הייתה הסיבה המרכזית לאיטיות
    שדווחה אחרי restart/מעבר טאב (9.9.2026)."""
    if not tickers:
        return {}
    # בריכת threads אחת קבועה לכל התהליך (לא בריכה חדשה בכל קריאה): בענן התהליך חי ימים, וקריאות שנתקעות על רשת (Yahoo
    # עם חורים בנתונים) היו מצטברות threads עד "can't start new thread" (קריסת האתר הציבורי, 29.10.2026 וגם 24.9)
    results = list(_price_pool().map(market_data.fetch_current_price, tickers))
    return dict(zip(tickers, results))


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
            # תקרת מרחק (strategy.MAX_STOP_DISTANCE_PCT) - לפוזיציות חדשות; אחזקות קיימות שומרות את הסטופ שנקבע בקנייה
            return round(max(entry_price - ATR_STOP_MULTIPLIER * atr,
                             entry_price * (1 - strategy_mod.MAX_STOP_DISTANCE_PCT / 100)), 2)
    return round(entry_price * STOP_LOSS_FACTOR, 2)


def get_or_backfill_stop_price(holding_row: dict, entry_price: float) -> float:
    """קו הסטופ השמור לאחזקה - ואם אין (אחזקה שנקנתה לפני שהמנגנון הזה נוסף),
    מחשב פעם אחת עכשיו ושומר, כדי שמאותו רגע הוא יהיה קבוע גם היא, בלי צורך
    לחשב מחדש בכל טעינה."""
    stored = holding_row.get("holding_stop_price")
    # pd.notna: NULL מה-DB מגיע מ-pandas כ-NaN, שהוא truthy - בלי הבדיקה הזו הסטופ הוצג "nan"
    if stored is not None and pd.notna(stored) and stored:
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


def get_holding_range(ticker: str, bought_at, entry) -> tuple[float, float] | None:
    """הטוב והגרוע ביותר מאז הקנייה: (שיא %, שפל %) יחסית לשער הכניסה, לפי סגירות יומיות מהקנייה ועד היום."""
    if not entry:
        return None
    series = get_sparkline_series(ticker, 80)
    if series.empty:
        return None
    try:
        bought = dt.datetime.fromisoformat(str(bought_at)).date() if bought_at else None
    except ValueError:
        bought = None
    if bought is None:
        return None
    idx = pd.to_datetime(series.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    vals = series[idx.date >= bought]
    if vals.empty:
        return None
    return (float(vals.max()) / entry - 1) * 100, (float(vals.min()) / entry - 1) * 100


def get_holding_sparkline(ticker: str, bought_at) -> list:
    """גרף אחזקה: מהקנייה (פחות 3 ימי מסחר של הקשר) עד היום; מוגבל להיסטוריה הזמינה (3 חודשים), לפחות 8 נקודות."""
    series = get_sparkline_series(ticker, 80)
    if series.empty:
        return []
    try:
        bought = dt.datetime.fromisoformat(str(bought_at)).date() if bought_at else None
    except ValueError:
        bought = None
    if bought is None:
        return series.tail(15).tolist()
    idx = pd.to_datetime(series.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    n_after = int((idx.date >= bought).sum())
    return series.tail(max(n_after + 3, 8)).tolist()

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
        overflow: hidden;
    }
    /* תיקון באג נוסף (29.9.2026, אותו דיווח "ביטלת את האפשרות לעלות למעלה
    ולרדת מטה, יש מידע לא זמין"): פתיחת הסיידבר עצמו (לא expander בתוכו -
    ר' תיקון stExpanderDetails למטה) עוברת אנימציית CSS transition
    (transform/min-width/max-width, 300ms) בין מצב מכווץ למצב פתוח - אם
    ה-transition נתקע (למשל הטאב היה ברקע/לא פעיל כשהיא רצה, אז ה-rAF
    שמניע אותה קופא), הסיידבר נשאר תקוע ויזואלית במצב מכווץ (width:0,
    translateX(-300px)) גם ש-aria-expanded כבר "true" - כאילו לא נפתח
    בכלל, אין מה לגלול. מבטלים את ה-transition לגמרי כדי שהמעבר יקרה
    מיידית ולא ייתקע באמצע. */
    [data-testid="stSidebar"] {
        transition: none !important;
    }
    [data-testid="stSidebar"][aria-expanded="true"] {
        transform: none !important;
        min-width: 200px !important;
        max-width: 337.5px !important;
        width: 300px !important;
    }
    /* Streamlit עובר בעצמו ל"מצב מובייל" (עמודות נערמות זו מתחת לזו במקום
    זו לצד זו) כשהחלון הכולל צר - שבר את שורות "value + יחידה" (%/ימים)
    בסיידבר, שאמורות תמיד להישאר צמודות זו לזו באותה שורה בלי קשר לרוחב
    החלון (הסיידבר עצמו קבוע 300px ממילא, "מובייל" לא רלוונטי כאן -
    14.9.2026, "מה עם זה למשל" עם צילום שהראה % ו-ימים נופלים לשורה נפרדת). */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
    }
    [data-testid="stSidebar"] [data-testid="stColumn"] {
        min-width: 0 !important;
    }
    /* ידית הגרירה לשינוי רוחב הסיידבר (הפס הדק בקצה) - אין לה data-testid
    יציב בגרסת Streamlit הזו, אז מזהים אותה לפי cursor:col-resize שהיא
    היחידה שנושאת. ממילא הרוחב קבוע (300px, למעלה) אז לגרירה אין תועלת
    אמיתית. שים לב: מזהה עצם הידית (class מבוסס-hash של Streamlit) עלול
    להשתנות בעדכון Streamlit עתידי - אם זה יחזור להופיע, זה כנראה למה.
    (14.9.2026 - זו התברר *לא* להיות הידית ש"הסרגל של למעלה/למטה" התכוון
    אליה בפועל; ר' stSidebarContent למטה לזו האמיתית). */
    [data-testid="stSidebar"] > div > div:only-child:not([data-testid]) {
        display: none;
    }
    /* גלילה אנכית חזרה לפעול (14.9.2026, "אני מבין עכשיו למה צריך לרדת
    למטה עם הסייד בר. תחזיר את זה") - בוטל אחרי שכבוי-גלילה לגמרי (ניסיון
    קודם, אותו יום) התברר כלא נכון: תוכן הסיידבר גבוה מהמסך, אז בלי גלילה
    חלק מהתוכן פשוט נחתך ולא נגיש. רק פס הגלילה החזותי נשאר מוסתר. */
    [data-testid="stSidebarContent"] {
        overflow-y: auto;
        scrollbar-width: none;
    }
    [data-testid="stSidebarContent"]::-webkit-scrollbar {
        display: none;
    }
    /* תיקון באג: כשפותחים expander בסיידבר (למשל "מעקב אחזקות"), Streamlit
    מאנימץ את הפתיחה ע"י height מפורש + overflow:hidden ב-inline style על
    ה-<details>, ואמור לחזור ל-height:auto בסיום האנימציה - אבל בפועל זה
    נתקע על height הסגור (~40px) אחרי הפתיחה, כך שהתוכן שבפנים מצויר במלואו
    ב-DOM אבל נחתך חזותית ולא נגיש/לא ניתן לגלול אליו ("ביטלת את האפשרות
    לעלות למעלה ולרדת מטה, יש מידע לא זמין" - 29.9.2026). !important כדי
    לגבור על ה-inline style הלא-important של Streamlit. */
    [data-testid="stExpander"] details[open] {
        height: auto !important;
        overflow: visible !important;
    }
    /* ה-expanders בסיידבר (מעקב אחזקות/השקעה וסיכון/עמלות ומיסים/סוגי
    התראה) נראים "נכנסים אחד לתוך השני" (30.9.2026) - ל-Streamlit יש
    margin-top: -7px כברירת מחדל על ה-wrapper של כל block, כדי לצמצם רווח
    בין אלמנטים, אבל ביחד עם ה-gap:4px של העמודה זה יוצא overlap שלילי של
    3px בין כל שני expanders - הפינות המעוגלות (border-radius:8px) של כל
    קופסה חופפות לקופסה שמתחתיה. מכריחים רווח חיובי במקום. */
    [data-testid="stSidebar"] [data-testid="stLayoutWrapper"]:has([data-testid="stExpander"]) {
        margin-top: 8px !important;
    }
    /* רווחים אחידים בין כרטיסי הסיידבר (14.10.2026, "הרווחים בסייד בר לא זהים"): הכלל למעלה הוסיף 8px גם ל-wrapper של
       כרטיס שלם שמכיל expander (לא רק ל-expander עצמו), כך שבין כרטיס ההגדרות לכרטיס הקבוצות יצא 21px ובין השאר 13px.
       בין כל שני כרטיסים עכשיו 12px, כמו בין ה-expanders שבתוך הכרטיס. */
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] { gap: 12px !important; }
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
        margin-top: 0 !important;
    }
    /* תווית ("ש"ח"/"$") ושדה המספר מתחתיה מיושרים לאותו קצה: לשדה היה ריפוד פנימי של 8px מימין, והתווית ללא - הערך
       ישב 9px פנימה מהתווית שמעליו */
    [data-testid="stSidebar"] [data-testid="stNumberInput"] input { padding-right: 0 !important; }
    /* בלי overflow:hidden כאן, כשה-JS של Streamlit מכווץ את הסיידבר (מסך צר/
    מובייל - aria-expanded="false", width:0 + transform), התוכן הפנימי שלו
    (שמניח 300px רוחב) ממשיך "לדלוף" ונראה כפס טקסט אנכי דחוס בקצה המסך -
    כנראה כי כיוון ה-transform מניח LTR ולא מזיז את הסיידבר RTL הזה מספיק
    רחוק אל מחוץ למסך (1.9.2026). */
    [data-testid="stSidebarHeader"] {
        /* 28px, לא 8px - זה בדיוק גובה כפתור הכיווץ (stSidebarCollapseButton)
        שממורכז בתוכו; אם ה-header נמוך יותר מהכפתור, הוא נחתך מלמעלה (ובגלל
        ה-overflow:hidden על stSidebar עצמו, ר' למטה, נעלם לגמרי - 2.9.2026). */
        height: 28px;
        min-height: 0px;
    }
    div[class*="st-key-nav_tabs_row"] {
        border: 1px solid rgba(128,128,128,0.3);
        border-right: 3px solid #3B6EA5;
        border-left: 3px solid #3B6EA5;
        border-radius: 12px;
        padding: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }
    /* 28.9.2026, "עדיין לא ממורכז (גובה)": הקונטיינר עצמו (st-key-nav_tabs_row)
    הוא stVerticalBlock עם שני ילדים - ה-<style> שמוזרק כאן (element בגובה 0,
    בלתי נראה) ואז שורת הכפתורים. הפער האוטומטי של Streamlit בין אלמנטים
    (gap:16px, נמדד בפועל) נכנס *בין* שני הילדים - כלומר מעל שורת הכפתורים
    בלבד, לא מתחתיה - שדוחף אותה ויזואלית למטה בתוך תיבת ה-padding (8px למעלה
    הופך בפועל ל-24px, 8px למטה נשאר 8px). gap:0 מבטל את הפער הזה מהשורש. */
    div[class*="st-key-nav_tabs_row"] > [data-testid="stVerticalBlock"],
    div[class*="st-key-nav_tabs_row"][data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    div[class*="st-key-navtab_"] button {
        /* 28.9.2026: היה 1.25rem/16px 22px מאז ה-commit הראשון - הפס עצמו
        תמיד היה "מרווח" מבחינת גובה, ה-nowrap (למטה) רק תיקן חוסר-אחידות
        בין כפתורים, לא את זה. הוקטן בפועל בעקבות משוב חוזר ("עדיין נראה
        אותו הדבר" אחרי תיקון ה-nowrap) שהגובה הכולל של הפס עדיין גבוה
        מדי - 0.95rem/9px 18px. */
        font-size: 0.95rem;
        padding: 9px 18px;
        border-radius: 8px;
        border: none;
        box-shadow: none;
        /* "הטאבים לא ממורכזים ביחד לגובה": תוויות באורכים שונים (עם/בלי
        אימוג'י+מילה אחת נוספת) נשברות למספר שורות שונה כל אחת לפי רוחב
        העמודה שקיבלה - נמדד בפועל (getBoundingClientRect): גובה כפתור נע
        בין 99px (שורה אחת, "התראות") ל-166px ("ביצועי אסטרטגיה", שתי
        שורות) - גובה השורה כולה נקבע לפי הגבוה מביניהם, והקצרים נשארים
        עליונים בתוכה במקום ממורכזים. nowrap מבטל את פערי-הגובה מהשורש. */
        white-space: nowrap;
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
    /* הכותרת העליונה של Streamlit (Deploy/Stop) אטומה בגובה 60px ומכסה את מה שמתחתיה - מקצרים אותה כדי שהלוגו יעלה למעלה
       (13.10.2026); הלוגו חייב להתחיל מתחתיה, אחרת הוא נעלם מאחוריה */
    header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 0 !important; }
    [data-testid="stMainBlockContainer"] {
        padding-top: 2.5rem;
    }
    /* ריווח אחיד בכל האתר (13.10.2026, "תצמצם קצת רווחים בכל האתר בצורה שווה וזהה"): רווח בין אלמנטים 12px במקום 16px,
       וקווי הפרדה (st.divider) עם אותו שוליים בכל מקום */
    [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }
    [data-testid="stMainBlockContainer"] hr { margin: 0.5rem 0 !important; }
    /* iframe עזר בגובה 0 בראש העמוד - מוציאים מזרימת העמוד כדי שלא יוסיף רווח של 16px מעל הלוגו */
    [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:first-child:has(> iframe) {
        position: absolute !important;
    }
    /* שני בלוקי ה-CSS הראשונים בעמוד ריקים ויזואלית אבל כל אחד מוסיף רווח של 16px מעל הלוגו (13.10.2026) */
    [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:nth-child(-n+2):has(style) {
        display: none !important;
    }
    div[class*="st-key-market_panel"] {
        padding: 8px 16px !important;
        gap: 10px !important;
    }
    /* בלוקי ה-CSS שמתחת לשורת הטאבים ריקים ויזואלית אבל כל אחד מוסיף רווח של 16px - מסתירים אותם (13.10.2026,
       "אפשר לצמצם קצת גם כאן?"). ה-<style> שבתוכם ממשיך לפעול גם כשהמיכל מוסתר */
    [data-testid="stLayoutWrapper"]:has(.st-key-nav_tabs_row) + [data-testid="stElementContainer"]:has(style),
    [data-testid="stLayoutWrapper"]:has(.st-key-nav_tabs_row) + [data-testid="stElementContainer"]:has(style)
        + [data-testid="stElementContainer"]:has(style) { display: none !important; }
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
    /* חריגה מכוונת לכלל ה-RTL הכללי למעלה - השורה התחתונה (הקטנה) בכרטיסי
    "התיק שלי" (render_portfolio_card/render_value_card/render_proximity_card)
    צמודה לשמאל בכוונה, לא לימין כמו שאר הטקסט - סלקטור מורכב יותר (לא רק
    ".card-bottom-line") כדי לנצח בוודאות את הכלל הכללי, לא להסתמך על סדר
    ה-DOM (9.9.2026, בעקבות בקשה מפורשת). */
    [data-testid="stMarkdownContainer"] .card-bottom-line {
        text-align: left !important;
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
    /* כפתורי הניקוי/פתיחה של המדדים "צפים" באמצע - נמדד בפועל
    (getBoundingClientRect): align-items:flex-start על ה-parent המשותף לא
    השפיע בכלל, כי לכפתורים עצמם יש align-self מפורש משלהם שדורס את זה.
    מיישרים את הכפתורים עצמם (14.9.2026, "משהו שם לא מסתדר לי בויזואל"). */
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] button[aria-label*="Clear"],
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] button[aria-label*="Open"] {
        align-self: flex-start !important;
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

with st.container(key="main_title_wrap"):
    # מיתוג (29.9.2026, "כותרת במילה אחת והסבר קצר בכמה מילים") - "DipRadar"
    # נבחר אחרי כמה סבבים (ריבאונד רדאר -> בוטל -> DipRadar/SnapBack/Rebound
    # -> "פחות זה יותר", מילה אחת בלי כפילות). HTML מותאם במקום st.title,
    # כדי לשלוט בגודל/ריווח-אותיות/צבע כמו לוגו אמיתי, לא כותרת h1 רגילה.
    st.markdown(
        f"""
        <div style="padding:6px 0 2px;">
          <a href="./" target="_self" style="text-decoration:none; color:{ACCENT_COLOR}; cursor:pointer; display:block;">
            <div style="font-size:2.3rem; font-weight:800; letter-spacing:0.02em; color:{ACCENT_COLOR}; line-height:1.25; display:flex; justify-content:center;">DipRadar</div>
          </a>
          <div style="font-size:0.95rem; font-weight:500; opacity:0.55; margin-top:2px; display:flex; align-items:center; justify-content:center; gap:5px;">
            <span>התראות ואסטרטגיית ריבאונד</span>
            <svg width="16" height="16" viewBox="0 0 24 24" style="flex-shrink:0;">
              <polyline points="2,18 9,11 13,15 22,4" fill="none" stroke="{ACCENT_COLOR}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              <polyline points="15,4 22,4 22,11" fill="none" stroke="{ACCENT_COLOR}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

_TAB_DEFS = [
    # סדר מקורי - ניסיון להעביר "מניות מובילות" למקום הרביעי (30.9.2026)
    # בוטל באותו יום: "תחזיר למצב הקודם."
    ("movers", "🔝 מניות מובילות"),
    ("today", "🔔 התראות"),
    ("portfolio", "💰 אחזקות"),
    ("history", "📋 יומן עסקאות"),
    ("backtest", "📈 ביצועי אסטרטגיה"),
]
if "active_tab" not in st.session_state:
    # None בכוונה - נוסה ברירת מחדל "today" (30.9.2026, בעקבות ביקורת חיצונית
    # על DipRadar) ובוטל באותו יום: "אני לא אוהב את זה. תחזיר למצב הקודם."
    st.session_state.active_tab = None

with st.container(key="nav_tabs_row"):
    # מובייל (28.9.2026, "פוליש מובייל"): 5 הכפתורים ב-st.columns נערמים זה
    # מתחת לזה במסך צר (אין ל-Streamlit breakpoint רספונסיבי לזה) - שורת
    # ניווט אחת הופכת לחמש שורות ענקיות שתופסות את רוב המסך לפני שמגיעים
    # לתוכן. nowrap+overflow-x:auto - נשארים שורה אחת אופקית וגוללים.
    st.markdown(
        """
        <style>
        @media (max-width: 480px) {
            /* 5.10.2026: שורה אחת גוללת הסתירה 2 מ-5 הטאבים מחוץ למסך בלי שום רמז.
            עכשיו 3+2 בשתי שורות - הכל גלוי בלי גלילה. */
            div[class*="st-key-nav_tabs_row"] [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important; gap: 6px !important;
            }
            div[class*="st-key-nav_tabs_row"] [data-testid="stColumn"] {
                width: auto !important; min-width: 0 !important;
                flex: 1 1 calc(33.33% - 6px) !important;
            }
            div[class*="st-key-nav_tabs_row"] button {
                white-space: nowrap !important; padding-left: 3px !important; padding-right: 3px !important;
                font-size: 0.82rem !important;
            }
            div[class*="st-key-nav_tabs_row"] button p, div[class*="st-key-nav_tabs_row"] button div { font-size: inherit !important; }
            /* מסך צר (360px ומטה): "מניות מובילות" נחתך בכפתור - גופן וריפוד קטנים עוד יותר (14.10.2026) */
            @media (max-width: 380px) {
                div[class*="st-key-nav_tabs_row"] button { font-size: 0.74rem !important; padding-left: 2px !important; padding-right: 2px !important; }
            }
        }
        </style>
        """.replace("</style>", _V3_CSS + f"/* dipradar-build {globals().get('_DIPRADAR_BUILD', 'none')} */</style>"),
        unsafe_allow_html=True,
    )
    # עמודה ראשונה = לוגו, אחרונה = מרווח גמיש; הטאבים באמצע (ר' _V3_CSS)
    _all_nav_cols = st.columns([1] * (len(_TAB_DEFS) + 2), gap="small")
    with _all_nav_cols[0]:
        st.markdown(_V3_BRAND_HTML, unsafe_allow_html=True)
    _nav_cols = _all_nav_cols[1:1 + len(_TAB_DEFS)]
    with _all_nav_cols[-1]:
        components.html(_V3_TOOLS_HTML, height=40)
    for _nav_col, (_nav_key, _nav_label) in zip(_nav_cols, _TAB_DEFS):
        with _nav_col:
            if st.button(
                _nav_label.partition(" ")[2], key=f"navtab_{_nav_key}", width='stretch',
                type="primary" if st.session_state.active_tab == _nav_key else "secondary",
            ):
                st.session_state.active_tab = None if st.session_state.active_tab == _nav_key else _nav_key
                st.session_state["_nav_fresh"] = True  # מעבר טאב: הכותרת של הטאב החדש מסתירה שאריות דהויות של הטאב הקודם
                st.rerun()


# מובייל (5.10.2026): שורות של 4 כרטיסים (מדדים, תיק) נערמו כל אחד במסך שלם -
# שלושה מסכים רק כדי לראות 4 מדדים. עכשיו רשת 2x2 למדדים בלבד - כרטיסי התיק
# (card-bottom-line) צרים מדי לשתי עמודות ונשארים בעמודה אחת.
st.markdown(
    """
    <style>
    /* אייקון "קישור לכותרת" של Streamlit (מופיע ברחיפה מעל כותרות) - לא שימושי בדשבורד (15.10.2026) */
    [data-testid="stHeaderActionElements"] { display: none !important; }
    @media (max-width: 480px) {
        /* כרטיסי התיק: במקום ארבעה כרטיסים גבוהים בעמודה (125px כל אחד) - כרטיס קומפקטי עם הערך בצד אחד והתווית
           והשורה התחתונה בצד השני (13.10.2026). 2x2 נבדק ונדחה: הכרטיס צר מדי לערכים כמו 30,388 ש"ח */
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.card-bottom-line) div[style*="height: 125px"] {
            display: grid !important; grid-template-columns: 1fr auto; grid-template-areas: "label value" "bottom value";
            align-items: center; column-gap: 12px; row-gap: 0; height: auto !important; min-height: 0 !important;
            padding: 10px 14px !important; text-align: right !important; justify-content: stretch !important;
        }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.card-bottom-line) div[style*="height: 125px"] > div { margin-top: 0 !important; }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.card-bottom-line) div[style*="height: 125px"] > div:nth-child(1) { grid-area: label; font-size: 0.82rem !important; }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.card-bottom-line) div[style*="height: 125px"] > div:nth-child(2) { grid-area: value; font-size: 1.35rem !important; text-align: left; max-width: 170px; }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.card-bottom-line) div[style*="height: 125px"] > div:nth-child(3) { grid-area: bottom; font-size: 0.8rem !important; text-align: right !important; }
        [data-testid="stMain"] h3 { font-size: 1.3rem !important; }
        [data-testid="stMain"] div[class*="st-key-chart_card_pnl"],
        [data-testid="stMain"] div[class*="st-key-chart_card_comparison"] { min-height: 0 !important; }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(4):last-child):not(:has(.card-bottom-line)) {
            flex-wrap: wrap !important; gap: 10px !important;
        }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(4):last-child):not(:has(.card-bottom-line)) > [data-testid="stColumn"] {
            flex: 1 1 calc(50% - 10px) !important; width: auto !important; min-width: 0 !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
# כפתור ה-"✕" (ניקוי) בתוך number_input ריק (value=None) קיבל רוחב מלא (370px) מכלל כפתורים
# גלובלי, וכיווץ את תיבת הטקסט ל-0 - אי אפשר היה לראות/להקליד (7.10.2026, "אי אפשר לכתוב").
st.markdown(
    """
    <style>
    [data-testid="stNumberInput"] button:has(> svg) {
        width: auto !important; min-width: 0 !important; flex: 0 0 auto !important;
    }
    /* כפתורי +/- בשדות מספר: מצב ה-hover/focus הכחול (צבע ראשי) "נתקע" אחרי לחיצה, ולפעמים נראה על שני הכפתורים יחד
       (14.10.2026). רק hover בפועל מקבל גוון עדין; focus/active אחרי לחיצה נשארים שקופים */
    [data-testid="stNumberInputContainer"] button:focus,
    [data-testid="stNumberInputContainer"] button:focus-visible,
    [data-testid="stNumberInputContainer"] button:active {
        background: transparent !important; color: inherit !important; box-shadow: none !important; outline: none !important;
    }
    @media (hover: hover) {
        [data-testid="stNumberInputContainer"] button:hover:enabled:not(:focus) {
            background: rgba(59,110,165,0.15) !important; color: #3b6ea5 !important;
        }
    }
    @media (hover: none) {
        [data-testid="stNumberInputContainer"] button:hover { background: transparent !important; color: inherit !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
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
strategy_mod.configure(cfg)  # בורר אסטרטגיה (מתג strategy_selector) - בלי המתג: ברירות מחדל = המצב הקודם


def _no_trading_today(country: str) -> bool:
    """True רק ביום שבו אין מסחר בכלל בשוק הזה (סוף שבוע/חג) - ביום מסחר שנסגר הנתון הוא של היום ולא מוסיפים תאריך."""
    from zoneinfo import ZoneInfo
    return not is_trading_day(country, dt.datetime.now(ZoneInfo(MARKET_HOURS[country]["tz"])).date())


def _daily_label_with_date(base: str, date_label: str, country: str = "IL") -> str:
    """"שינוי יומי" + תאריך הסגירה האחרונה כשהנתון אינו של היום (סוף שבוע/חג, וגם ביום מסחר לפני הפתיחה);
    ביום מסחר שהתקיים (גם אחרי הסגירה) הנתון הוא של היום - בלי תאריך עד סוף היום."""
    return base if date_label == "היום" else f"{base} {date_label}"


def _sync_and_warn(reason: str, include_db: bool = False) -> None:
    """עוטף cloud_sync.sync_to_cloud. בלי הודעה למשתמש על כישלון - ברוב המקרים
    זה סתם התנגשות חולפת עם דחיפת הבוט שמתאזנת לבד בניסיון החוזר הפנימי, וגם
    כשלא, השינוי המקומי לא הולך לאיבוד (ידחף עם הסנכרון הבא). כישלון אמיתי
    עדיין מתועד ב-log לצורך אבחון (ר' cloud_sync.sync_to_cloud)."""
    if _tester_user_active:
        _tester_publish_prefs()  # הבחירות של הבודק בסיידבר -> קובץ ההעדפות שהסורק קורא (נדחף לריפו הפרטי ברקע)
    cloud_sync.sync_to_cloud(reason, include_db=include_db)


def _tester_publish_prefs(**updates) -> None:
    """כותב את prefs.json המקומי של הבודק מההגדרות שבסיידבר שלו (cfg) + שדות שאין להם מקבילה בסיידבר (רמת סיגנל)."""
    try:
        _path = os.path.join(ROOT_DIR, "tester_prefs.json")
        _existing = _user_sync.read_local_prefs(_path) if os.path.exists(_path) else {}
        _existing.update(updates)
        _user_sync.write_local_prefs(_path, _user_sync.prefs_from_cfg(cfg, _existing))
    except Exception as _pp_err:
        print(f"tester prefs write failed: {_pp_err}")


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






@st.cache_data(ttl=15)
def load_alerts(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    conn = store.get_conn(path)
    df = store.read_alerts_df(conn, order="scan_ts DESC")
    conn.close()
    if "company_name" in df.columns:
        df["company_name"] = df["company_name"].map(fix_name)
    return df


df = load_alerts(db_path(cfg))

ALL_INDICES = ["SP500", "NASDAQ100", "TA35", "TA125"]
SCAN_INDEX_ORDER = ["TA35", "TA125", "NASDAQ100", "SP500"]  # סדר קבוע בבורר המדדים לסריקה בסיידבר: ת"א ואז אמריקאי
INDEX_LABELS = {"SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "TA35": 'ת"א 35', "TA125": 'ת"א 125'}


@st.cache_data(ttl=60)
def get_index_changes() -> dict:
    return {idx: market_data.fetch_index_proxy_change(idx) for idx in ALL_INDICES}






@st.cache_data(ttl=60)
def _last_close_before(hist: pd.Series, target_date) -> float | None:
    """הסגירה היומית האחרונה *לפני* target_date - לא לפי מיקום קבוע (.iloc[-1]/-2)
    כי _get_index_history_raw (period יומי) כן כוללת שורה ל"היום" כשהמסחר
    פעיל כרגע, עם מחיר *חי מתעדכן*, לא סגירה סופית - .iloc[-1] יכול להיות
    "היום" או "אתמול" תלוי אם השוק פתוח, אז חיפוש לפי תאריך אמיתי הוא הדרך
    היחידה האמינה (9.9.2026, באג נמצא בפועל: כשהשוק פתוח .iloc[-1] היה
    בעצם המחיר החי של היום עצמו, לא סגירת אתמול - האחוז נתקע קרוב ל-0%
    כי הנקודה שהודבקה כ'סגירה קודמת' זהה כמעט למחיר הנוכחי)."""
    if hist.empty:
        return None
    earlier = hist[hist.index.map(lambda ts: ts.date() < target_date)]
    return float(earlier.iloc[-1]) if not earlier.empty else None


def get_index_intraday_sparkline(index_key: str, trading_open: bool = True) -> tuple[list, str | None]:
    """נקודות המסחר התוך-יומי - מטמון קצר (דקה, לא 5 כמו הגרסה ההיסטורית) כי
    זה "מסחר נוכחי" ואמור להיות רענן ממש. התווית היא שעת הנקודה האחרונה
    (HH:MM) כשהמסחר פעיל ("היום ב-14:35" לא אומר הרבה יותר מ"עכשיו", אבל
    השעה כן, 2.9.2026) - אבל כשהשוק סגור זה כבר לא בהכרח "היום" (יכול להיות
    יום המסחר האחרון, אתמול/שישי), אז מציגים תאריך כמו באפשרויות הימים
    האחרות, לא שעה בלי הקשר (9.9.2026, בעקבות בקשה מפורשת)."""
    hist = market_data.fetch_index_intraday(index_key)
    if hist.empty:
        return [], None
    # trading_open (is_market_open) לבד לא מספיק כדי להחליט שעה מול תאריך -
    # יאהו יכול לפגר אחרי פתיחת המסחר בפועל ולהחזיר עדיין את הנתון של אתמול
    # (נמצא בפועל: 17.9.2026, 10:07 עם שוק פתוח, עדיין 16/09 בנתונים) - אז
    # השעה לבד ("17:20") הייתה מטעה, נראית כמו "עכשיו". בודקים את התאריך
    # האמיתי של הנקודה האחרונה, לא רק אם השוק אמור להיות פתוח.
    _is_actually_today = hist.index[-1].date() == israel_today()
    _as_of = hist.index[-1].strftime("%H:%M") if (trading_open and _is_actually_today) else hist.index[-1].strftime("%d/%m")
    prices = hist.tolist()
    # האחוז שמחושב מהנקודה הראשונה כאן (ר' render_index_card/הרכיב ב-JS,
    # (last-first)/first) חייב להיות ביחס לסגירה *הקודמת* - המוסכמה הפיננסית
    # הרגילה (כמו בגוגל/יאהו פייננס) - לא ביחס לבר התוך-יומי הראשון של היום.
    _prev_close = _last_close_before(_get_index_history_raw(index_key), hist.index[-1].date())
    if _prev_close is not None and prices[0] and abs(_prev_close - prices[0]) / prices[0] > 0.0001:
        prices = [_prev_close] + prices
    return prices, _as_of


@st.cache_data(ttl=60)
def get_index_last_completed_sparkline(index_key: str) -> tuple[list, str | None]:
    """נקודות תוך-יומיות של יום המסחר האחרון *שהושלם* - בשימוש רק כשהמסחר
    פעיל כרגע (get_index_intraday_sparkline כבר תפוסה ב"מסחר פעיל", שהוא
    היום הנוכחי בעיצומו, לא היום שלפניו). כדי שגם אפשרות "יום המסחר האחרון"
    בסליידר תראה גרף תוך-יומי אמיתי, לא קו שטוח של סגירה מול סגירה
    (9.9.2026, בקשה מפורשת: "מסחר פעיל... והחלק הבא אחריו... יום המסחר
    האחרון... עם נתונים של יום המסחר האחרון")."""
    hist = market_data.fetch_index_last_completed_intraday(index_key)
    if hist.empty:
        return [], None
    _as_of = hist.index[-1].strftime("%d/%m")
    prices = hist.tolist()
    # הסגירה *לפני* היום המושלם הזה עצמו (לא לפני "היום" הנוכחי) - ר' הערה
    # ב-_last_close_before למה חיפוש לפי תאריך, לא .iloc[-2] קבוע.
    _prev_close = _last_close_before(_get_index_history_raw(index_key), hist.index[-1].date())
    if _prev_close is not None and prices[0] and abs(_prev_close - prices[0]) / prices[0] > 0.0001:
        prices = [_prev_close] + prices
    return prices, _as_of


@st.cache_data(ttl=300)
def _get_index_history_raw(index_key: str) -> pd.Series:
    """שליפת ה-4 חודשים הגולמית בלבד, ממוטמנת בנפרד לפי index_key בלבד (לא
    לפי days) - כדי שכרטיס המדדים יוכל לשלוף מראש את כל אפשרויות הטווח (0-9
    קריאות ל-get_index_sparkline לכל מדד, ר' render_index_card) בלי להכפיל
    את קריאת הרשת היקרה פי-7: בלי ההפרדה הזו, כל days שונה הוא מפתח-מטמון
    נפרד ב-get_index_sparkline, וכל אחד קורא שוב ל-fetch_index_history בעצמו
    (שאינה ממוטמנת בכלל ברמת src/market_data.py) - זו הייתה הסיבה האמיתית
    לאיטיות חמורה אחרי restart שדווחה בפועל (9.9.2026)."""
    return market_data.fetch_index_history(index_key, period="4mo")


def get_index_sparkline(index_key: str, days: int) -> tuple[list, str | None]:
    """היסטוריית סגירות קצרה של המדד (לגרף הזעיר) + תאריך הסגירה האחרונה -
    שולפים 4 חודשים קלנדריים תמיד (מספיק גם ל-90 ימי מסחר, המקסימום שהבורר
    מאפשר, ר' _get_index_history_raw) ומחתכים לפי מה שהמשתמש בחר, כדי לא
    להזדקק למחרוזת period שונה של yfinance לכל ערך אפשרי."""
    hist = _get_index_history_raw(index_key)
    if hist.empty:
        return [], None
    # days+1, לא days: "יום מסחר אחרון" (days=1) לבדו הוא נקודת מחיר אחת -
    # אי אפשר לצייר קו מנקודה בודדת. נקודה נוספת אחת מלפני התחלת הטווח
    # נותנת קו בעל משמעות (השינוי *לאורך* הטווח שנבחר) בכל ערך, כולל 1 (2.9.2026).
    sliced = hist.tolist()[-(days + 1):]
    return sliced, hist.index[-1].strftime("%d/%m")





















def _compute_portfolio_summaries(holdings_df: pd.DataFrame):
    """מחשב את כרטיסי 'התיק שלי' (רווח כולל, שינוי יומי, שווי). מופרד מהרינדור
    ונקרא מבפנים ל-fragment עם run_every, כדי שהמחירים (get_current_price /
    fetch_universe_daily_changes) יישלפו טריים בכל הפעלה עצמאית שלו - לא רק
    פעם אחת בטעינת הדף."""
    portfolio_summary = value_summary = today_summary = None
    _price_map = get_current_prices_batch(tuple(sorted(set(holdings_df["ticker"])))) if not holdings_df.empty else {}
    if not holdings_df.empty:
        _by_ccy = {}
        for _, _r in holdings_df.iterrows():
            _entry, _qty = _r["actual_entry_price"], _r["actual_qty"]
            if not _entry or not _qty:
                continue
            _current = _price_map.get(_r["ticker"])
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
                "תשואה", _dom_agg["pnl"], _dom_pct,
                CURRENCY_SYMBOLS.get(_dominant_ccy, _dominant_ccy),
            )
            _total_value = _dom_agg["invested"] + _dom_agg["pnl"]
            value_summary = (
                "🪙 שווי כולל", _total_value, _dom_agg["invested"],
                CURRENCY_SYMBOLS.get(_dominant_ccy, _dominant_ccy), len(holdings_df),
            )

    if not holdings_df.empty:
        _own_close_conn = store.get_conn(db_path(cfg))
        _today_iso = israel_today().isoformat()
        try:
            for _t in sorted(set(holdings_df["ticker"])):
                _p = _price_map.get(_t)
                if _p is None:
                    continue
                _country = "IL" if market_data._is_israeli_ticker(_t) else "US"
                # תופסים "סגירה היום" רק אחרי שהמסחר באמת נסגר - אחרת המחיר החי
                # הוא עדיין תוך-יומי, לא סגירה, ולא יהיה נכון לרשום אותו ככזה
                # (ר' record_own_close - מקור אמת עצמאי, חייב להיות סגירה אמיתית).
                if has_closed_today(_country):
                    store.record_own_close(_own_close_conn, _t, _today_iso, _p)
        except Exception:
            pass  # תוסף לא-קריטי (23.9.2026) - כישלון כאן לא אמור להפיל את הדף

        _daily_df = market_data.fetch_universe_daily_changes(holdings_df["ticker"].tolist())
        _today_by_ccy = {}
        _today_max_close_date = None
        _today_gap_baseline_dates = []
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
            # קנייה באמצע אותו יום מסחר: הסגירה של אותו יום באה *אחרי* הקנייה, אז היא נכללת (בסיס = שער הכניסה) - כמו בטבלת האחזקות
            _bought_dt = None
            try:
                _bought_dt = dt.datetime.fromisoformat(_r["bought_at"]) if _r.get("bought_at") else None
            except Exception:
                pass
            _same_day_before_close = bool(
                _bought_date and _bought_date == _last_close_date and _bought_dt is not None
                and not bought_after_close(constituents.INDEX_COUNTRY_CODE.get(_r.get("index_name"), "IL"), _bought_dt)
            )
            if _bought_date and _last_close_date and _bought_date >= _last_close_date and not _same_day_before_close:
                continue
            _baseline = _prev_close
            _same_day_before_prev_close = bool(
                _bought_date and _prev_close_date and _bought_date == _prev_close_date and _bought_dt is not None
                and not bought_after_close(constituents.INDEX_COUNTRY_CODE.get(_r.get("index_name"), "IL"), _bought_dt)
            )
            _using_entry_baseline2 = bool(
                _bought_date and _prev_close_date and _bought_date >= _prev_close_date and _r.get("actual_entry_price")
                and not _same_day_before_prev_close
            )
            if _using_entry_baseline2:
                _baseline = _r["actual_entry_price"]
            elif _row_data.get("prev_close_gap") and _prev_close_date:
                # yfinance מפגר (prev_close_gap) - לפני שמוותרים ומשתמשים בסגירה
                # הישנה שלו, בודקים אם יש לנו סגירה עצמאית יותר טרייה שנרשמה
                # בעצמנו (ר' store.record_own_close, 23.9.2026) - אם כן, זו
                # מקור אמת עדיף, לא תלוי בפער של yfinance בכלל. עטוף ב-try
                # (23.9.2026, בעקבות AttributeError על האתר הציבורי - כנראה
                # dtype שונה ל-prev_close_date בפועל בענן לעומת מקומי, לא
                # שוחזר בבדיקה מקומית) - תוסף חדש שלא-קריטי אסור שיפיל את כל
                # העמוד; כישלון כאן פשוט נופל לאחור להתנהגות הישנה (מסומן כפער).
                try:
                    _own = store.get_last_own_close_before(_own_close_conn, _r["ticker"], _today_iso)
                except Exception:
                    _own = None
                if _own and str(_own[0]) > str(_prev_close_date):
                    _baseline = _own[1]
                    _prev_close_date = dt.date.fromisoformat(str(_own[0]))
                else:
                    _today_gap_baseline_dates.append(_prev_close_date)
            _ccy2 = constituents.INDEX_CURRENCY.get(_r.get("index_name"), "ILS")
            _agg2 = _today_by_ccy.setdefault(_ccy2, {"prev_value": 0.0, "change": 0.0})
            _agg2["prev_value"] += _baseline * _qty
            _agg2["change"] += (_last_close - _baseline) * _qty
            if _last_close_date and (_today_max_close_date is None or _last_close_date > _today_max_close_date):
                _today_max_close_date = _last_close_date
        if _today_by_ccy:
            _dom_ccy2 = max(_today_by_ccy, key=lambda c: _today_by_ccy[c]["prev_value"])
            _dom2 = _today_by_ccy[_dom_ccy2]
            _today_pct = (_dom2["change"] / _dom2["prev_value"] * 100) if _dom2["prev_value"] else 0.0
            # התאריך בסוגריים רלוונטי רק כשהמסחר סגור (מבהיר שזה מהסגירה
            # האחרונה, לא "עכשיו") - כשהמסחר פתוח "היום" חד-משמעי בלי צורך
            # בתאריך (9.9.2026, בעקבות בקשת המשתמש). חריג: פער אמיתי בין ימי
            # מסחר (ר' market_data._prev_close_gap, 15.9.2026 "הנתון שגוי") -
            # אז מציגים תמיד את תאריך הבסיס, גם כשהשוק פתוח, כי אחרת "שינוי
            # יומי" נראה כמו יום מסחר אחד כשהוא בעצם כמה.
            _today_label = "שינוי יומי"
            _dom_index_hint = "TA35" if _dom_ccy2 == "ILS" else "NASDAQ100"
            if _today_gap_baseline_dates:
                _today_label += f" ({min(_today_gap_baseline_dates).strftime('%d/%m')})"
            elif _today_max_close_date and not is_market_open(_dom_index_hint):
                _today_label += f" ({_today_max_close_date.strftime('%d/%m')})"
            today_summary = (
                _today_label, _dom2["change"], _today_pct, CURRENCY_SYMBOLS.get(_dom_ccy2, _dom_ccy2)
            )

    proximity_summary = None
    exposure_summary = None
    if not holdings_df.empty:
        _best = None  # (gap_pct, name, is_target) - הפער הכי קטן שנמצא עד כה בין המחיר הנוכחי לבין היעד או הסטופ
        _stop_warn_pct = cfg.get("holdings_stop_warn_pct", STOP_WARN_PCT)
        _target_warn_pct = cfg.get("holdings_target_warn_pct", TARGET_WARN_PCT)
        _best_target = None  # אותו מבנה כמו _best - רק אחזקות שחצו/קרובות ליעד
        _exposure_by_ccy = {}  # מצטבר לכרטיס "חשיפה לסיכון" - כמה מהתיק קרוב/חצה סטופ *בו-זמנית*,
        # לא רק האחזקה הבודדת הכי דחופה (proximity_summary למעלה) - ר' 17.9.2026,
        # "כמה % מהתיק קרוב לסטופ בו-זמנית, לא רק מניה בודדת".
        for _, _r in holdings_df.iterrows():
            _entry, _qty = _r.get("actual_entry_price"), _r.get("actual_qty")
            if not _entry or not _qty:
                continue
            _current = _price_map.get(_r["ticker"])
            if _current is None:
                _fallback_prices = get_sparkline_prices(_r["ticker"])
                _current = _fallback_prices[-1] if _fallback_prices else None
            if _current is None:
                continue
            _name = _r.get("company_name") or _r["ticker"]
            _stop_price = get_or_backfill_stop_price(_r, _entry)
            _target_price = live_target_price(_entry, _stop_price, _r.get("target_base"))
            # יחסית למחיר הסף עצמו (סטופ/יעד), לא הפרש-נקודות-אחוז יחסית
            # לכניסה - בדיוק כמו בכרטיס האחזקה הבודדת (distance_pct/
            # target_distance_pct, למטה) כדי ששני הכרטיסים יראו אותו מספר.
            # ההפרש בין שתי השיטות גדל ככל שהמרחק כניסה-סטופ גדול יותר (למשל
            # עם סטופ 2.5x ATR רחב) - נמצא בפועל: 15.9.2026, "בכרטיס המניה
            # כתוב שחצתה ב-2% ובכרטיס 'התיק שלי' כתוב 1.6%".
            _gap_target = target_distance_pct(_current, _target_price)
            _gap_stop = stop_distance_pct(_current, _stop_price)
            if _best is None or _gap_target < _best[0]:
                _best = (_gap_target, _name, True)
            if _gap_stop < _best[0]:
                _best = (_gap_stop, _name, False)
            # מניה שחצתה או קרובה ליעד (בסף ההתראה שהוגדר) תמיד מקבלת עדיפות על פני סטופ (13.10.2026)
            if _gap_target <= _target_warn_pct and (_best_target is None or _gap_target < _best_target[0]):
                _best_target = (_gap_target, _name, True)

            _ccy3 = constituents.INDEX_CURRENCY.get(_r.get("index_name"), "ILS")
            _exp = _exposure_by_ccy.setdefault(_ccy3, {"total_value": 0.0, "at_risk_value": 0.0,
                                                         "total_count": 0, "at_risk_count": 0})
            _holding_value = _current * _qty
            _exp["total_value"] += _holding_value
            _exp["total_count"] += 1
            if _gap_stop <= _stop_warn_pct:
                _exp["at_risk_value"] += _holding_value
                _exp["at_risk_count"] += 1
        if _best_target is not None:
            _best = _best_target
        if _best is not None:
            proximity_summary = (_best[1], _best[0], _best[2])
        if _exposure_by_ccy:
            # אותה מוסכמה כמו value_summary/portfolio_summary למעלה - מטבע דומיננטי
            # לפי שווי כולל, כי אי אפשר לחבר ש"ח ודולר לכרטיס אחד בעל משמעות.
            _exp_ccy = max(_exposure_by_ccy, key=lambda c: _exposure_by_ccy[c]["total_value"])
            _exp_agg = _exposure_by_ccy[_exp_ccy]
            # רק מ-2 אחזקות בו-זמנית ומעלה - עם אחת בלבד זה כבר מוצג ע"י
            # proximity_summary (הכרטיס "קרוב לסטופ" הקיים), הכרטיס הזה נועד
            # במפורש לחשוף את המקרה של כמה אחזקות קרובות/חצו יחד.
            if _exp_agg["at_risk_count"] >= 2:
                exposure_summary = (
                    _exp_agg["at_risk_count"], _exp_agg["total_count"],
                    _exp_agg["at_risk_value"], _exp_agg["total_value"],
                    CURRENCY_SYMBOLS.get(_exp_ccy, _exp_ccy),
                )

    return portfolio_summary, today_summary, value_summary, proximity_summary, exposure_summary


def _build_intraday_comparison_df(relevant_holdings: pd.DataFrame, dominant_index: str,
                                   intraday: dict, bench_hist: pd.Series,
                                   daily_hist_by_ticker: dict, bench_daily_hist: pd.Series):
    """ממוצע משוקלל (לפי סכום ההשקעה) של % השינוי התוך-יומי - כל אחזקה ביחס
    ל*סגירת יום המסחר הקודם* שלה (לא ביחס לנקודה התוך-יומית הראשונה של אותו
    יום!) - אותה נקודת ייחוס בדיוק כמו תג "שינוי יומי" בכרטיסי האחזקות
    וכרטיסי המדדים (14.9.2026, "הנתון כאן לא תואם את הנתונים בכרטיסי
    המדדים" - הגרסה הקודמת התחילה מ-0% ביחס למחיר הפתיחה שלה, לא ביחס
    לסגירה הקודמת, אז לא הייתה יכולה להתאים). מחזיר None אם אין לפחות 2
    נקודות זמן משותפות לתיק ולמדד (לא מספיק לצייר קו)."""
    if not intraday:
        return None
    session_date = bench_hist.index[0].date() if bench_hist is not None and not bench_hist.empty else None
    if session_date is None:
        for closes in intraday.values():
            if closes is not None and not closes.empty:
                session_date = closes.index[0].date()
                break
    if session_date is None:
        return None

    # סדרת % לכל אחזקה (פרוסות של 5 דקות, האחרון בכל פרוסה). אחזקה בלי פס בפרוסה מסוימת (מסחר דל) נשארת על ערכה האחרון
    # (ffill; לפני הפס הראשון - הערך הראשון) - אחרת הממוצע המשוקלל בפרוסה הזו נעשה רק על חלק מהאחזקות ויוצר קפיצות חדות.
    pct_by_ticker: dict = {}
    invested_by_ticker: dict = {}
    for _, r in relevant_holdings.iterrows():
        closes = intraday.get(r["ticker"])
        if closes is None or closes.empty:
            continue
        qty = r.get("actual_qty")
        entry = r.get("actual_entry_price")
        if not qty or not entry:
            continue
        daily_hist = daily_hist_by_ticker.get(r["ticker"])
        prev_close = _last_close_before(daily_hist, session_date) if daily_hist is not None else None
        if not prev_close:
            continue
        pct = pd.Series(
            [(float(price) - prev_close) / prev_close * 100 for price in closes.values],
            index=[ts.floor("5min") for ts in closes.index],
        )
        pct = pct[~pct.index.duplicated(keep="last")]
        pct_by_ticker[r["ticker"]] = pct
        invested_by_ticker[r["ticker"]] = entry * qty
    if not pct_by_ticker:
        return None
    pct_df = pd.DataFrame(pct_by_ticker).sort_index().ffill().bfill()
    weights = pd.Series(invested_by_ticker)[pct_df.columns]
    portfolio_pct = (pct_df * weights).sum(axis=1) / weights.sum()

    if bench_hist is None or bench_hist.empty:
        return None
    bench_prev_close = _last_close_before(bench_daily_hist, session_date) if bench_daily_hist is not None else None
    if not bench_prev_close:
        return None
    bench_pct = pd.Series({
        ts.floor("5min"): (float(price) - bench_prev_close) / bench_prev_close * 100
        for ts, price in bench_hist.items()
    }).sort_index()
    common_ts = sorted(t for t in portfolio_pct.index if t in bench_pct.index)
    if len(common_ts) < 2:
        return None
    return pd.DataFrame({
        "התיק שלי": portfolio_pct.loc[common_ts],
        INDEX_LABELS.get(dominant_index, dominant_index): bench_pct.loc[common_ts],
    })


def _compute_portfolio_history(holdings_df: pd.DataFrame):
    """שינוי % *תוך-יומי* (לא תשואה מצטברת מאז הקנייה, ולא שינוי יומי לפי
    ימי-לוח - 14.9.2026, "במקום תאריכים שעות") של התיק מול פרוקסי המדד
    הדומיננטי (לפי איזה index_name הכי הרבה כסף מושקע בו), לאורך שעות יום
    המסחר. כל נקודה = % שינוי ביחס למחיר הפתיחה של אותו יום, ממוצע משוקלל
    (לפי סכום ההשקעה) על כל האחזקות הרלוונטיות.
    מנסים קודם את היום הנוכחי; אם עדיין אין בו מספיק נקודות (למשל דקות
    ספורות אחרי פתיחת המסחר) נופלים על יום המסחר האחרון *שהושלם*; אם גם זה
    נכשל (תקלת יאהו ב-intraday עצמו, לא רק בסגירות היומיות - נמצא בפועל
    23.9.2026, פער נתונים יומי בן 6 ימים) נופלים לרזולוציית יום (ר'
    _build_daily_comparison_df) - "תמיד חייב להיות מוצג גרף. תמיד" (14.9.2026).
    מחזיר (None, None, None, False) רק אם גם השלב האחרון הזה נכשל (אין
    בכלל נתונים, אפילו לא סגירות יומיות).

    מחזיר (df, as_of_label, dominant_index, is_daily): as_of_label הוא None
    כשמוצג היום הנוכחי (הציר "נכון" לשעון האמיתי), או "DD/MM" כשמוצג יום
    מסחר קודם - כדי שהתצוגה תבהיר את זה בפירוש (לא רק "יש ציר עד 17:00" בלי
    הקשר, שנראה כאילו יש נתונים "מהעתיד" ביחס לשעה האמיתית עכשיו - 14.9.2026,
    "לא הגיוני, שעכשיו מוצג 17:00"). אותה מוסכמה בדיוק כמו
    get_index_last_completed_sparkline. dominant_index מוחזר בנפרד כדי
    שה-caller יוכל לבדוק is_market_open בעצמו - גם כש-as_of_label=None (מוצג
    "היום"), היום עצמו יכול כבר *להסתיים* (המסחר נסגר, אבל עדיין אותו יום
    קלנדרי) - "תציין תאריך אחרי התוך-יומי כשהמסחר לא פעיל" (17.9.2026) צריך
    את שני התנאים, לא רק "יום קודם". is_daily=True רק בנפילה לרזולוציית-יום -
    ה-caller צריך את זה כדי להעביר is_daily=True הלאה ל-_build_comparison_chart
    (ציר תאריכים, לא שעות)."""
    if holdings_df.empty:
        return None, None, None, False

    _idx_invested = {}
    for _, r in holdings_df.iterrows():
        idx = r.get("index_name")
        entry, qty = r.get("actual_entry_price"), r.get("actual_qty")
        if not idx or not entry or not qty:
            continue
        _idx_invested[idx] = _idx_invested.get(idx, 0.0) + entry * qty
    if not _idx_invested:
        return None, None, None, False
    dominant_index = max(_idx_invested, key=_idx_invested.get)
    dominant_ccy = constituents.INDEX_CURRENCY.get(dominant_index, "ILS")

    relevant_holdings = holdings_df[
        holdings_df["index_name"].apply(lambda i: constituents.INDEX_CURRENCY.get(i, "ILS") == dominant_ccy)
    ]
    if relevant_holdings.empty:
        return None, None, None, False

    tickers = relevant_holdings["ticker"].tolist()

    # סגירות יומיות (לא תוך-יומיות) - לנקודת הייחוס "סגירת יום המסחר הקודם"
    # שממנה נמדד השינוי %, אותו מקור בדיוק כמו תג "שינוי יומי" בכרטיסי
    # האחזקות/המדדים, כדי שהאחוזים בגרף באמת יתאימו להם.
    _daily_df = market_data.fetch_universe_daily_changes(tickers)
    daily_hist_by_ticker = {
        row["ticker"]: row["history"] for _, row in _daily_df.iterrows()
    } if not _daily_df.empty else {}
    bench_daily_hist = _get_index_history_raw(dominant_index)

    comparison_df = _build_intraday_comparison_df(
        relevant_holdings, dominant_index,
        market_data.fetch_universe_intraday_changes(tickers),
        market_data.fetch_index_intraday(dominant_index),
        daily_hist_by_ticker, bench_daily_hist,
    )
    if comparison_df is not None:
        # "היום" כאן זה רק ה-*תאריך האחרון שמופיע בנתונים* (fetch_index_intraday/
        # fetch_universe_intraday_changes מסננות לזה) - לא בהכרח היום הקלנדרי
        # האמיתי. יאהו יכול לפגר אחרי פתיחת המסחר בפועל בכמה עשרות דקות (נמצא
        # בפועל: 17.9.2026, 10:07 בבוקר עם שוק פתוח, fetch_index_intraday
        # החזירה עדיין את 16.9 בלבד) - בלי הבדיקה הזו זה מוצג כ"תוך-יומי" בלי
        # תאריך, כאילו זה נתון חי של היום, כשבפועל זה עדיין אתמול.
        _comp_last_date = comparison_df.index.max().date()
        if _comp_last_date == israel_today():
            return comparison_df, None, dominant_index, False
        return comparison_df, _comp_last_date.strftime("%d/%m"), dominant_index, False

    comparison_df = _build_intraday_comparison_df(
        relevant_holdings, dominant_index,
        market_data.fetch_universe_last_completed_intraday_changes(tickers),
        market_data.fetch_index_last_completed_intraday(dominant_index),
        daily_hist_by_ticker, bench_daily_hist,
    )
    if comparison_df is not None:
        as_of_label = comparison_df.index[-1].strftime("%d/%m")
        return comparison_df, as_of_label, dominant_index, False

    # שני ניסיונות התוך-יומי (היום/יום מסחר אחרון) דורשים שני fetch-ים
    # תוך-יומיים בו-זמנית (אחזקות + מדד) - כשל ממושך של אחד מהם (נמצא בפועל
    # 23.9.2026, אחרי שפער הנתונים היומי נמשך 6 ימים ברצף) משאיר את הגרף
    # ריק, למרות שיש בפועל סגירות יומיות תקינות זמינות. נופלים לגרסה גסה
    # יותר (רזולוציית יום, לא תוך-יומי) שבנויה רק מה-daily history שכבר
    # שלפנו למעלה - "חייב להיות מוצג גרף. תמיד" (14.9.2026) גובר על דיוק
    # הרזולוציה.
    comparison_df = _build_daily_comparison_df(
        relevant_holdings, dominant_index, daily_hist_by_ticker, bench_daily_hist,
    )
    as_of_label = comparison_df.index[-1].strftime("%d/%m") if comparison_df is not None else None
    return comparison_df, as_of_label, dominant_index, True


def _build_daily_comparison_df(relevant_holdings: pd.DataFrame, dominant_index: str,
                                daily_hist_by_ticker: dict, bench_daily_hist: pd.Series,
                                n_days: int = 10):
    """נופלים לזה כששני ניסיונות התוך-יומי (_build_intraday_comparison_df,
    להיום וליום המסחר האחרון) נכשלים - למשל תקלת יאהו ממושכת בנתוני
    ה-intraday עצמם. בונה השוואה מ*סגירות יומיות* בלבד (לא תוך-יומי) על פני
    עד n_days ימי המסחר האחרונים שיש להם בפועל נתון - ר' 23.9.2026, "אין
    מצב שאתה לא מציג נתונים".

    מקבצים לפי .date() (לא לפי ה-Timestamp הגולמי) בכוונה: daily_hist_by_ticker
    (מ-fetch_universe_daily_changes) מגיע עם אינדקס tz-naive, בעוד
    bench_daily_hist (מ-fetch_index_history) מגיע tz-aware (Asia/Jerusalem) -
    נמצא בפועל (23.9.2026) שחיתוך common_ts בין השניים יצא ריק לגמרי בגלל
    זה למרות שהתאריכים הקלנדריים זהים - שני Timestamp שונים ב-tz לא נחשבים
    שווים גם כשהם "אותו יום". date() ניטרלי מבחינת tz, פותר את זה."""
    weighted_by_date: dict = {}
    weight_by_date: dict = {}
    for _, r in relevant_holdings.iterrows():
        hist = daily_hist_by_ticker.get(r["ticker"])
        qty = r.get("actual_qty")
        entry = r.get("actual_entry_price")
        if hist is None or hist.empty or not qty or not entry:
            continue
        recent = hist.tail(n_days + 1)
        if len(recent) < 2:
            continue
        invested = entry * qty
        base = float(recent.iloc[0])
        for ts, price in recent.items():
            d = ts.date()
            pct = (float(price) - base) / base * 100
            weighted_by_date[d] = weighted_by_date.get(d, 0.0) + pct * invested
            weight_by_date[d] = weight_by_date.get(d, 0.0) + invested
    if not weighted_by_date:
        return None
    portfolio_pct = pd.Series({
        pd.Timestamp(d): weighted_by_date[d] / weight_by_date[d] for d in weighted_by_date
    }).sort_index()

    if bench_daily_hist is None or bench_daily_hist.empty:
        return None
    recent_bench = bench_daily_hist.tail(n_days + 1)
    if len(recent_bench) < 2:
        return None
    bench_base = float(recent_bench.iloc[0])
    bench_pct = pd.Series({
        pd.Timestamp(ts.date()): (float(price) - bench_base) / bench_base * 100
        for ts, price in recent_bench.items()
    }).sort_index()

    common_ts = sorted(t for t in portfolio_pct.index if t in bench_pct.index)
    if len(common_ts) < 2:
        return None
    return pd.DataFrame({
        "התיק שלי": portfolio_pct.loc[common_ts],
        INDEX_LABELS.get(dominant_index, dominant_index): bench_pct.loc[common_ts],
    })
























_SECTOR_LABELS_HE = {
    "Technology": "טכנולוגיה",
    "Financial Services": "פיננסיים",
    "Financials": "פיננסים",
    "Healthcare": "בריאות",
    "Energy": "אנרגיה",
    "Consumer Cyclical": "צריכה מחזורית",
    "Consumer Defensive": "צריכה בסיסית",
    "Industrials": "תעשייה",
    "Basic Materials": "חומרי גלם",
    "Real Estate": 'נדל"ן',
    "Utilities": "תשתיות",
    "Communication Services": "תקשורת",
}






def _autosave_settings():
    """נשמר אוטומטית ל-config.yaml ברגע שמשנים ערך בסיידבר - בלי כפתור "שמור"
    נפרד, כי אלה רק שני שדות פשוטים ואין סיבה אמיתית לדחות את הכתיבה לדיסק."""
    new_indices = st.session_state.get("settings_indices")
    if not new_indices:
        st.toast("יש לבחור לפחות מדד אחד - לא נשמר.", icon="⚠️", duration=2)
        return
    new_indices = [i for i in SCAN_INDEX_ORDER if i in new_indices]  # סדר קבוע, לא סדר הלחיצות
    st.session_state["settings_indices"] = new_indices
    cfg["indices"] = new_indices
    cfg.pop("index", None)
    cfg["drop_threshold_pct"] = st.session_state.get("settings_threshold")
    cfg["multi_day_window_days"] = st.session_state.get("settings_multi_day_days")
    cfg["multi_day_threshold_pct"] = st.session_state.get("settings_multi_day_threshold")
    cfg["multi_day_enabled"] = st.session_state.get("settings_multi_day_enabled", True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("settings")


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


def _autosave_message_types():
    types = {
        key: bool(st.session_state.get(f"settings_msgtype_{key}", True))
        for key in notifier.MESSAGE_TYPES
    }
    cfg["telegram_message_types"] = types
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("message types")


def _autosave_channels():
    # בהפעלת ערוץ נרשם מתי הופעל (enabled_since): מקבלים התראות רק מאותו רגע קדימה, לא את מה שקרה קודם
    _now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for _ch_key, _widget in (("telegram", "settings_telegram_enabled"), ("desktop_notifications", "settings_desktop_enabled")):
        _new_on = bool(st.session_state.get(_widget, True))
        _was_on = bool(cfg.get(_ch_key, {}).get("enabled", True))
        cfg.setdefault(_ch_key, {})["enabled"] = _new_on
        if _new_on and not _was_on:
            cfg[_ch_key]["enabled_since"] = _now_iso
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _sync_and_warn("notification channels")


with st.sidebar:
    current_indices = cfg.get("indices") or ([cfg["index"]] if "index" in cfg else [])
    # מסודר לפי סדר קבוע (SCAN_INDEX_ORDER: קודם ת"א, אחר כך אמריקאי) - לא לפי סדר הבחירה ההיסטורי - כדי
    # ש-NASDAQ100 יהיה תמיד ליד SP500 (שניהם דולר) ו-TA35 ליד TA125 (שניהם
    # שקל), לא מפוזרים (14.9.2026, "הנאסד״ק יוכל להיות לצד הS&P"; 15.10.2026: הסדר קבוע גם אחרי בחירה/הסרה).
    current_indices = [i for i in SCAN_INDEX_ORDER if i in current_indices]

    if cfg.get("strategy_selector"):
        # בורר אסטרטגיה (14.10.2026). כיבוי מיידי: strategy_selector: false ב-config.yaml, או הכפתור "חזרה לאסטרטגיה הנוכחית".
        def _autosave_strategy():
            cfg["strategy_card"] = st.session_state.get("settings_strategy_card", strategy_mod.DEFAULT_CARD)
            cfg["risk_level"] = st.session_state.get("settings_risk_level", strategy_mod.DEFAULT_RISK)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
            _sync_and_warn("strategy")

        def _reset_strategy():
            st.session_state["settings_strategy_card"] = strategy_mod.DEFAULT_CARD
            st.session_state["settings_risk_level"] = strategy_mod.DEFAULT_RISK
            _autosave_strategy()

        with st.container(border=True, key="strategy_selector_card"):
            st.markdown("**🎯 אסטרטגיה**")
            _card_keys, _risk_keys = list(strategy_mod.SCORECARDS), list(strategy_mod.RISK_LEVELS)
            st.selectbox(
                "רמת סינון", _card_keys, index=_card_keys.index(strategy_mod.active_card_key()),
                format_func=lambda k: strategy_mod.SCORECARDS[k]["label"], key="settings_strategy_card",
                on_change=_autosave_strategy,
                help="איפה עוברים הגבולות בין א' (לקנות), ב' (לחכות) וג' (לא לקנות). הניקוד עצמו זהה בכל הכרטיסים.\n"
                     + "\n".join(f"• {v['label']}: {v['desc']}" for v in strategy_mod.SCORECARDS.values()),
            )
            st.selectbox(
                "רמת סיכון", _risk_keys, index=_risk_keys.index(strategy_mod.active_risk_key()),
                format_func=lambda k: strategy_mod.RISK_LEVELS[k]["label"], key="settings_risk_level",
                on_change=_autosave_strategy,
                help="קובעת את היעד בעסקה ואת הסיכון לעסקה (מכפיל על 'סיכון לעסקה' בהגדרות).\n"
                     + "\n".join(f"• {v['label']}: {v['desc']}" for v in strategy_mod.RISK_LEVELS.values()),
            )
            st.button("↩ חזרה לאסטרטגיית ברירת המחדל", key="strategy_reset_btn", on_click=_reset_strategy,
                      use_container_width=True,
                      disabled=(strategy_mod.active_card_key(), strategy_mod.active_risk_key())
                      == (strategy_mod.DEFAULT_CARD, strategy_mod.DEFAULT_RISK))

    with st.container(border=True, key="scan_settings_card"):
        st.markdown(
            """
            <style>
            div[class*="st-key-scan_settings_card"] {
                border-radius: 10px;
                border-right: 3px solid #3B6EA5;
                padding-top: 0px !important;
            }
            /* הכלל הגלובלי של הסיידבר (שורה ~438) קובע gap:0.8rem!important
            עם ספציפיות (0,2,0) - חייב selector עם ספציפיות שווה/גבוהה יותר
            כדי לגבור עליו, לא מספיק רק !important (15.9.2026, "אתה פועל
            הפוך ממה שביקשתי" - ה-gap רק גדל כי כל div מרווח שהוספתי הוא
            flex item נוסף עם gap משלו משני צדדיו). */
            div[data-testid="stVerticalBlock"][class*="st-key-scan_settings_card"] {
                gap: 4px !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        _sb_title("📊 מדדים לסריקה")
        st.pills(
            "בחר מדד/ים לסריקה", SCAN_INDEX_ORDER, selection_mode="multi",
            default=None if "settings_indices" in st.session_state else current_indices, label_visibility="collapsed",
            key="settings_indices", on_change=_autosave_settings,
        )
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        _sb_title("📉 ירידה יומית להתראה")
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
        tc1, tc2 = (st.container(), st.empty())
        tc1.number_input(
            "אחוז ירידה שמפעיל התראה", min_value=0.5, max_value=50.0,
            value=float(cfg["drop_threshold_pct"]), step=0.5, label_visibility="collapsed",
            key="settings_threshold", on_change=_autosave_settings,
        )

        _sb_title("📉 ירידה מצטברת")
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        _v3_row = st.columns([1.15, 1], gap="small")
        mc1, mc2, dc1, dc2 = _v3_row[0], st.empty(), _v3_row[1], st.empty()
        mc1.number_input(
            "אחוז ירידה מצטברת שמפעיל התראה", min_value=0.5, max_value=50.0,
            value=float(cfg.get("multi_day_threshold_pct", 5.0)), step=0.5, label_visibility="collapsed",
            key="settings_multi_day_threshold", on_change=_autosave_settings,
            disabled=not st.session_state.get("settings_multi_day_enabled", cfg.get("multi_day_enabled", True)),
        )
        dc1.number_input(
            "מספר ימים לירידה מצטברת", min_value=2, max_value=10, step=1,
            value=int(cfg.get("multi_day_window_days", 3)), label_visibility="collapsed",
            key="settings_multi_day_days", on_change=_autosave_settings,
            disabled=not st.session_state.get("settings_multi_day_enabled", cfg.get("multi_day_enabled", True)),
        )
        st.toggle(
            "הפעל התראת ירידה מצטברת", value=bool(cfg.get("multi_day_enabled", True)),
            key="settings_multi_day_enabled", on_change=_autosave_settings,
        )

        # הכפתור עבר לתוך אותו כרטיס כמו ההגדרות שהוא בעצם מפעיל (14.9.2026,
        # "את כפתור הסריקה הידנית לדעתי צריך למקום במקום אחר... בתוך כרטיס
        # הגדרות סריקה עצמו") - במקום תיבה נפרדת משלו כמו קודם. אנימציית
        # "קו סריקה" נוסתה ונדחתה ("תחזיר למצב הקודם") - חזרה לחיקוי שורת
        # expander (טקסט רגיל, חץ "▶" בקצה).
        st.markdown(
            """
            <style>
            div[class*="st-key-sidebar_scan_button"] button {
                background-color: transparent !important;
                border: none !important;
                box-shadow: none !important;
                font-weight: 400 !important; font-size: 14px !important;
                justify-content: space-between !important;
                padding: 4px 12px !important;
                color: inherit !important;
            }
            div[class*="st-key-sidebar_scan_button"] button p {
                color: inherit !important;
            }
            div[class*="st-key-sidebar_scan_button"] button:hover {
                background-color: rgba(120,120,120,0.07) !important;
            }
            div[class*="st-key-sidebar_scan_button"] button > div {
                justify-content: space-between !important;
                width: 100%;
            }
            div[class*="st-key-sidebar_scan_button"] button::after {
                content: "▶";
                font-size: 10px;
                color: #3B6EA5;
                margin-inline-start: 8px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.button(_nm("🔍 סריקת שווקים ידנית"), key="sidebar_scan_button", width='stretch'):
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

    with st.container(border=True, key="exp_group_card"):
        st.markdown(
            """
            <style>
            div[class*="st-key-exp_group_card"] {
                border-radius: 10px;
                border-right: 3px solid #3B6EA5;
                padding-top: 0px !important;
            }
            /* צמצום המרווח בין הפריטים המתקפלים - לא להדביק לגמרי (14.9.2026,
            "אתה יכול לצמצם אותם קצת, לא חייב להצמיד"), רק לקרב. נמדד: המרווח
            המקורי כ-13px - מצמצמים לכ-6px, לא ל-0. */
            div[class*="st-key-exp_investment"],
            div[class*="st-key-exp_fees"],
            div[class*="st-key-exp_message_types"] {
                margin-top: -7px;
            }
            div[data-testid="stVerticalBlock"][class*="st-key-exp_group_card"] {
                gap: 4px !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        _sb_title("⚙️ הגדרות מתקדמות", "tight")
        with st.expander(_nm("📈 מעקב אחזקות"), key="exp_holdings_alert"):
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

        with st.expander(_nm("💵 השקעה וסיכון"), key="exp_investment"):
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

        with st.expander(_nm("💰 עמלות ומיסים"), key="exp_fees"):
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

        with st.expander("התראות בטלגרם", key="exp_message_types"):
            _saved_msg_types = cfg.get("telegram_message_types", {})
            for _mt_key, _mt_label in notifier.MESSAGE_TYPES.items():
                if _tester_user_active and _mt_key.startswith("health_"):
                    continue  # הודעות בריאות המערכת - של הבעלים בלבד
                st.checkbox(
                    _mt_label, value=bool(_saved_msg_types.get(_mt_key, True)),
                    key=f"settings_msgtype_{_mt_key}", on_change=_autosave_message_types,
                )

    with st.container(border=True, key="channels_card"):
        st.markdown(
            """
            <style>
            div[class*="st-key-channels_card"] {
                border-radius: 10px;
                border-right: 3px solid #3B6EA5;
                padding-top: 0px !important;
            }
            div[data-testid="stVerticalBlock"][class*="st-key-channels_card"] {
                gap: 4px !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        _sb_title("📢 ערוצי התראה", "tight2")
        ch1, ch2, _ch3 = st.columns([1.3, 1.3, 1.4])
        ch1.checkbox(
            "טלגרם", value=bool(cfg.get("telegram", {}).get("enabled", True)),
            key="settings_telegram_enabled", on_change=_autosave_channels,
        )
        if not _tester_user_active:  # התראות דסקטופ הן רק של הבעלים (מחשב מקומי); לבודק אין להן משמעות
            ch2.checkbox(
                "דסקטופ", value=bool(cfg.get("desktop_notifications", {}).get("enabled", True)),
                key="settings_desktop_enabled", on_change=_autosave_channels,
            )

    if _config_mod.tester_mode() and _config_mod.tester_user() and _user_sync.configured():
        @st.cache_data(ttl=20, show_spinner=False)
        def _tester_tg_status(_uid: str) -> dict:
            try:
                return _user_sync.telegram_status(_uid)
            except Exception:
                return {"connected": False, "link": ""}

        with st.container(border=True, key="tester_tg_card"):
            _sb_title("📲 התראות בטלגרם", "tight2")
            _tg = _tester_tg_status(_config_mod.tester_user())
            if _tg["connected"]:
                st.markdown("מחובר ✅ — תקבל כאן התראות קנייה חדשות. לניתוק: שלח /stop לבוט.")
            elif _tg["link"]:
                st.markdown("לקבלת התראות קנייה חדשות בטלגרם: פתח את הקישור ולחץ Start. החיבור מתעדכן תוך כמה דקות.")
                st.link_button("חבר טלגרם", _tg["link"])
            else:
                st.markdown("חיבור הטלגרם עדיין לא הוגדר.")

            # רמת הסיגנל להתראות ירידה: הדבר היחיד שאין לו מקבילה בסיידבר של הבעלים (אצלו מגיעות כל ההתראות). כל שאר ההתראות נקבעות
            # בסיידבר עצמו (מדדים, אחוזי ירידה, סוגי התראה, ערוץ טלגרם, עמלות ומיסים) ונשמרות בריפו הפרטי.
            def _save_tester_signals():
                _tester_publish_prefs(signals=list(st.session_state.get("tprefs_signals") or []))

            _cur_signals = _user_sync.read_local_prefs(os.path.join(ROOT_DIR, "tester_prefs.json"))["signals"]
            st.markdown("**רמת סיגנל להתראות ירידה**")
            st.pills(
                "רמת סיגנל", ["buy", "wait", "avoid"], selection_mode="multi", label_visibility="collapsed",
                format_func=lambda k: strategy_mod.SIGNAL_LABEL[k],
                default=None if "tprefs_signals" in st.session_state else _cur_signals,
                key="tprefs_signals", on_change=_save_tester_signals,
                help="איזה סיגנל להתראות הירידה שתקבל בטלגרם. ברירת מחדל: לקנות בלבד.",
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
    if "thin_print" not in df.columns:
        df["thin_print"] = False
    column_order = ["שער", "שינוי מצטבר (%)", "שינוי יומי (%)", "טיקר", "company_name",
                     "last_close_date", "is_stale", "index_name", "prev_close_gap", "prev_close_date", "thin_print"]
    return df[column_order]








def _trading_days_held(bought_date, country_code: str) -> int:
    """ימי מסחר מיום הקנייה עד היום (כולל שניהם) - אופק האסטרטגיה הוא ימי מסחר, לא ימי לוח."""
    if bought_date is None:
        return 1
    today = israel_today()
    n, day = 0, bought_date
    while day <= today:
        if is_trading_day(country_code, day):
            n += 1
        day += dt.timedelta(days=1)
    return max(n, 1)


def _alert_signal(r) -> tuple[str, str]:
    """סיגנל 🟢/🟡/🔴 להתראה (שורת DataFrame/dict) - ר' strategy.entry_signal."""
    _scan_ts = r.get("scan_ts")
    try:
        _hour = int(str(_scan_ts)[11:13])
    except Exception:
        _hour = None
    return strategy_mod.entry_signal(
        r.get("index_name"), r.get("pct_change"),
        r.get("intraday_recovery_pct"), r.get("dist_from_ma50_pct"),
        sector=r.get("sector"), alert_hour=_hour,
    )


def _alert_score(r) -> int | None:
    """ניקוד הסיגנל של התראה (מתוך MAX_SIGNAL_SCORE) - אותם נתונים כמו _alert_signal."""
    try:
        _hour = int(str(r.get("scan_ts"))[11:13])
    except Exception:
        _hour = None
    try:
        return strategy_mod.signal_score(
            r.get("index_name"), r.get("pct_change"), r.get("intraday_recovery_pct"), r.get("dist_from_ma50_pct"),
            r.get("sector"), _hour,
        )[0]
    except Exception:
        return None









def _v3_stock_rows(sub_df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in sub_df.iterrows():
        out.append({
            "name": r["company_name"] or r["טיקר"], "mono": str(r["טיקר"]).replace(".TA", ""),
            "daily": None if pd.isna(r["שינוי יומי (%)"]) else float(r["שינוי יומי (%)"]),
            "cum": None if pd.isna(r["שינוי מצטבר (%)"]) else float(r["שינוי מצטבר (%)"]),
            "price": _price_text(r["שער"], r["index_name"]),
            "warn": bool(r.get("prev_close_gap") or r.get("thin_print")),
        })
    return out


def _nav_stale_css() -> str:
    """אחרי מעבר טאב Streamlit משאיר על המסך את התוכן הדהוי של הטאב הקודם עד שהריצה נגמרת (עשרות שניות בריצה קרה).
    בריצה הראשונה אחרי הלחיצה מסתירים אותו; בריצות הבאות (מסננים וכו') לא - הסתרה שם הייתה גורמת לעמוד "לקפוץ"."""
    if st.session_state.pop("_nav_fresh", False):
        return '<style>[data-testid="stMain"] [data-stale="true"] { display: none !important; }</style>'
    return ""


def _render_movers_v3() -> None:
    """טאב 'מניות מובילות' בעיצוב v3 (המוקאפ שאושר): כותרת + טריות, מדד + ימים, שתי טבלאות (ירידה/עלייה), מניות במעקב."""
    scanning_indices = cfg.get("indices") or ALL_INDICES
    # הבחירה האחרונה (מדד, ימים) נשמרת בין כניסות - כמו בשאר הטאבים עם מסננים
    _restore_filter_prefs({"movers_index_select": ("TA35", list(SCAN_INDEX_ORDER))})
    # הימים: ערך התחלתי מהבחירה השמורה (value=), ולא דרך session_state - אחרת value=None והשדה מקבל כפתור ניקוי (⊗)
    _saved_days = _load_ui_prefs().get("movers_cumulative_days")
    _days_default = _saved_days if isinstance(_saved_days, int) and 2 <= _saved_days <= 10 else 3
    movers_index = st.session_state.get("movers_index_select") or "TA35"
    movers_days = int(st.session_state.get("movers_cumulative_days", _days_default))
    movers_df = get_all_changes(movers_index, movers_days)

    fresh, stale_note = "היום", ""
    if not movers_df.empty:
        _rep = movers_df["last_close_date"].max()
        if not (_rep == israel_today() and is_market_open(movers_index)) and pd.notna(_rep):
            fresh = f"סגירה {_rep.strftime('%d.%m')}"
            if market_data.is_data_stale(_rep, "X.TA" if movers_index in ("TA35", "TA125") else ""):
                fresh += " · נתון ישן"
    st.markdown(f'{_nav_stale_css()}<div class="v3h">{ui_v3.movers_head("מניות מובילות", "" if fresh == "היום" else fresh, 0 if fresh == "היום" else None, icons=2)}</div>', unsafe_allow_html=True)

    def _toggle_movers_filters() -> None:
        st.session_state["movers_filters_open"] = not st.session_state.get("movers_filters_open", False)

    def _movers_index_keep() -> None:  # לחיצה על המדד שכבר נבחר מבטלת אותו - חוזרים לאחרון ששמור
        if st.session_state.get("movers_index_select") is None:
            st.session_state["movers_index_select"] = _load_ui_prefs().get("movers_index_select", "TA35")

    # on_click (ולא st.rerun באמצע הסקריפט): rerun לפני שהפקדים נרשמו מאפס את הבחירות שלהם
    st.button("רענון", key="movers_refresh_icon", on_click=get_all_changes.clear)
    st.button(" ", key="movers_filter_icon", on_click=_toggle_movers_filters)
    # הווידג'טים תמיד מוצגים (אחרת Streamlit מאפס את הבחירה); כשהסינון סגור הם מוסתרים ב-CSS
    st.markdown(
        '<style>div[class*="st-key-movers_controls"] { display:' + ("block" if st.session_state.get("movers_filters_open", False) else "none") + '; }</style>',
        unsafe_allow_html=True,
    )

    with st.container(key="movers_controls"):
        _c_idx, _c_days = st.columns([3, 2])
        with _c_idx:
            st.segmented_control(
                "מדד לצפייה", SCAN_INDEX_ORDER, format_func=lambda i: INDEX_LABELS[i],
                default=None if st.session_state.get("movers_index_select") is not None else "TA35",
                selection_mode="single", key="movers_index_select", label_visibility="collapsed", on_change=_movers_index_keep,
            )
        with _c_days:
            st.number_input(
                "ימים לחישוב שינוי מצטבר", min_value=2, max_value=10, step=1,
                value=_days_default,
                key="movers_cumulative_days", label_visibility="collapsed",
            )
    _save_filter_prefs(("movers_index_select", "movers_cumulative_days"))
    if movers_index not in scanning_indices:
        st.caption(f"{INDEX_LABELS[movers_index]} לא נמצא ברשימת המדדים שנסרקים להתראות - זו צפייה בלבד.")

    if movers_df.empty:
        st.warning("לא התקבלו נתונים - אין חיבור למקור הנתונים.")
    else:
        _rows = _v3_stock_rows

        up_df = movers_df[movers_df["שינוי יומי (%)"] >= 0].sort_values("שינוי יומי (%)", ascending=False)
        down_df = movers_df[movers_df["שינוי יומי (%)"] < 0].sort_values("שינוי יומי (%)")
        with st.container(key="movers_columns_row"):
            col_down, col_up = st.columns(2, gap="large")
            for col, sub, title, kind, flag in ((col_down, down_df, "מניות בירידה", "down", "down"), (col_up, up_df, "מניות בעלייה", "up", "up")):
                with col:
                    _expanded = st.session_state.get(f"movers_expand_{flag}", False)
                    _shown = sub if _expanded else sub.head(8)
                    st.markdown(
                        f'<div class="v3h">{ui_v3.colored_head(title, len(sub), kind)}{ui_v3.stocks_table(_rows(_shown), movers_days)}</div>',
                        unsafe_allow_html=True,
                    )
                    if len(sub) > 8:
                        if st.button(("הצג פחות" if _expanded else f"הצג את כל {len(sub)}"), key=f"movers_more_{flag}"):
                            st.session_state[f"movers_expand_{flag}"] = not _expanded
                            st.rerun(scope="fragment")

    # מניות במעקב
    _wl_conn = store.get_conn(db_path(cfg))
    _wl_items = store.get_watchlist(_wl_conn)
    _wl_conn.close()
    _wl_rows = []
    if _wl_items:
        _wl_daily_df = get_current_changes_for(tuple({it["ticker"] for it in _wl_items}))
        for it in _wl_items:
            _match = _wl_daily_df[_wl_daily_df["ticker"] == it["ticker"]]
            _cur = get_current_price(it["ticker"])
            if _cur is None and not _match.empty:
                _cur = _match.iloc[0]["last_close"]
            _wl_added = dt.datetime.fromisoformat(it["added_at"])
            _wl_country = constituents.INDEX_COUNTRY_CODE.get(it["index_name"], "IL")
            _wl_days, _wl_day = 0, _wl_added.date()
            while _wl_day <= israel_today():  # ימי מסחר מיום ההוספה ועד היום (כולל), כמו "ימי החזקה" ביומן העסקאות
                if is_trading_day(_wl_country, _wl_day):
                    _wl_days += 1
                _wl_day += dt.timedelta(days=1)
            _wl_rows.append({
                "id": it["id"], "name": it["company_name"] or it["ticker"], "mono": str(it["ticker"]).replace(".TA", ""),
                "added": _wl_added.strftime("%d.%m.%y"), "days": max(_wl_days, 1),
                "ret": ((_cur / it["entry_price"] - 1) * 100.0) if _cur is not None else None,
                "entry": _price_text(it["entry_price"], it["index_name"]),
                "price": _price_text(_cur, it["index_name"]) if _cur is not None else "—",
            })
    # ניהול המעקב: אייקון הוספה (+) בקצה השמאלי של כותרת הסעיף (כמו הרענון והמשפך בשאר הטאבים) פותח לוח הוספה/הסרה
    def _toggle_watch_manage() -> None:
        st.session_state["watch_manage_open"] = not st.session_state.get("watch_manage_open", False)

    def _remove_watch_item(item_id: int) -> None:
        _c = store.get_conn(db_path(cfg))
        try:
            store.remove_watchlist_item(_c, item_id)
        finally:
            _c.close()
        _sync_and_warn("watchlist changed", include_db=True)

    with st.container(key="movers_watch_section"):
        st.markdown(
            f'<div class="v3h"><section class="block">{ui_v3.head("מניות במעקב")}'
            f'{ui_v3.watchlist_head() if _wl_rows else ""}</section></div>',
            unsafe_allow_html=True,
        )
        st.button(" ", key="watch_manage_icon", on_click=_toggle_watch_manage)
        with st.container(key="movers_watch_rows"):
            for _wr in _wl_rows:
                with st.container(key=f"wl_row_{_wr['id']}"):
                    st.markdown(f'<div class="v3h">{ui_v3.watchlist_row(_wr)}</div>', unsafe_allow_html=True)
                    st.button("✕", key=f"wl_rm_{_wr['id']}", on_click=_remove_watch_item, args=(_wr["id"],))
        if st.session_state.get("watch_manage_open", False):
            with st.container(key="movers_watch_actions"):
                with st.container(horizontal=True, vertical_alignment="bottom", key="movers_watch_add_row"):
                    _wl_add_index = st.selectbox("מדד", SCAN_INDEX_ORDER, format_func=lambda i: INDEX_LABELS[i], key="watchlist_add_index")
                    _wl_add_tickers = constituents.get_constituents(_wl_add_index)
                    _wl_add_name_map = (
                        constituents.get_il_name_map(_wl_add_index) if _wl_add_index.upper() in ("TA35", "TA125")
                        else constituents.get_us_name_map(_wl_add_index)
                    )
                    _wl_add_options = sorted(_wl_add_tickers, key=lambda t: _wl_add_name_map.get(t, t))
                    _wl_add_labels = {t: f"{_wl_add_name_map.get(t, t)} ({t})" for t in _wl_add_options}
                    _wl_add_chosen = st.selectbox("מניה", _wl_add_options, format_func=lambda t: _wl_add_labels[t], key="watchlist_add_ticker")
                    # שער ביצוע: ברירת המחדל היא השער הנוכחי של המניה שנבחרה (ניתן לשינוי). בבורסת ת"א מזינים באגורות,
                    # כמו בטפסי הפוזיציה. מפתח נפרד לכל מניה, כדי שהערך ההתחלתי יתעדכן כשמחליפים מניה
                    _wl_is_il = market_data._is_israeli_ticker(_wl_add_chosen)
                    _wl_cur_px = get_current_price(_wl_add_chosen)
                    _wl_default_px = None if _wl_cur_px is None else round(_wl_cur_px * (100.0 if _wl_is_il else 1.0), 2)
                    _wl_exec_raw = st.number_input(
                        "שער ביצוע", min_value=0.0, value=_wl_default_px, step=1.0 if _wl_is_il else 0.01,
                        format="%.2f", key=f"watchlist_add_exec_{_wl_add_chosen}_{st.session_state.get('wl_exec_nonce', 0)}", placeholder="שער",
                    )
                    _wl_add_clicked = st.button("הוספה למעקב", key="watchlist_add_btn")
                if _wl_add_clicked:
                    if _wl_exec_raw:
                        _wl_entry_price = (_wl_exec_raw / 100.0) if _wl_is_il else _wl_exec_raw
                    else:
                        _wl_entry_price = get_current_price(_wl_add_chosen)
                    if _wl_entry_price is None:
                        st.warning("לא הצלחתי לשלוף מחיר נוכחי כרגע - נסה שוב בעוד רגע.")
                    else:
                        _wl_add_conn = store.get_conn(db_path(cfg))
                        store.add_watchlist_item(
                            _wl_add_conn, _wl_add_chosen, _wl_add_name_map.get(_wl_add_chosen), _wl_add_index, _wl_entry_price,
                        )
                        _wl_add_conn.close()
                        # מפתח חדש (ולא pop של הישן): ווידג'ט שכבר נשלח מהדפדפן שומר את הערך האחרון, ולכן השדה חוזר לשער הנוכחי רק עם מפתח שונה
                        st.session_state["wl_exec_nonce"] = st.session_state.get("wl_exec_nonce", 0) + 1
                        _sync_and_warn("watchlist changed", include_db=True)
                        st.rerun()


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
            _render_movers_v3()
            return

        _render_movers_tab()

def _open_position_form(chosen_row, key_prefix: str) -> None:
    with st.container(key=f"openpos_form_{key_prefix}"):
        _open_position_form_body(chosen_row, key_prefix)


def _open_position_form_body(chosen_row, key_prefix: str) -> None:
    """טופס פתיחת פוזיציה (שער ביצוע / עלות / תאריך / עסקה ידנית) להתראה אחת.
    משותף ל"➕ פתיחת פוזיציה" בטאב אחזקות ולכפתור בתוך ההתראה עצמה (7.10.2026) - אותו
    קוד בדיוק, כדי ששניהם יישארו עקביים (שער באגורות לת"א, שדות ריקים בכוונה)."""
    is_il = market_data._is_israeli_ticker(chosen_row["ticker"])
    add_trade_date = st.date_input(
        "תאריך ביצוע העסקה", value=dt.date.today(), key=f"{key_prefix}_trade_date",
        format="DD/MM/YYYY",
        help="אם לא הזנת את האחזקה באותו יום שקנית בפועל - כדי שספירת ימי ההחזקה תהיה נכונה.",
    )
    ac1, ac2 = st.columns(2)
    # value=None (שדה ריק באמת, לא "0"): עם value=0.0 הסמן נפתח *לפני* ה-"0" המוצג, אז הקלדת
    # 4636 הפכה ל-46360 - 0 מיותר שנוסף בסוף בכל הזנה (נאוויטס וקמטק, 7.10.2026).
    add_entry_raw = ac1.number_input(
        "שער ביצוע", min_value=0.0, value=None,
        step=1.0 if is_il else 0.01, format="%.2f", key=f"{key_prefix}_entry", placeholder="0",
    )
    add_entry = ((add_entry_raw or 0.0) / 100.0) if is_il else (add_entry_raw or 0.0)
    add_amount_raw = ac2.number_input(
        "עלות", min_value=0.0, value=None, step=100.0, format="%.2f",
        key=f"{key_prefix}_amount", placeholder="0",
        help="העלות הכוללת כפי שמופיעה בבנק. הכמות מחושבת ממנה אוטומטית (עלות ÷ שער ביצוע).",
    )
    add_amount = add_amount_raw or 0.0
    if add_entry > 0 and add_amount > 0:
        try:
            _cc = "IL" if is_il else "US"
            _res = fees.compute_net_result(
                country_code=_cc, buy_price=add_entry, sell_price=add_entry * (1 + strategy_mod.target_frac()),
                position_size_ccy=add_amount, holding_days=strategy_mod.HOLD_MAX_DAYS, fees_cfg=cfg["fees"],
            )
            _ccy_sym = CURRENCY_SYMBOLS.get(_res.currency, _res.currency)
            _fee_share = (_res.total_commission / _res.gross_pnl * 100) if _res.gross_pnl > 0 else 0
            _note = (f" · העמלות אוכלות {_fee_share:.0f}% מהרווח הגולמי - פוזיציה גדולה יותר תשפר" if _fee_share >= 35 else "")
            st.caption(
                f"אם יגיע ליעד (+{strategy_mod.target_pct():.0f}%): רווח נטו "
                f"{_signed_num(_res.net_pnl, 0)} {_ccy_sym} ({_signed_num(_res.net_return_pct, 1, '%')}) "
                f"אחרי עמלות ומס{_note}"
            )
        except Exception:
            pass
    with st.container(key=f"{key_prefix}_manualwrap"):
        add_is_manual = st.toggle("עסקה ידנית", key=f"{key_prefix}_manual")
        st.caption("לא לפי האסטרטגיה - לא תיכלל בסטטיסטיקת הביצועים")
    if st.button("הוסף לאחזקות", key=f"{key_prefix}_btn", type="primary"):
        final_qty = (add_amount / add_entry) if (add_amount > 0 and add_entry > 0) else 0.0
        # מניות בבורסה נסחרות ביחידות שלמות - כשהכמות המחושבת קרובה (עד 1%) לשלם, מעגלים אליו
        # (אחרת עיגולי מחיר ממוצע הפכו 92 ל-91.994 בפוזיציה ששמרנו).
        if is_il and final_qty > 0 and abs(final_qty - round(final_qty)) / final_qty < 0.01:
            final_qty = float(round(final_qty))
        _ref = chosen_row.get("last_close")
        if add_entry <= 0 or final_qty <= 0:
            st.warning("יש למלא שער ביצוע ועלות לפני ההוספה.")
        elif _ref is not None and pd.notna(_ref) and _ref > 0 and abs(add_entry / _ref - 1) > 0.4:
            # 7.10.2026: קמטק נרשמה פי 10 מהמחיר האמיתי (אגורות הוזנו כשקלים) - חוסמים
            # שער שרחוק מעל 40% ממחיר ההתראה, כמעט תמיד טעות הקלדה.
            _shown = f"{_ref * 100:,.0f} אג'" if is_il else f"{_ref:,.2f}"
            st.error(f"שער הביצוע שהוזן רחוק מאוד ממחיר ההתראה ({_shown}) - בדוק יחידות (אגורות/שקלים).")
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
            for _clear_key in ("entry", "amount", "manual"):
                st.session_state.pop(f"{key_prefix}_{_clear_key}", None)
            load_alerts.clear()
            st.rerun()


_ALERT_REASON_LABELS = {
    "market_wide": "יום חלש בשוק", "sector_pressure": "לחץ סקטוריאלי", "earnings_reaction": "תגובה לדוח",
    "profit_taking": "מימושים אחרי עלייה", "stock_specific_news": "חדשות ספציפיות", "ex_dividend": "ניתוק דיבידנד (טכני)",
    "unclear": "לא נמצאה סיבה ברורה",
}
_SIG_WORD = {"buy": "לקנות", "wait": "לחכות", "avoid": "לא לקנות"}


def _filter_dot_css(icon_key: str, active: bool) -> str:
    """נקודה קטנה על אייקון המשפך כשיש סינון פעיל (והלוח סגור או פתוח - כדי שתמיד ברור שהטבלה מסוננת)."""
    if not active:
        return ""
    return (
        f'div[class*="st-key-{icon_key}"] button::after {{ content: ""; position: absolute; top: 4px; inset-inline-end: 3px; '
        f'width: 6px; height: 6px; border-radius: 50%; background: var(--v3-accent); }}'
    )


def _alert_price(value, index_name) -> str:
    """שער בטבלת ההתראות (v3): מספר שלם בלי סמל מטבע - השוק ברור מהסינון והשם, ות"א נסחר באגורות."""
    if pd.isna(value):
        return "—"
    return _level_text(value, constituents.INDEX_CURRENCY.get(index_name, "ILS") == "ILS")


@st.cache_data(ttl=600)
def _live_expected_max_drop_pct() -> float | None:
    """"צפי לנמוך היומי": חציון הירידה (מסגירה קודמת עד שפל היום) בכל ההתראות ההיסטוריות - אותו חישוב כמו בסורק."""
    from src import scanner as _scanner
    _c = store.get_conn(db_path(cfg))
    try:
        return _scanner._historical_expected_max_drop_pct(_c)
    finally:
        _c.close()


def _render_alerts_v3(todays_alerts: pd.DataFrame, is_fallback_day: bool, last_scan_date: str | None, after_header=None) -> None:
    """טבלת 'התראות היום' בעיצוב v3 (המוקאפ שאושר): סיכום, מסננים, שורות שנפתחות לפרטי ההתראה, פתיחת פוזיציה."""
    st.session_state.setdefault("open_alert_id", None)
    n_total = len(todays_alerts)
    title = "התראות"  # כותרת במילה אחת, כמו בשאר הטאבים
    # מסחר סגור (סופ"ש/חג/לפני הפתיחה): התאריך של יום המסחר שההתראות שייכות לו מופיע בכותרת
    _closed_date_text = ""
    if is_fallback_day and last_scan_date:
        try:
            _closed_date_text = "יום מסחר " + dt.date.fromisoformat(last_scan_date).strftime("%d.%m")
        except Exception:
            pass
    st.markdown(
        f'{_nav_stale_css()}<div class="v3h">{ui_v3.movers_head(title, _closed_date_text, None, icons=3)}</div>', unsafe_allow_html=True,
    )
    # on_click (ולא st.rerun באמצע הסקריפט): rerun לפני שהמסננים נרשמו מאפס את הבחירות שלהם
    def _toggle_alerts_filters() -> None:
        st.session_state["alerts_filters_open"] = not st.session_state.get("alerts_filters_open", False)

    def _toggle_alerts_add() -> None:
        st.session_state["alerts_add_open"] = not st.session_state.get("alerts_add_open", False)

    st.button("רענון", key="alerts_refresh_icon", on_click=load_alerts.clear)
    st.button(" ", key="alerts_filter_icon", on_click=_toggle_alerts_filters)
    st.button(" ", key="alerts_add_icon", on_click=_toggle_alerts_add)  # התראת מחיר ידנית: נפתחת מהפלוס שבכותרת
    if after_header is not None:
        after_header()  # טופס התראת מחיר ידנית: מיד מתחת לכותרת

    # נתוני שורה: סיגנל, ניקוד, גורמים, מחירים מעוצבים, שעה
    _tickers = tuple(sorted(todays_alerts["ticker"].unique())) if n_total else ()
    _cur_df = get_current_changes_for(_tickers) if _tickers else pd.DataFrame()
    _md_days = cfg.get("multi_day_window_days", 3)
    _md_thr = abs(cfg["drop_threshold_pct"])
    _nd_map = {}
    if not _cur_df.empty and "history" in _cur_df.columns:
        for _t, _h in zip(_cur_df["ticker"], _cur_df["history"]):
            _nd_map[_t] = market_data.compute_n_day_change_pct(_h, _md_days)

    _cur_map, _cur_gap, _cur_px = {}, {}, {}
    _hist_map = dict(zip(_cur_df["ticker"], _cur_df["history"])) if (not _cur_df.empty and "history" in _cur_df.columns) else {}
    if not _cur_df.empty:
        _cur_map = dict(zip(_cur_df["ticker"], _cur_df["pct_change"]))
        if "last_close" in _cur_df.columns:
            _cur_px = dict(zip(_cur_df["ticker"], _cur_df["last_close"]))
        if "prev_close_gap" in _cur_df.columns:
            _cur_gap = dict(zip(_cur_df["ticker"], _cur_df["prev_close_gap"].fillna(False)))

    items = []
    for _, r in todays_alerts.iterrows():
        try:
            _h = int(str(r.get("scan_ts"))[11:13])
        except Exception:
            _h = None
        score, parts = strategy_mod.signal_score(
            r.get("index_name"), r["pct_change"], r.get("intraday_recovery_pct"), r.get("dist_from_ma50_pct"), r.get("sector"), _h,
        )
        key = (strategy_mod.SIGNAL_BUY if score >= strategy_mod.buy_min_score()
               else strategy_mod.SIGNAL_WAIT if score >= strategy_mod.wait_min_score() else strategy_mod.SIGNAL_AVOID)
        change, change_note = r["pct_change"], ""
        if change > -_md_thr:
            _nd = _nd_map.get(r["ticker"])
            if _nd is not None and pd.notna(_nd) and _nd < 0:
                change, change_note = _nd, f" ב־{_md_days} ימים"
        _ts = post_alert._alert_ts(r.get("scan_ts"))
        items.append({
            "row": r, "id": int(r["id"]), "key": key, "score": score, "parts": parts, "change": change, "note": change_note,
            "is_il": (r.get("index_name") or "").upper() in ("TA35", "TA125"),
            "ts": _ts.tz_convert("UTC") if _ts is not None else pd.NaT,
            "hhmm": str(r.get("scan_ts"))[11:16],
        })
    now_utc = pd.Timestamp.now(tz="UTC")
    for it in items:
        it["is_new"] = bool(pd.notna(it["ts"]) and (now_utc - it["ts"]) <= pd.Timedelta(minutes=30))

    n_buy = sum(1 for i in items if i["key"] == "buy")
    n_wait = sum(1 for i in items if i["key"] == "wait")
    n_avoid = sum(1 for i in items if i["key"] == "avoid")
    st.markdown(
        '<div class="v3h">' + ui_v3.kpi4([
            ("כל ההתראות", str(n_total), ""), ("לקנות", str(n_buy), "up"), ("לחכות", str(n_wait), "warn"), ("לא לקנות", str(n_avoid), "down"),
        ], compact=True) + "</div>", unsafe_allow_html=True,
    )

    _restore_filter_prefs({
        "alerts_filter_sig": ("כל הסיגנלים", ["לקנות", "לחכות", "לא לקנות", "כל הסיגנלים"]),
        "alerts_filter_mkt": ("כל השווקים", ['בורסת ת"א', "וול סטריט", "כל השווקים"]),
        "alerts_sort_mode": ("זמן", ["סיגנל", "זמן"]),
    })
    # הווידג'טים תמיד מוצגים (אחרת Streamlit מאפס את הבחירה) - כשהלוח סגור הוא מוסתר ב-CSS
    st.markdown(
        '<style>div[class*="st-key-alerts_filters"] { display:' + ("block" if st.session_state.get("alerts_filters_open", False) else "none") + '; }'
        + _filter_dot_css("alerts_filter_icon", st.session_state.get("alerts_filter_sig") != "כל הסיגנלים" or st.session_state.get("alerts_filter_mkt") != "כל השווקים" or st.session_state.get("alerts_sort_mode") != "זמן")
        + '</style>',
        unsafe_allow_html=True,
    )
    with st.container(key="alerts_filters"):
        _f1, _f2, _f3 = st.columns([3, 2, 2])
        # "הכל" בסוף כל בורר, מסומן כברירת מחדל; לחיצה על האפשרות הנבחרת לא מבטלת אותה (חוזרים ל"הכל")
        _ALL_LABEL = {"alerts_filter_sig": "כל הסיגנלים", "alerts_filter_mkt": "כל השווקים"}

        def _all_if_empty(_key: str) -> None:
            if st.session_state.get(_key) in (None, "הכל"):
                st.session_state[_key] = _ALL_LABEL[_key]

        for _k in _ALL_LABEL:
            _all_if_empty(_k)
        with _f1:
            _sig_filter = st.segmented_control(
                "סינון לפי סיווג", ["לקנות", "לחכות", "לא לקנות", "כל הסיגנלים"], selection_mode="single",
                key="alerts_filter_sig", label_visibility="collapsed", on_change=_all_if_empty, args=("alerts_filter_sig",),
            ) or "כל הסיגנלים"
        with _f2:
            _mkt_filter = st.segmented_control(
                "שוק", ['בורסת ת"א', "וול סטריט", "כל השווקים"], selection_mode="single", key="alerts_filter_mkt", label_visibility="collapsed",
                on_change=_all_if_empty, args=("alerts_filter_mkt",),
            )
        with _f3:
            # המיון בפועל תמיד מסומן (ברירת מחדל: זמן); לחיצה על האפשרות שכבר נבחרה לא מבטלת אותה
            st.session_state.setdefault("alerts_sort_mode", "זמן")

            def _keep_sort() -> None:
                if st.session_state.get("alerts_sort_mode") is None:
                    st.session_state["alerts_sort_mode"] = "זמן"

            _sort_mode = st.segmented_control(
                "מיון", ["סיגנל", "זמן"], selection_mode="single", key="alerts_sort_mode", label_visibility="collapsed", on_change=_keep_sort,
            ) or "זמן"
    _save_filter_prefs(("alerts_filter_sig", "alerts_filter_mkt", "alerts_sort_mode"))

    shown = [i for i in items if (_sig_filter == "כל הסיגנלים" or _SIG_WORD[i["key"]] == _sig_filter)]
    if _mkt_filter == 'בורסת ת"א':
        shown = [i for i in shown if i["is_il"]]
    elif _mkt_filter == "וול סטריט":
        shown = [i for i in shown if not i["is_il"]]
    if _sort_mode == "סיגנל":
        shown.sort(key=lambda i: (-i["score"], -abs(i["row"]["pct_change"]), -(i["ts"].value if pd.notna(i["ts"]) else 0)))
    else:
        shown.sort(key=lambda i: -(i["ts"].value if pd.notna(i["ts"]) else 0))

    if not shown:
        st.markdown('<div class="v3h"><div class="nw"><small>אין התראות להצגה.</small></div></div>', unsafe_allow_html=True)
        return

    st.markdown(f'<div class="v3h tw">{ui_v3.alerts_header()}</div>', unsafe_allow_html=True)
    for it in shown:
        r = it["row"]
        rid = it["id"]
        is_open = st.session_state["open_alert_id"] == rid
        idx_name = r.get("index_name")
        _ch = it["change"]
        change_html = f'<span class="{ui_v3.cls_for(_ch)}">{ui_v3.num(ui_v3.signed(_ch, 1, "%"))}{esc_note(it["note"])}</span>'
        _cv = _cur_map.get(r["ticker"])
        if _cv is None or pd.isna(_cv) or _cur_gap.get(r["ticker"]):  # בסיס השוואה ישן - לא מציגים שינוי יומי מטעה
            cur_html = '<span style="color:var(--dim)">—</span>'
            cur_px_text = "—"
        else:
            cur_html = f'<span class="{ui_v3.cls_for(_cv)}">{ui_v3.num(ui_v3.signed(_cv, 1, "%"))}</span>'
            cur_px_text = _alert_price(_cur_px.get(r["ticker"], float("nan")), idx_name)
        with st.container(key=f"v3_arow_{rid}"):
          with st.container(key=f"v3_arowhd_{rid}"):
            st.markdown(
                '<div class="v3h tw">' + ui_v3.alert_row(
                    r.get("company_name") or r["ticker"], str(r["ticker"]).replace(".TA", ""), it["is_new"], change_html,
                    it["key"], _SIG_WORD[it["key"]], f"{max(it['score'], 0)}/{strategy_mod.MAX_SIGNAL_SCORE}",
                    _alert_price(r.get("entry_limit"), idx_name),
                    _alert_price(r["last_close"] * (1 + strategy_mod.target_frac()), idx_name),
                    _alert_price(r.get("stop_loss"), idx_name), it["hhmm"], is_open, {"SP500": "SPX", "NASDAQ100": "NDX"}.get(idx_name, idx_name or ""), cur_html, cur_px=cur_px_text,
                ) + "</div>", unsafe_allow_html=True,
            )
            if st.button(" ", key=f"v3_open_alert_{rid}"):
                st.session_state["open_alert_id"] = None if is_open else rid
                st.rerun(scope="fragment")
          if is_open:
                _reasons = json.loads(r.get("reasons_json") or "[]")
                _reason = _ALERT_REASON_LABELS.get(_reasons[0], _reasons[0]) if _reasons else "לא ידוע"
                _over = r.get("overreaction_score")
                _over_cls = "" if pd.isna(_over) else ("up" if _over >= 70 else "" if _over >= 45 else "down")
                _qt = r.get("quality_tier")
                _q_known = bool(_qt) and _qt != "unknown" and pd.notna(r.get("quality_score"))
                _exp = r.get("expected_max_drop_pct")
                if _exp is None or pd.isna(_exp):  # התראות שנשמרו לפני שהשדה נשמר בפועל - החציון ההיסטורי החי
                    _exp = _live_expected_max_drop_pct()
                _flags_raw = r.get("quality_flags_json")
                _flags = json.loads(_flags_raw) if isinstance(_flags_raw, str) else []
                _news = json.loads(r.get("headlines_json") or "[]")
                _net = json.loads(r.get("net_result_json") or "{}")
                _prof = _net.get("profit_scenario") or {}
                _net_text = ""
                if _prof:
                    _sym = CURRENCY_SYMBOLS.get(_prof.get("currency"), _prof.get("currency", ""))
                    _sym = "₪" if _sym == 'ש"ח' else _sym
                    _size = (_prof.get("qty", 0) or 0) * (_prof.get("buy_price", 0) or 0)
                    # רווח ברוטו בהגעה ליעד המוצג בטבלה (אותו כניסה ויעד), בפוזיציה של הגודל שחושב להתראה
                    _entry_px = r.get("entry_limit")
                    _tgt_px = r["last_close"] * (1 + strategy_mod.target_frac())
                    _g = _size * (_tgt_px / _entry_px - 1) if (pd.notna(_entry_px) and _entry_px) else (_prof.get("gross_pnl", 0) or 0)
                    _net_text = (
                        f'<b class="up">{ui_v3.num(f"{_g:,.0f}")}&nbsp;{_sym}</b> בהגעה ליעד ובפוזיציה של {ui_v3.num(f"{_size:,.0f}")} {_sym}'
                    )
                with st.container(key=f"alert_card_{rid}"):
                    _card_top, _card_bottom = ui_v3.alert_detail(
                        it["parts"], get_sparkline_prices(r["ticker"]), _reason, None if pd.isna(_over) else float(_over),
                        float(r["quality_score"]) if _q_known else None, _over_cls,
                        {"high": "up", "low": "down"}.get(_qt, "") if _q_known else "",
                        float(_exp) if (pd.notna(_exp) and _exp > abs(r["pct_change"])) else None, _flags, _news, _net_text,
                        bool(r.get("bought") == 1),
                        levels=(_alert_price(r.get("entry_limit"), idx_name),
                                _alert_price(r["last_close"] * (1 + strategy_mod.target_frac()), idx_name),
                                _alert_price(r.get("stop_loss"), idx_name)),
                        quiet=it["key"] == "buy", split=True,
                    )
                    st.markdown('<div class="v3h">' + _card_top + '</div>', unsafe_allow_html=True)
                    with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"alert_cum_row_{rid}"):
                        _cum_lbl = st.empty()  # הטקסט נכתב אחרי שהבורר החזיר את מספר הימים (הוא מוצג לפניו, באותה שורה)
                        _cum_days = st.segmented_control(
                            "ימים לירידה מצטברת", [2, 3, 5, 10], default=3, selection_mode="single",
                            key="alert_cum_days", format_func=lambda v: f"{v} ימים", label_visibility="collapsed",
                        ) or 3
                    _cum_pct = market_data.compute_n_day_change_pct(_hist_map.get(r["ticker"]), int(_cum_days)) if _hist_map.get(r["ticker"]) is not None else None
                    _cum_txt = "—" if _cum_pct is None else f'<b class="{ui_v3.cls_for(_cum_pct)}">{ui_v3.num(ui_v3.signed(_cum_pct, 1, "%"))}</b>'
                    _cum_lbl.markdown(f'<div class="v3h cumline"><small>שינוי מצטבר</small> {_cum_txt}</div>', unsafe_allow_html=True)
                    st.markdown('<div class="v3h">' + _card_bottom + '</div>', unsafe_allow_html=True)
                    if r.get("bought") != 1:
                        with st.expander("פתיחת פוזיציה", key=f"open_pos_exp_{rid}"):
                            _lim = r.get("entry_limit")
                            if pd.notna(_lim):
                                _il = market_data._is_israeli_ticker(r["ticker"])
                                st.caption(f"לימיט כניסה מוצע: {_lim * 100:,.0f} אג'" if _il else f"לימיט כניסה מוצע: {_lim:,.2f}")
                            _open_position_form(r, f"alert_pos_{rid}")


def esc_note(note: str) -> str:
    return f'<small class="dim nt">{html.escape(note.strip().removeprefix("ב־"))} מצטבר</small>' if note else ""


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

            # פלייסהולדרים בסדר התצוגה המבוקש (התראה ידנית, טבלה, קרוב לסף,
            # כרטיסים) - לא סדר הריצה בפועל. st.container() נקבע במיקום שבו
            # הוא *נוצר*, לא במיקום שבו ממלאים אותו - בדיוק כמו _tab_slot_X
            # בטאבים אחרים בקובץ הזה. פרטי ההתראה נפתחים מתוך שורת הטבלה
            # עצמה (st.button + session_state בתוך הפרגמנט, ר' למטה) - לא
            # קטע נפרד מתחת לטבלה, לא <a href> (ניווט דפדפן אמיתי, שנבדק
            # ונמצא איטי בפועל). התראת מחיר ידנית למעלה (9.9.2026, בקשה מפורשת).
            # 7.10.2026: הועברה מתחת לטבלה; 18.11.2026: נפתחת בראש הטאב, מיד מתחת לכותרת (בקשה מפורשת)
            _slot_table = st.container()
            _slot_nearmiss = st.container()

            def _render_manual_price_alert() -> None:
                """טופס התראת מחיר ידנית. נקרא מתוך _render_alerts_v3 מיד מתחת לכותרת (עם הפלוס), כך שהוא נפתח בראש הטאב ומתחת לכותרת."""
                _pa_count_conn = store.get_conn(db_path(cfg))
                _pa_active_count = len(store.get_active_price_alerts(_pa_count_conn))
                _pa_count_conn.close()
                _pa_label = (f"🔔 התראת מחיר ידנית ({_pa_active_count})" if _pa_active_count else "🔔 התראת מחיר ידנית")
                _pa_label = _nm(_pa_label)
                _pa_key = "exp_price_alert" if st.session_state.get("alerts_add_open", False) else "exp_price_alert_closed"
                _pa_ctx = st.container(key=_pa_key)
                with _pa_ctx:
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
                                    _sync_and_warn("price alert cancelled", include_db=True)
                                    st.rerun(scope="fragment")
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
                    if st.button("הוסף התראה", key="price_alert_add_btn", type="primary"):
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
                            _sync_and_warn("price alert added", include_db=True)
                            st.session_state.pop("price_alert_target", None)
                            st.session_state.pop("price_alert_target_pct", None)
                            st.rerun(scope="fragment")
                    _pa_conn.close()

            if df.empty:
                with _slot_table:
                    _render_manual_price_alert()
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
                # 17.10.2026 (בקשת המשתמש): ממשיכים להציג את יום המסחר האחרון עד 10 דקות לפני פתיחת
                # המסחר בת"א (9:59 -> 9:49) - וגם בסופ"ש/חג, כשאין בכלל יום מסחר חדש שמתחיל.
                _il_open = MARKET_HOURS["IL"]["open"]
                _fallback_until = (dt.datetime.combine(israel_today(), dt.time(*_il_open)) - dt.timedelta(minutes=10)).time()
                _is_fallback_day = todays_alerts.empty and (
                    not is_trading_day("IL", israel_today()) or israel_now().time() < _fallback_until
                )
                # כלי פיתוח (סקירת עיצוב): DIPRADAR_ALERTS_PREVIEW_DATE=YYYY-MM-DD מציג יום מלא כאילו הוא "אחרון"; לא מוגדר בפרודקשן
                _preview_day = os.environ.get("DIPRADAR_ALERTS_PREVIEW_DATE")
                if _preview_day and (df["scan_date"] == _preview_day).any():
                    _is_fallback_day = True
                if _is_fallback_day:
                    _last_scan_date = _preview_day if (_preview_day and (df["scan_date"] == _preview_day).any()) else df["scan_date"].max()
                    todays_alerts = df[df["scan_date"] == _last_scan_date]

                _REBOUND_TIER_EMOJI = {"A": "🟢", "B": "🟡", "C": "🔴"}



                todays_display_src = todays_alerts.copy()
                # יעד לפי האסטרטגיה הנוכחית (+3% ממחיר ההתראה), גם להתראות שנשמרו עם יעד ישן -
                # לפני ההמרה לטקסט (אגורות/שקלים) שמתחת
                todays_display_src["target_base"] = (todays_display_src["last_close"] * (1 + strategy_mod.target_frac())).round(2)
                for _price_col in ("entry_limit", "target_base", "stop_loss"):
                    todays_display_src[_price_col] = todays_display_src.apply(
                        lambda r, c=_price_col: _price_text(r[c], r.get("index_name"), whole=True), axis=1,
                    )
                # סיווג ריבאונד (A/B/C) = הרמזור של האסטרטגיה + הניקוד המשוקלל, צבוע לפי הרמזור; הפירוט
                # (איזה גורם נתן כמה נקודות) בריחוף - ר' strategy.signal_score (7.10.2026).
                def _rebound_cell_html(r) -> str:
                    if pd.isna(r.get("pct_change")):
                        return "—"
                    try:
                        _h = int(str(r.get("scan_ts"))[11:13])
                    except Exception:
                        _h = None
                    _score, _parts = strategy_mod.signal_score(
                        r.get("index_name"), r["pct_change"], r.get("intraday_recovery_pct"),
                        r.get("dist_from_ma50_pct"), r.get("sector"), _h,
                    )
                    _k = (strategy_mod.SIGNAL_BUY if _score >= strategy_mod.buy_min_score()
                          else strategy_mod.SIGNAL_WAIT if _score >= strategy_mod.wait_min_score()
                          else strategy_mod.SIGNAL_AVOID)
                    _lines = "".join(
                        f'<div style="display:flex; align-items:baseline; gap:10px; padding:2px 0;">{_pts_chip(pts)}<span>{name}</span></div>'
                        for name, pts in _parts
                    ) or "<div>אין גורם תומך</div>"
                    _tip = (
                        f'<span class="sigtip-text sigtip-wide"><div style="font-weight:700; margin-bottom:3px; '
                        f'color:{SIGNAL_COLORS[_k]};">{strategy_mod.SIGNAL_LABEL[_k]} · ניקוד {max(_score, 0)} מתוך {strategy_mod.MAX_SIGNAL_SCORE}</div>{_lines}'
                        f'<div style="margin-top:4px; opacity:0.65; font-size:0.74rem;">{strategy_mod.buy_min_score()} ומעלה = לקנות · '
                        f'{strategy_mod.wait_min_score()}-{strategy_mod.buy_min_score() - 1} = לחכות · פחות = לא לקנות</div></span>'
                    )
                    # אות הסיווג גדולה וצבועה; הניקוד כטקסט ברור "ניקוד X מתוך 6" (מקסימום אפשרי 6, לקנות מ-4)
                    return (
                        f'<span class="sigtip sigtip-side">'
                        f'<span style="font-weight:800; font-size:1.05rem; color:{SIGNAL_COLORS[_k]};">'
                        f'{strategy_mod.rebound_class(_k)}</span>'
                        f'<span style="font-size:0.78rem; opacity:0.75; margin-inline-start:7px;">'
                        f'ניקוד {max(_score, 0)} מתוך {strategy_mod.MAX_SIGNAL_SCORE}</span>{_tip}</span>'
                    )

                todays_display_src["rebound_tier"] = todays_display_src.apply(_rebound_cell_html, axis=1)

                # שינוי נוכחי - נשלף בכל ריצה של הפרגמנט (run_every="60s") לרשימת
                # הטיקרים של היום בלבד, בנפרד מ"שינוי בזמן התראה" השמור שלא זז.
                _current_tickers = tuple(sorted(todays_alerts["ticker"].unique()))
                _current_changes_df = get_current_changes_for(_current_tickers)
                _current_changes_map = (
                    dict(zip(_current_changes_df["ticker"], _current_changes_df["pct_change"]))
                    if not _current_changes_df.empty else {}
                )
                todays_display_src["current_pct_change"] = todays_display_src["ticker"].map(_current_changes_map)
                # prev_close_gap - "שינוי נוכחי" מושווה מול בסיס (prev_close) שעלול
                # להיות ישן בכמה ימים (yfinance מדלגת יום מסחר לטיקר ספציפי, ר' הערה
                # ב-scanner.py) גם כש-last_close עצמו עדכני לגמרי - אז "שינוי יומי"
                # בפועל הוא שינוי מצטבר של כמה ימים, לא של אתמול בלבד, ושונה ממה
                # שהבנק/מקור אחר מראה (1.10.2026, "יש פער בין ההתראה... לבין מה
                # שאני רואה בבנק", KEN.TA - prev_close מ-29/09 בזמן שהיום 1/10).
                # כבר נבדק ומסומן בכל מקום אחר באתר (טבלת מניות מובילות/קרוב לסף/
                # אחזקות) - רק כאן, בטבלת ההתראות הראשית, היה חסר.
                _current_gap_map = (
                    dict(zip(_current_changes_df["ticker"], _current_changes_df["prev_close_gap"].fillna(False)))
                    if not _current_changes_df.empty and "prev_close_gap" in _current_changes_df.columns else {}
                )
                todays_display_src["current_gap"] = todays_display_src["ticker"].map(_current_gap_map).fillna(False)

                # מיון (7.10.2026): ברירת מחדל לפי ניקוד האסטרטגיה (הכי מעניינות למעלה); בשוויון - ירידה
                # גדולה יותר, ואז העדכנית ביותר. מתג מחזיר לסדר כרונולוגי. התראה מה-30 דקות האחרונות מסומנת "חדשה".
                def _row_score_value(r) -> int:
                    if pd.isna(r.get("pct_change")):
                        return -99
                    try:
                        _hh = int(str(r.get("scan_ts"))[11:13])
                    except Exception:
                        _hh = None
                    return strategy_mod.signal_score(
                        r.get("index_name"), r["pct_change"], r.get("intraday_recovery_pct"),
                        r.get("dist_from_ma50_pct"), r.get("sector"), _hh,
                    )[0]

                def _row_ts(v):
                    _t = post_alert._alert_ts(v)
                    return _t.tz_convert("UTC") if _t is not None else pd.NaT

                todays_display_src["_score"] = todays_display_src.apply(_row_score_value, axis=1)
                todays_display_src["_drop"] = todays_display_src["pct_change"].abs()
                # to_datetime(utc=True) - גם כשהטבלה ריקה (תחילת יום מסחר, אין עדיין התראות) העמודה חייבת להיות datetime,
                # אחרת החיסור למטה קורס (8.10.2026, TypeError: rsub dtype str)
                todays_display_src["_ts"] = pd.to_datetime(
                    todays_display_src["scan_ts"].map(_row_ts), utc=True, errors="coerce",
                )
                todays_display_src["_is_new"] = (
                    (pd.Timestamp.now(tz="UTC") - todays_display_src["_ts"]) <= pd.Timedelta(minutes=30)
                ).fillna(False).astype(bool)
                _sort_mode = st.session_state.get("alerts_sort_mode", "סיגנל")
                if _sort_mode == "סיגנל":
                    todays_display_src = todays_display_src.sort_values(
                        ["_score", "_drop", "_ts"], ascending=[False, False, False], na_position="last",
                    )
                else:
                    todays_display_src = todays_display_src.sort_values("_ts", ascending=False, na_position="last")

                alerts_display = todays_display_src.rename(columns={
                    "ticker": "טיקר", "company_name": "שם", "pct_change": "שינוי בזמן התראה",
                    "current_pct_change": "שינוי נוכחי",
                    "entry_limit": "לימיט כניסה", "target_base": "יעד מכירה", "stop_loss": "סטופ-לוס",
                    "overreaction_score": "תגובת יתר", "quality_score": "איכות פונדמנטלית",
                    "rebound_tier": "סיווג ריבאונד",
                })
                if "שם" not in alerts_display.columns:
                    alerts_display["שם"] = ""
                # מספר ני"ע - עמודה גלויה משלה, לא טקסט חבוי בטולטיפ (24.9.2026,
                # "אני רוצה את מספר ני"ע... זה צריך להיות יפה ויזואלית... גם
                # בהתראות"). מחושב לפני חיתוך ".TA" למטה, כי המיפוי לפי טיקר
                # מלא כמו שהוא ב-tase_symbols.csv. מושמט כליל ביום שכולו מניות
                # אמריקאיות - "מספר ני"ע" הוא מושג ישראלי בלבד, עמודת "—" שלמה
                # היא בלבול מיותר (24.9.2026, "למה למניות האמריקאיות את מספר
                # נייר?" - אותה הערה בדיוק כמו בטבלת "מניות מובילות").
                alerts_display["מספר ני\"ע"] = alerts_display["טיקר"].map(constituents.get_tase_security_id_map())
                _show_tase_id_col2 = alerts_display["מספר ני\"ע"].notna().any()
                alerts_display["טיקר"] = alerts_display["טיקר"].str.replace(".TA", "", regex=False)
                # "שם (טיקר)" - עמודת טיקר נפרדת בוטלה, אותו פורמט בדיוק כמו
                # "שם_וטיקר" בטבלת "קרוב לסף" (_render_movers_style_table) -
                # פינוי עמודה שלמה לרוחב לשאר העמודות הצפופות (9.9.2026,
                # בקשה מפורשת, אושר שאותו פורמט כבר עובד בלי בעיה במקום אחר).
                alerts_display["שם"] = alerts_display.apply(
                    lambda r: f'{r["שם"]} ({r["טיקר"]})' if pd.notna(r["שם"]) and r["שם"] else r["טיקר"],
                    axis=1,
                )
                _base_display_cols = ["id", "_is_new", "שם", "שינוי בזמן התראה", "שינוי נוכחי", "current_gap",
                                       "סיווג ריבאונד", "לימיט כניסה", "יעד מכירה", "סטופ-לוס"]
                if _show_tase_id_col2:
                    _base_display_cols.insert(2, "מספר ני\"ע")
                alerts_display = alerts_display[_base_display_cols]
                _ow = round(analysis.REBOUND_OVERREACTION_WEIGHT * 100)
                # הסבר הסיווג בריחוף על ה-"?" - מסודר בקבוצות (מוסיף / מוריד / הסיווג), עם צבעים (7.10.2026)
                def _help_row(text: str, pts: str, color: str) -> str:
                    return (
                        f'<div style="display:flex; align-items:baseline; gap:10px; padding:2px 0;">'
                        f'{_pts_chip(int(pts.replace(chr(0x2212), "-")))}<span>{text}</span></div>'
                    )

                def _help_title(text: str) -> str:
                    return f'<div style="font-weight:800; margin:7px 0 3px; font-size:0.82rem;">{text}</div>'

                _rebound_help_html = (
                    '<span class="sigtip sigtip-help" style="margin-inline-start:4px;">'
                    f'{_HELP_ICON_SVG}'
                    '<span class="sigtip-text" style="width:300px; white-space:normal; top:140%; right:-10px; '
                    'text-align:right; line-height:1.45;">'
                    '<div style="font-weight:800; font-size:0.88rem;">איך נקבע הסיווג</div>'
                    '<div style="opacity:0.7;">סכום נקודות (0 עד 6) מסימנים שחזו הצלחה</div>'
                    + _help_title("מוסיף נקודות")
                    + _help_row("ירידה חדה", "+2", POS_COLOR)
                    + _help_row("רחוקה 10% ומעלה מתחת לממוצע של 50 יום", "+1", POS_COLOR)
                    + _help_row("סקטור חזק (תשתיות, טכנולוגיה)", "+2", POS_COLOR)
                    + _help_row("התראה לפני 13:00", "+1", POS_COLOR)
                    + _help_title("מוריד נקודות")
                    + _help_row("מעל הממוצע של 50 יום", "−1", NEG_COLOR)
                    + _help_row("סקטור חלש (נדל״ן, אנרגיה, חומרי גלם)", "−2", NEG_COLOR)
                    + _help_title("הסיווג")
                    + f'<div><b style="color:{SIGNAL_COLORS["buy"]};">A · לקנות</b> — {strategy_mod.buy_min_score()} נקודות ומעלה</div>'
                    + f'<div><b style="color:{SIGNAL_COLORS["wait"]};">B · לחכות</b> — {strategy_mod.wait_min_score()} עד {strategy_mod.buy_min_score() - 1} נקודות</div>'
                    + f'<div><b style="color:{SIGNAL_COLORS["avoid"]};">C · לא לקנות</b> — 0 עד {strategy_mod.wait_min_score() - 1} נקודות</div>'
                    '</span></span>'
                )
                _rebound_header_label = f'סיווג ריבאונד {_rebound_help_html}'
                if _is_fallback_day:
                    _fallback_date_text = dt.date.fromisoformat(_last_scan_date).strftime("%d.%m")
                    _today_header_text = f"{len(todays_alerts)} התראות מיום המסחר האחרון ({_fallback_date_text})"
                else:
                    _today_header_text = "התראות היום"
                _no_new_alerts_yet = todays_alerts.empty and not _is_fallback_day
                _market_open_now = is_market_open("TA35") or is_market_open("NASDAQ100")
                st.session_state.setdefault("open_alert_id", None)
                with _slot_table:
                    _render_alerts_v3(todays_alerts, _is_fallback_day, _last_scan_date if _is_fallback_day else None, after_header=_render_manual_price_alert)

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
                # prev_close_gap - אותה משפחת באג בדיוק, מהכיוון ההפוך: last_close_date
                # יכול להיות "היום" ממש (לא is_stale בכלל) בזמן שה*בסיס* להשוואה
                # (prev_close, "אתמול") הוא בעצם ישן בהרבה כי yfinance דילגה על יום/ימי
                # מסחר - אז "שינוי יומי" הוא בעצם שינוי של כמה ימים, לא קרבה אמיתית
                # לסף היומי (נמצא בפועל 22.9.2026: כל TA35 עם prev_close מ-17/09,
                # 5 ימים אחורה, בזמן שה-last_close היה תקין לגמרי - ר' scanner.py
                # _scan_one_index, אותו תיקון בדיוק חובר גם לסורק עצמו).
                near_miss_frames.append(idx_df[
                    (idx_df["שינוי יומי (%)"] < -scanning_threshold * 0.8) &
                    (idx_df["שינוי יומי (%)"] >= -scanning_threshold) &
                    (~idx_df["is_stale"]) &
                    (~idx_df["prev_close_gap"].fillna(False)) &
                    (idx_df["last_close_date"] == israel_today())
                ])
            near_miss_df = pd.concat(near_miss_frames).sort_values("שינוי יומי (%)") if near_miss_frames else pd.DataFrame()
            # מניה שנמצאת בכמה מדדים סרוקים (למשל קמטק גם בת"א 35 וגם בת"א 125) מופיעה פעם אחת בלבד (13.10.2026)
            if not near_miss_df.empty and "טיקר" in near_miss_df.columns:
                near_miss_df = near_miss_df.drop_duplicates(subset="טיקר", keep="first")

            if not near_miss_df.empty:
                with _slot_nearmiss:
                    st.markdown(
                        f'<div class="v3h"><section class="block">{ui_v3.head("קרוב לסף התראה")}'
                        f'{ui_v3.stocks_table(_v3_stock_rows(near_miss_df), cfg.get("multi_day_window_days", 3), show_price=False)}</section></div>',
                        unsafe_allow_html=True,
                    )

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


@st.cache_data(ttl=300)
def get_post_alert_results(alerts_df: pd.DataFrame, target_pct: float, hold_days: int) -> pd.DataFrame:
    """תוצאות מרגע ההתראה בלבד (ר' src/post_alert.py): מחבר את ההתראות לטבלת התוצאות
    ומחשב מחדש outcome לפי היעד והאופק שנבחרו - רטרואקטיבית על כל ההיסטוריה."""
    if "id" in alerts_df.columns:
        alerts_df = alerts_df[~alerts_df["id"].isin(store.excluded_alert_ids())]
    conn = store.get_conn(db_path(cfg))
    try:
        outcomes = post_alert.load_outcomes(conn)
    finally:
        conn.close()
    merged = alerts_df.merge(outcomes, left_on="id", right_on="alert_id", how="left")
    return post_alert.evaluate(merged, target_pct, hold_days)


@st.cache_data(ttl=3600)
def get_backtest_results(alerts_df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    if "id" in alerts_df.columns:
        alerts_df = alerts_df[~alerts_df["id"].isin(store.excluded_alert_ids())]
    # strict_window: אופק החזקה קבוע (7.10.2026, "החזקה של כמה שעות עד שלושה ימים") - בלי הרחבה
    # אוטומטית של החלון לפי גודל היעד. תוצאה כזו *לא* נשמרת ל-DB (שם ה-outcome הקנוני הוא
    # של חלון 10 הימים, ר' backtest.refresh_pending_outcomes) - אחרת הטאב היה דורס אותו.
    return backtest.run_backtest(alerts_df, window_days, strict_window=True)


_PERF_HOLD = {"יום אחד": 1, "יומיים": 2, "3 ימים": 3, "4-8 ימים": 8, "9-13 ימים": 13, "14 ימים ומעלה": 30}
_PERF_SIG_EMOJI = {"לקנות": "🟢", "לחכות": "🟡", "לא לקנות": "🔴"}


def _perf_bucket(score) -> str:
    if pd.isna(score):
        return "לא ידוע"
    score = int(score)
    return "80-100" if score >= 80 else "60-79" if score >= 60 else "40-59" if score >= 40 else "20-39" if score >= 20 else "0-19"


def _render_perf_v3() -> None:
    """טאב 'ביצועי אסטרטגיה' בעיצוב v3 (המוקאפ שאושר): פילטרים מכווצים לשורה, שישה סיכומים, לפי סיגנל/סיבה/ציון, פירוט מתקפל."""
    # בזמן חישוב ארוך (בדיקת ההתראות מול מחירים) Streamlit משאיר על המסך שאריות דהויות מהטאב הקודם - מסתירים אותן ומציגים הודעת טעינה
    # רק בכניסה הראשונה לטאב (אחרי זה כל לחיצה על מסנן מריצה מחדש והסתרה תגרום לעמוד "לקפוץ")
    # ה-style נכנס לאותו st.markdown של הכותרת (אלמנט נפרד מוסיף רווח ומזיז את הכותרת למטה לעומת שאר הטאבים)
    if not st.session_state.get("_perf_entered"):
        _stale_css = '<style>[data-testid="stMain"] [data-stale="true"] { display: none !important; }</style>'
    else:
        # שינוי מסנן מריץ מחדש את הדף (~שנייה): בלי הדהייה של Streamlit לאלמנטים הישנים - היא נראית כמו "קפיצה"/הבהוב
        _stale_css = '<style>[data-testid="stMain"] [data-stale="true"] { opacity: 1 !important; transition: none !important; }</style>'
    st.markdown(f'{_stale_css}<div class="v3h">{ui_v3.movers_head("ביצועי אסטרטגיה", "", None)}</div>', unsafe_allow_html=True)
    # on_click (ולא st.rerun באמצע הסקריפט): rerun לפני שהמסננים נרשמו מאפס את הבחירות שלהם
    def _toggle_perf_filters() -> None:
        st.session_state["perf_filters_open"] = not st.session_state.get("perf_filters_open", False)

    st.button("הרצת בדיקה מחדש", key="perf_refresh_icon", on_click=get_backtest_results.clear)
    st.button(" ", key="perf_filter_icon", on_click=_toggle_perf_filters)  # אייקון סינון - פותח את אותו לוח כמו שורת הסיכום

    all_df = load_alerts(db_path(cfg))
    if all_df.empty:
        st.info("אין עדיין התראות להערכה. הרץ סריקה כדי להתחיל לצבור נתונים.")
        return

    _target_default = f"{int(round(strategy_mod.target_pct()))}%"
    _hold_default = next((k for k, v in _PERF_HOLD.items() if v == strategy_mod.HOLD_MAX_DAYS), "3 ימים")
    _ss = st.session_state
    # הבחירה האחרונה נשמרת בקובץ: חוזרת גם אחרי החלפת טאב/רענון/הפעלה מחדש (Streamlit מוחק מצב של ווידג'ט שלא הוצג)
    _prefs = _load_ui_prefs()
    for _k in _PERF_PREF_KEYS:
        if _ss.get(_k) is None and _prefs.get(_k) is not None:
            _ss[_k] = _prefs[_k]
    summary_parts = [
        _ss.get("perf_scope", "כל ההתראות"), _ss.get("perf_market", 'בורסת ת"א'), f"סיגנל: {_ss.get('perf_signal', 'לקנות')}",
        f"יעד {_ss.get('perf_target', _target_default)}", f"החזקה: {_ss.get('perf_hold', _hold_default)}",
    ]
    _open = bool(_ss.get("perf_filters_open", False))
    # שורת הסיכום היא טקסט בלבד - הסינון נפתח רק מאיקון המשפך שבכותרת
    st.markdown(f'<div class="v3h">{ui_v3.perf_filter_summary(summary_parts, _open)}</div>', unsafe_allow_html=True)
    # הווידג'טים תמיד מוצגים (אחרת Streamlit מאפס את הבחירה); כשהפילטרים סגורים הם מוסתרים ב-CSS
    st.markdown(
        '<style>div[class*="st-key-perf_filters_body"] { display:' + ("block" if _open else "none") + '; }</style>', unsafe_allow_html=True,
    )
    with st.container(key="perf_filters_body"):
        def _row(label: str, options: list, key: str, default):
            c1, c2 = st.columns([1, 5])
            c1.markdown(f'<div class="v3pl">{label}</div>', unsafe_allow_html=True)
            # לחיצה על אפשרות שכבר נבחרה מבטלת אותה - מחזירים את הבחירה האחרונה במקום להפיל לברירת מחדל
            def _keep_last(_key=key, _default=default) -> None:
                if st.session_state.get(_key) is None:
                    st.session_state[_key] = _load_ui_prefs().get(_key, _default)

            _initial = None if _ss.get(key) is not None else default
            with c2:
                return st.segmented_control(
                    label, options, default=_initial, selection_mode="single", key=key, label_visibility="collapsed", on_change=_keep_last,
                ) or _ss.get(key) or default

        scope = _row("היקף הבדיקה", ["כל ההתראות", "התראות שמומשו"], "perf_scope", "כל ההתראות")
        market = _row("שוק", ['בורסת ת"א', "וול סטריט", "כל השווקים"], "perf_market", 'בורסת ת"א')
        sig_choice = _row("סיגנל", ["לקנות", "לחכות", "לא לקנות", "הכל"], "perf_signal", "לקנות")
        target_label = _row("יעד רווח", [f"{t}%" for t in range(2, 11)], "perf_target", _target_default)
        hold_label = _row("זמן החזקה מקסימלי", list(_PERF_HOLD), "perf_hold", _hold_default)
    _save_ui_prefs({"perf_scope": scope, "perf_market": market, "perf_signal": sig_choice, "perf_target": target_label, "perf_hold": hold_label})
    target_pct = int(target_label.rstrip("%"))
    window_days = _PERF_HOLD[hold_label]

    strategy_df = all_df[all_df.get("is_manual_trade") != 1] if "is_manual_trade" in all_df.columns else all_df
    il_indices = ("TA35", "TA125")
    if market == 'בורסת ת"א':
        strategy_df = strategy_df[strategy_df["index_name"].isin(il_indices)]
    elif market == "וול סטריט":
        strategy_df = strategy_df[~strategy_df["index_name"].isin(il_indices)]

    if scope == "התראות שמומשו":
        # "מומשו" = התראות שהפכו לעסקה אמיתית (פתוחה או סגורה, בלי ידניות). נמדדות באותו מנוע כמו כל התראה -
        # כך היעד, האופק והסיגנל שנבחרו משפיעים גם כאן (קודם הן נמדדו מול היעד/סטופ המקוריים ושלושת המסננים נעלמו).
        _cc = store.get_conn(db_path(cfg))
        try:
            _real_ids = {int(r[0]) for r in _cc.execute(f"SELECT alert_id FROM {store.user_table('closed_trades')} WHERE alert_id IS NOT NULL AND COALESCE(is_manual_trade, 0) != 1")}
        finally:
            _cc.close()
        _bought = strategy_df["bought"] == 1 if "bought" in strategy_df.columns else pd.Series(False, index=strategy_df.index)
        strategy_df = strategy_df[_bought | strategy_df["id"].isin(_real_ids)]
    bt = get_post_alert_results(strategy_df, float(target_pct), int(window_days))
    if not bt.empty:
        bt["סיגנל"] = bt.apply(lambda r: strategy_mod.SIGNAL_EMOJI[_alert_signal(r)[0]], axis=1)
    bt_all_signals = bt
    if sig_choice in _PERF_SIG_EMOJI and not bt.empty:
        bt = bt[bt["סיגנל"] == _PERF_SIG_EMOJI[sig_choice]]

    st.session_state["_perf_entered"] = True
    summary = backtest.overall_summary(bt)
    wr = summary["win_rate_pct"]
    blocks = [ui_v3.perf_kpi(
        summary["total_alerts"], summary["hit_target"], summary["hit_stop"], summary["neither"], summary["pending"],
        f"{wr:.0f}%" if wr is not None else "—", None if wr is None else wr >= 50,
    )]

    hsub = (
        f'<span class="hsub"><span class="fp">יעד {ui_v3.num(str(target_pct) + "%")}</span>'
        f'<span class="fp">אופק {ui_v3.num(window_days)} {"יום" if window_days == 1 else "ימים"}</span><span class="fp">נמדד מרגע ההתראה</span></span>'
    )
    if bt_all_signals is not None and not bt_all_signals.empty:
        decided = bt_all_signals[bt_all_signals["outcome"].isin([backtest.HIT_TARGET, backtest.HIT_STOP, backtest.NEITHER])]
        rows = []
        if not decided.empty:
            g = decided.groupby("סיגנל").agg(
                total=("outcome", "size"), hits=("outcome", lambda x: (x == backtest.HIT_TARGET).sum()),
                exp=("ret", "mean") if "ret" in decided.columns else ("outcome", lambda x: float("nan")),
            ).reset_index()
            order = {"🟢": 0, "🟡": 1, "🔴": 2}
            g = g.sort_values("סיגנל", key=lambda col: col.map(order)).reset_index(drop=True)
            word = {"🟢": ("לקנות", "up"), "🟡": ("לחכות", "warn"), "🔴": ("לא לקנות", "down")}
            for _, r in g.iterrows():
                w, c = word.get(r["סיגנל"], (r["סיגנל"], ""))
                rate = r["hits"] / r["total"] * 100
                e = r["exp"]
                e_cell = (f'<td class="r {ui_v3.cls_for(e)}">{ui_v3.num(ui_v3.signed(e, 2))}</td>' if pd.notna(e) else "<td>—</td>")
                rows.append([f'<td class="main"><span class="{c}">{w}</span></td>', f'<td>{ui_v3.num(int(r["total"]))}</td>',
                             f'<td>{ui_v3.num(int(r["hits"]))}</td>', ui_v3.rate_cell(rate), e_cell])
        body = (ui_v3.plain_table(["סיגנל", 'סה"כ', "הגיעו ליעד", "שיעור הצלחה (%)", "תוחלת לעסקה (%)"], rows) if rows
                else '<div class="nw"><small>אין עדיין מספיק התראות מוכרעות.</small></div>')
        blocks.append(ui_v3.titled_section("שיעור הצלחה לפי סיגנל", hsub, body))

    # סיבה / ציון
    bt_display = bt.copy()
    if not bt_display.empty:
        bt_display["סיבה"] = bt_display["reasons_json"].apply(
            lambda v: (lambda rs: _ALERT_REASON_LABELS.get(rs[0], rs[0]) if rs else "לא ידוע")(json.loads(v or "[]"))
        )
        bt_display["ציון תגובת-יתר"] = bt_display["overreaction_score"].apply(_perf_bucket)
        by_reason = backtest.summarize_by(bt_display, "סיבה")
        by_score = backtest.summarize_by(bt_display, "ציון תגובת-יתר")
    else:
        by_reason = by_score = pd.DataFrame()

    def _rate_rows(frame: pd.DataFrame, col: str, sort_rate: bool) -> list[list[str]]:
        if frame is None or frame.empty:
            return []
        f = frame.copy()
        if sort_rate:
            f = f.sort_values("שיעור הצלחה (%)", ascending=False)
        else:
            f["_k"] = f[col].map(lambda v: (1 if v == "לא ידוע" else 0, -int(str(v).split("-")[0]) if str(v)[0].isdigit() else 0))
            f = f.sort_values("_k")
        return [
            [f'<td class="main">{ui_v3.esc(r[col])}</td>', f'<td>{ui_v3.num(int(r["סה\"כ"]))}</td>', f'<td>{ui_v3.num(int(r["הגיעו ליעד"]))}</td>',
             ui_v3.rate_cell(float(r["שיעור הצלחה (%)"]))]
            for _, r in f.iterrows()
        ]

    left_rows, right_rows = _rate_rows(by_reason, "סיבה", True), _rate_rows(by_score, "ציון תגובת-יתר", False)
    _none = '<div class="nw"><small>אין עדיין מספיק התראות מוכרעות.</small></div>'
    two = (
        '<section class="sec"><div class="two"><div>'
        f'<div class="sech">שיעור הצלחה לפי סיבת הירידה</div>{ui_v3.plain_table(["סיבה", "סה\"כ", "הגיעו ליעד", "שיעור הצלחה (%)"], left_rows) if left_rows else _none}'
        '</div><div>'
        f'<div class="sech">שיעור הצלחה לפי ציון תגובת-יתר</div>{ui_v3.plain_table(["ציון תגובת-יתר", "סה\"כ", "הגיעו ליעד", "שיעור הצלחה (%)"], right_rows) if right_rows else _none}'
        '</div></div></section>'
    )
    blocks.append(two)

    more = []
    # ברמת יום (טווחי סמך, נטו אחרי עמלות, והטובות ביותר ביום) - רק כשיש מספיק התראות מוכרעות
    if bt_all_signals is not None and not bt_all_signals.empty and "ret" in bt_all_signals.columns:
        _ds = bt_all_signals[bt_all_signals["outcome"].isin([backtest.HIT_TARGET, backtest.HIT_STOP, backtest.NEITHER])].copy()
        _ds = _ds[_ds["ret"].notna()]
        if len(_ds) >= 20:
            _ds["y"] = (_ds["outcome"] == backtest.HIT_TARGET).astype(int)
            _ds["score"] = _ds.apply(
                lambda r: strategy_mod.signal_score(
                    r.get("index_name"), r["pct_change"], r.get("intraday_recovery_pct"), r.get("dist_from_ma50_pct"), r.get("sector"),
                    int(str(r.get("scan_ts"))[11:13]) if str(r.get("scan_ts"))[11:13].isdigit() else None,
                )[0], axis=1,
            )
            _position = float(cfg.get("position_size", {}).get("ILS", 5000.0))
            _fees_cfg = cfg["fees"] if bool(_ds["index_name"].isin(il_indices).all()) else None
            _tbl = strategy_stats.bucket_summary(_ds, _fees_cfg, position=_position, B=600)
            N = ui_v3.num

            def _cih(v):
                return f"{ui_v3.snum(v[0], 2, '%')} עד {ui_v3.snum(v[1], 2, '%')}"

            def _ci(v, pct=True):
                return f"{v[0]:.1f}% עד {v[1]:.1f}%" if pct else f"{v[0]:+.2f}% עד {v[1]:+.2f}%"

            heads = ["קבוצה", "התראות / ימים", "הצלחה (טווח 95%)", "תשואה ברוטו (טווח)"] + (["תשואה נטו (טווח)"] if _fees_cfg else [])
            trs = []
            for _, r in _tbl.iterrows():
                cells = [
                    f'<td class="main">{ui_v3.esc(r["קבוצה"])}</td>', f'<td>{N(int(r["התראות"]))} / {N(int(r["ימים"]))}</td>',
                    f'<td>{N(f"{r["הצלחה %"]:.0f}%")} ({N(_ci(r["הצלחה CI"]))})</td>',
                    f'<td>{ui_v3.snum(r["ברוטו %"], 2, "%")} ({_cih(r["ברוטו CI"])})</td>',
                ]
                if _fees_cfg:
                    cells.append(f'<td>{ui_v3.snum(r["נטו %"], 2, "%")} ({_cih(r["נטו CI"])})</td>')
                trs.append(cells)
            _tk = strategy_stats.topk_table(_ds)
            tk_rows = [
                [f'<td class="main">{"הטובה ביותר" if r["K"] == 1 else f"{N(int(r["K"]))} הטובות ביותר"}</td>',
                 f'<td>{N(f"{r["הצלחה %"]:.0f}%")} / {ui_v3.snum(r["ברוטו %"], 2, "%")}</td>',
                 (f'<td>{N(f"{r["רק 4+: הצלחה %"]:.0f}%")} / {ui_v3.snum(r["רק 4+: ברוטו %"], 2, "%")}</td>' if r["רק 4+: התראות"] else "<td>—</td>")]
                for _, r in _tk.iterrows()
            ]
            body = ui_v3.plain_table(heads, trs) + '<div style="height:28px"></div>' + ui_v3.plain_table(["קונים ביום", "בלי סינון", "רק עם ניקוד 4+"], tk_rows)
            more.append(ui_v3.collapsible("ניתוח לפי ימים", ["טווחי סמך", "נטו אחרי עמלות", "קנייה של הטובות ביותר ביום"], body))

    # כל ההתראות עם תוצאה
    if not bt_display.empty:
        t = bt_display[["scan_ts", "ticker", "pct_change", "target_base", "stop_loss", "outcome"]].head(300)
        trs = []
        for _, r in t.iterrows():
            try:
                when = dt.datetime.fromisoformat(str(r["scan_ts"])).strftime("%d.%m %H:%M")
            except Exception:
                when = str(r["scan_ts"])[:16]
            lab = backtest.OUTCOME_LABELS_HE.get(r["outcome"], str(r["outcome"]))
            oc = "up" if r["outcome"] == backtest.HIT_TARGET else ("down" if r["outcome"] == backtest.HIT_STOP else "dim")
            trs.append([
                f'<td class="main">{ui_v3.esc(str(r["ticker"]).replace(".TA", ""))}</td>', f'<td>{ui_v3.num(when)}</td>',
                (f'<td class="{ui_v3.cls_for(r["pct_change"])}">{ui_v3.num(ui_v3.signed(r["pct_change"], 1, "%"))}</td>' if pd.notna(r["pct_change"]) else "<td>—</td>"),
                f'<td>{ui_v3.num(_level_text(r["target_base"], str(r["ticker"]).endswith(".TA")) if pd.notna(r["target_base"]) else "—")}</td>',
                f'<td>{ui_v3.num(_level_text(r["stop_loss"], str(r["ticker"]).endswith(".TA")) if pd.notna(r["stop_loss"]) else "—")}</td>',
                f'<td class="{oc}">{ui_v3.esc(lab)}</td>',
            ])
        more.append(ui_v3.collapsible(
            "כל ההתראות עם תוצאה", [f"{ui_v3.num(len(bt_display))} התראות", "יעד, סטופ ותוצאה לכל אחת"],
            ui_v3.plain_table(["טיקר", "זמן סריקה", "שינוי (%)", "יעד", "סטופ", "תוצאה"], trs),
        ))
    if more:
        blocks.append(f'<div class="stack">{"".join(more)}</div>')
    st.markdown(f'<div class="v3h">{"".join(blocks)}</div>', unsafe_allow_html=True)






_tab_slot_backtest = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
if st.session_state.active_tab != "backtest":
    st.session_state["_perf_entered"] = False  # בכניסה הבאה לטאב: מסתירים שאריות ישנות של הטאב הקודם
with _tab_slot_backtest.container():
    if st.session_state.active_tab == "backtest":
        _render_perf_v3()

def _next_gain_alert_pct(gain_pct: float | None) -> float:
    gain_start_pct = cfg.get("holdings_gain_alert_start_pct", 2.0)
    gain_step_pct = cfg.get("holdings_gain_alert_step_pct", 1.0) or 1.0
    if gain_pct is None or gain_pct < gain_start_pct:
        return gain_start_pct
    level = int((gain_pct - gain_start_pct) // gain_step_pct)
    return gain_start_pct + (level + 1) * gain_step_pct


def _build_holding_rows(holdings: pd.DataFrame) -> list[dict]:
    """שורות האחזקות (מחיר נוכחי, רווח/הפסד, שינוי יומי, סטופ וכו') - משותף לטאב אחזקות ולעמוד הבית (v3)."""
    _daily_data_map = {}
    _daily_df2 = market_data.fetch_universe_daily_changes(holdings["ticker"].tolist())
    for _, _dr in _daily_df2.iterrows():
        _daily_data_map[_dr["ticker"]] = _dr
    _price_map3 = get_current_prices_batch(tuple(sorted(set(holdings["ticker"]))))
    _own_close_conn3 = store.get_conn(db_path(cfg))
    _today_iso3 = israel_today().isoformat()

    rows = []
    for _, r in holdings.iterrows():
        days_held = 1
        bought_date = None
        if r.get("bought_at"):
            try:
                bought_dt = dt.datetime.fromisoformat(r["bought_at"])
                bought_date = bought_dt.date()
                days_held = max((dt.date.today() - bought_date).days, 0) + 1
            except Exception:
                pass

        # הגרף הזעיר בכרטיס אחזקה מציג את המגמה *מאז הקנייה* (לא חלון
        # קבוע של 15 יום כמו בשאר השימושים ב-get_sparkline_prices) -
        # אחרת אחזקה שנקנתה לפני 3 ימים מציגה קו של 15 יום שרובו
        # לפני שהיא בכלל הייתה בתיק, מבלבל (9.9.2026, "למה 15 ימים
        # ולא מיום הקנייה?"). מינימום 2 (נקודת קנייה + היום) לקו תקין.
        prices = get_sparkline_prices(r["ticker"], days=max(days_held, 2))
        current = _price_map3.get(r["ticker"])
        if current is None:
            current = prices[-1] if prices else None
        entry = r["actual_entry_price"]
        qty = r["actual_qty"]
        pnl = (current - entry) * qty if (current is not None and entry) else None
        pnl_pct = (current / entry - 1) * 100 if (current is not None and entry) else None
        ccy = constituents.INDEX_CURRENCY.get(r.get("index_name"), "ILS")
        country_code = constituents.INDEX_COUNTRY_CODE.get(r.get("index_name"), "IL")

        # "שינוי יומי" בכרטיס אחזקה בודדת - אותה בעיה שכבר תוקנה בכרטיס
        # המצטבר "💼 התיק שלי": אם נקנתה היום (אחרי prev_close), ההשוואה
        # מול prev_close (הסגירה של אתמול) לא רלוונטית למי שהחזיק אותה רק
        # מהקנייה - הבסיס הנכון הוא שער הכניסה, לא סגירת אתמול.
        daily_pct = None
        daily_pct_date = None
        daily_change_amt = None
        daily_baseline_value = None
        daily_pct_baseline_date = None
        daily_pct_gap = False
        _dr = _daily_data_map.get(r["ticker"])
        if current is not None and _dr is not None:
            _prev_close, _prev_close_date = _dr.get("prev_close"), _dr.get("prev_close_date")
            _baseline = _prev_close
            # קנייה באמצע יום המסחר של prev_close (לפני הסגירה) - הסגירה באה
            # אחרי הקנייה, אז היא הבסיס הנכון ולא שער הכניסה (כמו בסיכום התיק)
            _same_day_before_close3 = bool(
                bought_date and _prev_close_date and bought_date == _prev_close_date
                and not bought_after_close(country_code, bought_dt)
            )
            _using_entry_baseline = bool(
                bought_date and _prev_close_date and bought_date >= _prev_close_date and entry
                and not _same_day_before_close3
            )
            if _using_entry_baseline:
                _baseline = entry
            elif _dr.get("prev_close_gap") and _prev_close_date:
                # אותו עיקרון בדיוק כמו _compute_portfolio_summaries -
                # סגירה עצמאית שנרשמה בעצמנו (ר' store.record_own_close)
                # עדיפה על prev_close המפגר של yfinance, אם יש לנו
                # אחת טרייה יותר. try (23.9.2026, ר' הערה מקבילה
                # למעלה) - תוסף לא-קריטי אסור שיפיל את כל העמוד.
                try:
                    _own = store.get_last_own_close_before(_own_close_conn3, r["ticker"], _today_iso3)
                except Exception:
                    _own = None
                if _own and str(_own[0]) > str(_prev_close_date):
                    _baseline = _own[1]
                    _prev_close_date = dt.date.fromisoformat(str(_own[0]))
            if _baseline:
                daily_pct = (current - _baseline) / _baseline * 100
                # 24.9.2026 ("הנתון לא נכון", קווליטאו): כשהבסיס הוא מחיר
                # הכניסה (נקנתה אחרי prev_close), השינוי הוא מחיר חי מול
                # כניסה - לא קשור לשום "תאריך סגירה". תיוג last_close_date
                # כאן היה מטעה (מראה "(22/09)" ליד % שמחושב ממש עכשיו).
                daily_pct_date = _dr.get("last_close_date") if not _using_entry_baseline else None
                if qty:
                    daily_change_amt = (current - _baseline) * qty
                    daily_baseline_value = _baseline * qty
                # דגל "פער" רק כשהבסיס בפועל הוא prev_close (לא מחיר
                # כניסה) - ר' market_data._prev_close_gap: יום מסחר
                # אמיתי חסר בהיסטוריה (לא רק סופ"ש/חג), אז "שינוי
                # יומי" בעצם פורש כמה ימי מסחר (15.9.2026, "הנתון
                # שגוי" - NICE.TA הראתה שינוי יומי מנופח כי prev_close
                # היה מ-10/09 בזמן ש-14/09 היה יום מסחר אמיתי שחסר
                # ב-yfinance).
                if not _using_entry_baseline:
                    daily_pct_baseline_date = _prev_close_date
                    daily_pct_gap = bool(_dr.get("prev_close_gap"))

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
            "trading_days_held": _trading_days_held(bought_date, country_code),
            "entry_signal": strategy_mod.SIGNAL_EMOJI[_alert_signal(r)[0]],
            "alert_pct": r.get("pct_change"), "signal_score": _alert_score(r),
            "entry_signal_text": strategy_mod.SIGNAL_LABEL[_alert_signal(r)[0]],
            "entry_signal_color": SIGNAL_COLORS[_alert_signal(r)[0]],
            "net_pnl": net_pnl, "net_pct": net_pct,
            "next_alert_pct": _next_gain_alert_pct(pnl_pct),
            "forecast_entry_limit": r.get("entry_limit"), "forecast_target": r.get("target_base"),
            "forecast_stop": r.get("stop_loss"), "forecast_score": r.get("overreaction_score"),
            "forecast_verdict": r.get("overreaction_verdict"),
            "holding_stop_price": get_or_backfill_stop_price(r, entry) if entry else None,
            "is_manual_trade": bool(r.get("is_manual_trade")) if pd.notna(r.get("is_manual_trade")) else False,
            "daily_pct": daily_pct,
            "daily_pct_date": daily_pct_date,
            "daily_pct_baseline_date": daily_pct_baseline_date,
            "daily_pct_gap": daily_pct_gap,
            "daily_change_amt": daily_change_amt,
            "daily_baseline_value": daily_baseline_value,
            "sector": r.get("sector") or "לא ידוע",
        })

    # ממוין לפי תשואה נטו (%) מאז הכניסה - הכי מרוויחה קודם. יותר
    # רלוונטי מ"שינוי יומי" כי זה בדיוק מה שקובע קרבה ליעד/סטופ,
    # לא רק תנודה חד-יומית שיכולה להטעות (2.9.2026).
    rows.sort(key=lambda r: r["net_pct"] if r["net_pct"] is not None else float("-inf"), reverse=True)
    _total_current_value = sum(r["current_value"] for r in rows if r["current_value"]) or 1.0
    for _r in rows:
        _r["portfolio_pct"] = (_r["current_value"] or 0) / _total_current_value * 100
    return rows


def _v3_sell_flow(row: dict, part: str = "icon") -> None:
    """מכירה / סגירת פוזיציה (v3). part="icon": אייקון מינוס בפינת הכרטיס שמחליף את מצב הטופס; part="form": שורת טופס מתחת
    לכרטיס (שער, תאריך, אישור, ביטול). אותה לוגיקת שמירה ואותם מפתחות כמו בכרטיס הישן."""
    sell_key = f"confirm_sell_{row['id']}"
    if part == "icon":
        def _toggle() -> None:
            st.session_state[sell_key] = not st.session_state.get(sell_key, False)

        st.button(" ", key=f"sell_holding_{row['id']}", on_click=_toggle)  # אייקון מינוס עגול (ר' CSS של sell_holding_)
        return
    if not st.session_state.get(sell_key):
        return
    is_il = market_data._is_israeli_ticker(row["ticker"])
    default_exit = (row["current"] if row["current"] is not None else row["entry"]) or 0.0
    default_exit = default_exit * (100.0 if is_il else 1.0)
    with st.container(key=f"sell_form_{row['id']}", horizontal=True, vertical_alignment="bottom"):
        exit_price_raw = st.number_input(
            "שער מכירה", min_value=0.0, value=float(default_exit), step=1.0 if is_il else 0.01,
            format="%.0f" if is_il else "%.2f", key=f"exit_price_{row['id']}",
        )
        exit_date = st.date_input("תאריך מכירה", value=dt.date.today(), key=f"exit_date_{row['id']}", format="DD/MM/YYYY")
        do_confirm = st.button("אישור מכירה", key=f"confirm_sell_btn_{row['id']}", type="primary")
        do_cancel = st.button("ביטול", key=f"cancel_sell_btn_{row['id']}", type="tertiary")
    exit_price = (exit_price_raw / 100.0) if is_il else exit_price_raw
    if do_confirm:
        exit_at = dt.datetime.combine(exit_date, dt.datetime.now().time()).isoformat(timespec="seconds")
        entry_at = row["bought_at"]
        try:
            entry_date_only = dt.datetime.fromisoformat(entry_at).date() if entry_at else exit_date
        except Exception:
            entry_date_only = exit_date
        holding_days = max((exit_date - entry_date_only).days, 0) + 1
        net = fees.compute_net_result(
            country_code=row["country_code"], buy_price=row["entry"], sell_price=exit_price,
            position_size_ccy=row["entry"] * row["qty"], holding_days=holding_days, fees_cfg=cfg["fees"],
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
    if do_cancel:
        st.session_state.pop(sell_key, None)
        st.rerun(scope="fragment")


def _sector_items(rows: list[dict]) -> list[dict]:
    """התפלגות סקטורים לפי שווי נוכחי (% מהתיק), ממוין יורד - משותף לטאב האחזקות ולעמוד הבית."""
    sec: dict = {}
    for r in rows:
        if r.get("current_value"):
            lbl = _SECTOR_LABELS_HE.get(r.get("sector"), r.get("sector") or "לא ידוע")
            d = sec.setdefault(lbl, {"label": lbl, "pct": 0.0, "names": []})
            d["pct"] += r.get("portfolio_pct") or 0.0
            d["names"].append(r["name"])
    return sorted(sec.values(), key=lambda d: -d["pct"])


def _render_holdings_v3(rows: list[dict], render_open_expander) -> None:
    """טאב אחזקות בעיצוב v3 (המוקאפ שאושר): התראת סטופ, התיק שלי, פתיחת פוזיציה, רדאר + שורות שנפתחות לפרטים ולמכירה."""
    st.session_state.setdefault("open_holding_id", None)
    by_ccy: dict = {}
    for r in rows:
        a = by_ccy.setdefault(r["ccy"], {"invested": 0.0, "value": 0.0, "pnl": 0.0, "n": 0, "dchg": 0.0, "dbase": 0.0})
        a["invested"] += r["invested"]
        a["value"] += r["current_value"] or 0
        a["pnl"] += r["pnl"] or 0
        a["n"] += 1
        if r.get("daily_change_amt") is not None and r.get("daily_baseline_value"):
            a["dchg"] += r["daily_change_amt"]
            a["dbase"] += r["daily_baseline_value"]
    dom = max(by_ccy, key=lambda c: by_ccy[c]["invested"])
    a = by_ccy[dom]
    sym = "₪" if dom == "ILS" else ("&#36;" if dom == "USD" else dom)
    pnl_pct = (a["pnl"] / a["invested"] * 100) if a["invested"] else 0.0
    _strip_day = ui_v3._daily_col_label([r.get("daily_pct_date") for r in rows])  # "היום" או תאריך כשהמסחר סגור (כמו עמודת השינוי היומי בטבלה)
    strip = ui_v3.portfolio_strip(
        a["value"], a["n"], a["pnl"], pnl_pct,
        a["dchg"] if a["dbase"] else None, (a["dchg"] / a["dbase"] * 100) if a["dbase"] else None, dom,
        day_label=_daily_label_with_date("שינוי יומי", _strip_day, "US" if dom == "USD" else "IL"),
    )
    # התראה אחת: האחזקה שחצתה את הסטופ (או היעד) הכי עמוק
    notice_html = ""
    worst = None
    for r in rows:
        stop, cur = r.get("holding_stop_price"), r["current"]
        if stop and cur is not None:
            gap = stop_distance_pct(cur, stop)
            if gap < 0 and (worst is None or gap < worst[1]):
                worst = (r["name"], gap, False)
    if worst:
        notice_html = ui_v3.notice(worst[0], worst[1], worst[2])
    # "התיק שלי" והתראת הסטופ הוסרו מהטאב - שניהם מופיעים בעמוד הבית; בטאב עצמו האחזקה שחצתה את הסטופ מסומנת באדום בטבלה וברדאר

    st.markdown(f'{_nav_stale_css()}<div class="v3h">{ui_v3.movers_head("אחזקות", "", None)}</div>', unsafe_allow_html=True)
    # on_click (ולא st.rerun באמצע הסקריפט): rerun לפני שהמסנן נרשם מאפס את הבחירה שלו
    def _toggle_holdings_filters() -> None:
        st.session_state["holdings_filters_open"] = not st.session_state.get("holdings_filters_open", False)

    def _toggle_holdings_add() -> None:
        st.session_state["holdings_add_open"] = not st.session_state.get("holdings_add_open", False)

    st.button("רענון", key="holdings_refresh_icon", on_click=load_alerts.clear)
    st.button(" ", key="holdings_filter_icon", on_click=_toggle_holdings_filters)
    st.button(" ", key="holdings_add_icon", on_click=_toggle_holdings_add)
    if st.session_state.get("holdings_add_open", False):
        render_open_expander(True)  # פתיחת פוזיציה: נפתחת מהפלוס שבכותרת

    radar_rows = []
    for r in rows:
        if r["pnl_pct"] is None or not r["entry"]:
            continue
        stop = r.get("holding_stop_price")
        _tp = live_target_price(r["entry"], stop, r.get("forecast_target")) if stop else None
        radar_rows.append({
            "name": r["name"], "pnl_pct": r["pnl_pct"], "daily_pct": r.get("daily_pct"),
            "stop_pct": ((stop / r["entry"] - 1) * 100) if stop else None,
            "tgt_pct": ((_tp / r["entry"] - 1) * 100) if _tp else strategy_mod.target_pct(),
        })
    col_rows = st.container()
    with col_rows:
        # סינון ברווח/בהפסד/הכל (משפיע על הטבלה בלבד; הסה"כ והרדאר נשארים של כל התיק). הלוח מוסתר ב-CSS כשהוא סגור - הווידג'ט תמיד מוצג כדי שהבחירה תישמר
        st.markdown(
            '<style>div[class*="st-key-holdings_filters"] { display:' + ("block" if st.session_state.get("holdings_filters_open", False) else "none") + '; }'
            + '</style>',
            unsafe_allow_html=True,
        )
        _restore_filter_prefs({"holdings_filter_pnl": ("הכל", ["ברווח", "בהפסד", "הכל"])})

        def _keep_pnl_filter() -> None:
            if st.session_state.get("holdings_filter_pnl") is None:
                st.session_state["holdings_filter_pnl"] = "הכל"

        with st.container(key="holdings_filters"):
            _pnl_filter = st.segmented_control(
                "סינון אחזקות", ["ברווח", "בהפסד", "הכל"], selection_mode="single", key="holdings_filter_pnl",
                label_visibility="collapsed", on_change=_keep_pnl_filter,
            ) or "הכל"
        _save_filter_prefs(("holdings_filter_pnl",))
        _day_lbl = ui_v3._daily_col_label([r.get("daily_pct_date") for r in rows if r["pnl_pct"] is not None])
        st.markdown('<div class="v3h hw">' + ui_v3.hold_head(_day_lbl) + "</div>", unsafe_allow_html=True)
        _shown_any = False
        for r in rows:
            if r["pnl_pct"] is None:
                continue
            if (_pnl_filter == "ברווח" and r["pnl_pct"] <= 0) or (_pnl_filter == "בהפסד" and r["pnl_pct"] >= 0):
                continue
            _shown_any = True
            rid = r["id"]
            is_open = st.session_state["open_holding_id"] == rid
            stop = r.get("holding_stop_price")
            stop_pct = ((stop / r["entry"] - 1) * 100) if (stop and r["entry"]) else None
            out = stop_pct is not None and r["pnl_pct"] < stop_pct
            sym_r = "₪" if r["ccy"] == "ILS" else ("&#36;" if r["ccy"] == "USD" else r["ccy"])
            with st.container(key=f"v3_hrow_{rid}"):
                with st.container(key=f"v3_hrowhd_{rid}"):
                    _cur = r.get("current")
                    _stop_gap = stop_distance_pct(_cur, stop) if (stop and _cur is not None) else None
                    _tgt_price = live_target_price(r["entry"], stop, r.get("forecast_target")) if stop else None
                    _tgt_gap = target_distance_pct(_cur, _tgt_price) if (_tgt_price and _cur is not None) else None
                    _tgt_pct = ((_tgt_price / r["entry"] - 1) * 100) if (_tgt_price and r.get("entry")) else None  # היעד עצמו: % מעל הכניסה
                    st.markdown(
                        '<div class="v3h hw">' + ui_v3.hold_row(
                            r["name"], str(r["ticker"]).replace(".TA", ""), sym_r, r.get("current_value"), r.get("portfolio_pct"),
                            r.get("pnl"), r["pnl_pct"], r.get("daily_change_amt"), r.get("daily_pct"), _stop_gap, _tgt_gap,
                            r.get("trading_days_held"), strategy_mod.HOLD_MAX_DAYS,
                            get_holding_sparkline(r["ticker"], r.get("bought_at")), r.get("entry") or None,
                            (r.get("entry_signal_text") or "", r.get("entry_signal_color") or ""), out, is_open, r.get("net_pnl"),
                            _tgt_gap is not None and _tgt_gap < 0 and not out, _tgt_pct,
                        ) + "</div>", unsafe_allow_html=True,
                    )
                    if st.button(" ", key=f"v3_open_holding_{rid}"):
                        st.session_state["open_holding_id"] = None if is_open else rid
                        st.rerun(scope="fragment")
                if is_open:
                    is_il = market_data._is_israeli_ticker(r["ticker"])
                    px = (lambda v: f"{v * 100:,.0f}") if is_il else (lambda v: f"{v:,.2f}")
                    px0 = lambda v: _level_text(v, is_il)  # סטופ/יעד - עגולים
                    fees_txt = f"{abs((r['pnl'] or 0) - r['net_pnl']):,.0f}" if (r.get("net_pnl") is not None and r.get("pnl") is not None) else ""
                    try:
                        _bd = dt.datetime.fromisoformat(str(r.get("bought_at"))).strftime("%d.%m.%y") if r.get("bought_at") else ""
                    except Exception:
                        _bd = ""
                    tgt_price = live_target_price(r["entry"], stop, r.get("forecast_target")) if stop else None
                    _sec = _SECTOR_LABELS_HE.get(r.get("sector"), r.get("sector") or "") if r.get("sector") and r.get("sector") != "לא ידוע" else ""
                    # סגירת פוזיציה: אייקון מינוס בפינת הכרטיס (זוג לפלוס שבכותרת) - מוצב לפני הכרטיס ומוחזק בגובה אפס
                    # סגירת פוזיציה: אייקון מינוס בפינת הכרטיס (זוג לפלוס שבכותרת) - מוצב לפני הכרטיס ומוחזק בגובה אפס
                    with st.container(key=f"v3_hpos_{rid}"):
                        _v3_sell_flow(r)
                    st.markdown(
                        '<div class="v3h hw"><div class="hdet">' + ui_v3.hold_card(
                            cost=f"{r['invested']:,.0f}", qty=f"{(r.get('qty') or 0):,.0f}", fees=fees_txt, bought=_bd,
                            signal=(r.get("entry_signal_text") or "", r.get("entry_signal_color") or ""),
                            score=(r.get("signal_score"), strategy_mod.MAX_SIGNAL_SCORE), alert_pct=r.get("alert_pct"),
                            range_html=ui_v3.range_text(get_holding_range(r["ticker"], r.get("bought_at"), r.get("entry"))),
                            stop_px=px0(stop) if stop else "", tgt_px=px0(tgt_price) if tgt_price else "", sector=_sec,
                            mobile_strip=ui_v3.hold_mobile_strip(
                                r.get("current_value"), sym_r, r.get("portfolio_pct"), _stop_gap, _tgt_gap,
                                r.get("trading_days_held"), strategy_mod.HOLD_MAX_DAYS, r.get("pnl"), r.get("net_pnl"), _tgt_pct),
                        ) + "</div></div>", unsafe_allow_html=True,
                    )
                    _v3_sell_flow(r, "form")

        if not _shown_any:
            st.markdown('<div class="v3h"><div class="nw"><small>אין אחזקות שמתאימות לסינון.</small></div></div>', unsafe_allow_html=True)
        _dom_day_pct = (a["dchg"] / a["dbase"] * 100) if a["dbase"] else None
        st.markdown('<div class="v3h">' + ui_v3.total_line(
            a["pnl"], pnl_pct, a["dchg"] if a["dbase"] else None, _dom_day_pct, dom,
            day_label=_daily_label_with_date("שינוי יומי", _strip_day, "US" if dom == "USD" else "IL"),
        ) + '</div>', unsafe_allow_html=True)

    # מתחת לטבלה: סולם סטופ ויעד (מיקום כל אחזקה מול הסטופ והיעד שלה; הרדאר נשאר רק בדף הבית)
    _ladder = ui_v3.stop_target_ladder(radar_rows)
    if _ladder:
        st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="v3h">{_ladder}</div>', unsafe_allow_html=True)

    # התפלגות סקטוריאלית (לפי שווי נוכחי, % מהתיק)
    _sec_html = ui_v3.sector_section(_sector_items(rows))
    if _sec_html:
        # ריווח מעל הכותרת כמו בשאר האתר (מחלקת block: 48px)
        st.markdown(f'<div class="v3h"><section class="block">{_sec_html}</section></div>', unsafe_allow_html=True)


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

            def _render_open_position_expander(expanded: bool = False) -> None:
                with st.expander(_nm("➕ פתיחת פוזיציה"), expanded=expanded, key="open_position_expander"):
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
                            _open_position_form(chosen_row, "portfolio_add")

            gain_start_pct = cfg.get("holdings_gain_alert_start_pct", 2.0)
            gain_step_pct = cfg.get("holdings_gain_alert_step_pct", 1.0) or 1.0

            def _next_gain_alert_pct(gain_pct: float | None) -> float:
                if gain_pct is None or gain_pct < gain_start_pct:
                    return gain_start_pct
                level = int((gain_pct - gain_start_pct) // gain_step_pct)
                return gain_start_pct + (level + 1) * gain_step_pct


            holdings = df[df.get("bought") == 1].copy() if (not df.empty and "bought" in df.columns) else pd.DataFrame()
            if holdings.empty:
                _render_open_position_expander()
                st.info("אין עדיין אחזקות. השתמש ב'פתיחת פוזיציה' למעלה.")
            else:
                rows = _build_holding_rows(holdings)
                _render_holdings_v3(rows, _render_open_position_expander)
                return

        _render_holdings_tab()


@st.cache_data(ttl=3600)
def _closed_trade_histories_v3(tickers: tuple[str, ...], start: str, end: str) -> dict:
    return backtest._fetch_batched_histories(list(tickers), dt.date.fromisoformat(start), dt.date.fromisoformat(end))


def _render_journal_v3() -> None:
    """טאב 'יומן עסקאות' בעיצוב v3 (המוקאפ שאושר): חמישה סיכומים ואז טבלת עסקאות סגורות, בסדר ובתוכן של האתר הקודם."""
    hist_conn = store.get_conn(db_path(cfg))
    closed_trades = store.get_closed_trades(hist_conn)
    hist_conn.close()
    st.markdown(f'{_nav_stale_css()}<div class="v3h"><section class="block" style="margin-top:32px">{ui_v3.head("יומן עסקאות")}</section></div>', unsafe_allow_html=True)
    # אייקון סינון בקצה השמאלי של הכותרת (כמו אייקון הרענון בטאבים אחרים); פותח/סוגר את לוח הסינון והמיון מעל הטבלה
    def _toggle_journal_filters() -> None:
        st.session_state["journal_filters_open"] = not st.session_state.get("journal_filters_open", False)

    def _refresh_journal() -> None:  # callback (ולא st.rerun באמצע הסקריפט): rerun לפני שהמסננים נרשמו מאפס את הבחירות
        _closed_trade_histories_v3.clear()
        load_alerts.clear()

    st.button("רענון", key="journal_refresh_icon", on_click=_refresh_journal)
    st.button(" ", key="journal_filter_icon", on_click=_toggle_journal_filters)
    if not closed_trades:
        st.info("עדיין אין עסקאות סגורות. כשתסגור אחזקה בטאב 'אחזקות', היא תופיע כאן.")
        return
    df_h = pd.DataFrame(closed_trades).sort_values("exit_at", ascending=False)

    _start = pd.to_datetime(df_h["entry_at"], errors="coerce").min()
    _hists = (
        _closed_trade_histories_v3(tuple(sorted(df_h["ticker"].unique())), _start.date().isoformat(), dt.date.today().isoformat())
        if pd.notna(_start) else {}
    )

    def _crossed_stop(r) -> bool:
        if r.get("forecast_stop") is None or pd.isna(r.get("forecast_stop")):
            return False
        h = _hists.get(r["ticker"])
        if h is None or h.empty:
            return False
        try:
            e_ts = pd.Timestamp(r["entry_at"]).tz_localize(None)
            x_ts = pd.Timestamp(r["exit_at"]).tz_localize(None)
        except Exception:
            return False
        idx = h.index.tz_localize(None) if h.index.tz is not None else h.index
        window = h.set_axis(idx)[(idx >= e_ts) & (idx <= x_ts)]
        return bool((window["Low"] <= r["forecast_stop"]).any())

    def _outcome(r) -> str:
        if r["exit_price"] >= live_target_price(r["entry_price"], r.get("forecast_stop"), None):
            return "הגיעה ליעד"
        if r.get("forecast_stop") is not None and pd.notna(r.get("forecast_stop")) and r["exit_price"] <= r["forecast_stop"]:
            return "פגע בסטופ"
        if _crossed_stop(r):
            return "חזרה מסטופ"
        if r["exit_price"] > r["entry_price"]:
            return "רווח לפני היעד"
        return "נמכרה ידנית"

    # סיגנל האסטרטגיה בזמן ההתראה שממנה נפתחה העסקה (רטרואקטיבי)
    sig_by_alert: dict[int, str] = {}
    ids = [int(x) for x in df_h["alert_id"].dropna().unique()] if "alert_id" in df_h.columns else []
    if ids:
        _c = store.get_conn(db_path(cfg))
        try:
            _sr = pd.read_sql_query(
                "SELECT id, index_name, pct_change, intraday_recovery_pct, dist_from_ma50_pct, sector, scan_ts "
                f"FROM alerts WHERE id IN ({','.join(map(str, ids))})", _c,
            )
        finally:
            _c.close()
        for _, r in _sr.iterrows():
            sig_by_alert[int(r["id"])] = _alert_signal(r)[0]

    def _trading_days(r) -> int:
        try:
            a, b = pd.Timestamp(r["entry_at"]).date(), pd.Timestamp(r["exit_at"]).date()
        except Exception:
            return int(r["holding_days"])
        country = constituents.INDEX_COUNTRY_CODE.get(r.get("index_name"), "IL")
        n, day = 0, a
        while day <= b:
            if is_trading_day(country, day):
                n += 1
            day += dt.timedelta(days=1)
        return max(n, 1)

    def _px(v, is_il: bool) -> str:
        return "—" if (v is None or pd.isna(v)) else (f"{v * 100:,.0f}" if is_il else f"{v:,.2f}")

    def _d(v) -> str:
        try:
            return dt.datetime.fromisoformat(v).strftime("%d.%m.%y")
        except Exception:
            return "—"

    rows = []
    for _, r in df_h.iterrows():
        is_il = market_data._is_israeli_ticker(r["ticker"])
        invested = (r["entry_price"] or 0) * (r["qty"] or 0)
        sk = sig_by_alert.get(int(r["alert_id"])) if pd.notna(r.get("alert_id")) else None
        rows.append({
            "name": r["company_name"] or r["ticker"], "mono": str(r["ticker"]).replace(".TA", ""),
            "sig_key": sk or "", "sig_label": _SIG_WORD.get(sk, "") if sk else "", "manual": bool(r.get("is_manual_trade")),
            "entry_px": _px(r["entry_price"], is_il), "entry_dt": _d(r["entry_at"]),
            "exit_px": _px(r["exit_price"], is_il), "exit_dt": _d(r["exit_at"]),
            "days": _trading_days(r), "outcome": _outcome(r),
            "pct": (r["gross_pnl"] / invested * 100) if invested else 0.0,
            "gross": float(r["gross_pnl"]), "net": float(r["net_pnl"]), "ccy": r["currency"],
        })

    total = len(df_h)
    wins = int((df_h["gross_pnl"] > 0).sum())  # ברוטו - כמו עמודת "רווח/הפסד" (נטו רק כשמצוין במפורש)
    rate = round(wins / total * 100) if total else 0
    cells = [
        ("סה\"כ עסקאות סגורות", str(total), ""),
        ("עסקאות ברווח", str(wins), "up"),
        ("שיעור הצלחה", f"{rate}%", "up" if rate >= 50 else "down"),
        ("חציון ימי החזקה", f"{float(pd.Series([r['days'] for r in rows]).median()):g}" if rows else "—", ""),
    ]
    if rows:
        _pcts = pd.Series([r["pct"] for r in rows], dtype=float)  # תשואה (ברוטו כברירת מחדל - רק נטו מצוין במפורש) לעסקה
        cells.append(("תשואה ממוצעת", ui_v3.signed(float(_pcts.mean()), 1, "%"), ui_v3.cls_for(float(_pcts.mean()))))
    for ccy, grp in df_h.groupby("currency"):
        g, n = float(grp["gross_pnl"].sum()), float(grp["net_pnl"].sum())
        cells.append(("רווח/הפסד", ui_v3.signed(g), ui_v3.cls_for(g)))
        cells.append(("נטו", ui_v3.signed(n), ui_v3.cls_for(n)))
    # עקומת רווח נקי מצטבר - במטבע הדומיננטי (מספר העסקאות הגדול ביותר), לפי תאריך סגירה
    _dom = df_h["currency"].value_counts().idxmax()
    _eq = df_h[df_h["currency"] == _dom].copy()
    _eq["_x"] = pd.to_datetime(_eq["exit_at"], errors="coerce")
    _eq = _eq.dropna(subset=["_x"]).sort_values("_x")
    _eq["_c"] = _eq["gross_pnl"].astype(float).cumsum()  # ברוטו - כמו "רווח/הפסד כולל" בכרטיסים
    _eq_html = ui_v3.equity_curve(
        [{"ts": r["_x"].timestamp(), "date": r["_x"].strftime("%d.%m"), "full": r["_x"].strftime("%d.%m.%y"), "name": r["company_name"] or r["ticker"],
          "net": float(r["gross_pnl"]), "cum": float(r["_c"])} for _, r in _eq.iterrows()],
        ui_v3.CCY_SYMBOL.get(_dom, _dom),
    )
    st.markdown(f'<div class="v3h">{ui_v3.journal_kpi(cells)}</div>', unsafe_allow_html=True)

    # סינון ומיון של הטבלה. בכל בורר תמיד מסומנת בחירה: "הכל" (שוק/תוצאה) ו"תאריך" (מיון, לפי תאריך יציאה) כברירת מחדל;
    # לחיצה על האפשרות הנבחרת לא מבטלת אותה אלא מחזירה לברירת המחדל
    _jdefaults = {"journal_filter_mkt": "כל השווקים", "journal_filter_res": "הכל", "journal_sort": "תאריך"}

    def _journal_default(_key: str) -> None:
        if st.session_state.get(_key) is None:
            st.session_state[_key] = _jdefaults[_key]

    _restore_filter_prefs({
        "journal_filter_mkt": ("כל השווקים", ['בורסת ת"א', "וול סטריט", "כל השווקים"]),
        "journal_filter_res": ("הכל", ["ברווח", "בהפסד", "הכל"]),
        "journal_sort": ("תאריך", ["תשואה", "רווח/הפסד", "תאריך"]),
    })
    # הווידג'טים תמיד מוצגים (אחרת Streamlit מאפס את הבחירה) - כשהלוח סגור הוא מוסתר ב-CSS
    _jopen = bool(st.session_state.get("journal_filters_open", False))
    st.markdown(
        '<style>div[class*="st-key-journal_filters"] { display:' + ("block" if _jopen else "none") + '; }'
        + '</style>',
        unsafe_allow_html=True,
    )
    with st.container(key="journal_filters"):
        _j1, _j2, _j3 = st.columns([2, 2, 3])
        with _j1:
            _jm = st.segmented_control(
                "שוק", ['בורסת ת"א', "וול סטריט", "כל השווקים"], selection_mode="single", key="journal_filter_mkt",
                label_visibility="collapsed", on_change=_journal_default, args=("journal_filter_mkt",),
            ) or "כל השווקים"
        with _j2:
            _jr = st.segmented_control(
                "תוצאה", ["ברווח", "בהפסד", "הכל"], selection_mode="single", key="journal_filter_res",
                label_visibility="collapsed", on_change=_journal_default, args=("journal_filter_res",),
            ) or "הכל"
        with _j3:
            _js = st.segmented_control(
                "מיון", ["תשואה", "רווח/הפסד", "תאריך"], selection_mode="single", key="journal_sort",
                label_visibility="collapsed", on_change=_journal_default, args=("journal_sort",),
            ) or "תאריך"
    _save_filter_prefs(("journal_filter_mkt", "journal_filter_res", "journal_sort"))
    _view = rows
    if _jm != "כל השווקים":
        _view = [r for r in _view if (r["ccy"] == "ILS") == (_jm == 'בורסת ת"א')]
    if _jr != "הכל":
        _view = [r for r in _view if (r["gross"] > 0) == (_jr == "ברווח")]  # לפי רווח/הפסד ברוטו, כמו העמודה בטבלה
    if _js == "תשואה":
        _view = sorted(_view, key=lambda r: -r["pct"])
    elif _js == "רווח/הפסד":
        _view = sorted(_view, key=lambda r: -r["net"])
    _tbl = ui_v3.journal_table(_view) if _view else '<div class="nw"><small>אין עסקאות שמתאימות לסינון.</small></div>'
    st.markdown(
        '<div class="v3h">'
        + f'<section class="block" style="margin-top:8px">{_tbl}</section>'
        + (f'<section class="block" style="margin-top:60px">{_eq_html}</section>' if _eq_html else "")
        + '</div>',
        unsafe_allow_html=True,
    )


_tab_slot_history = st.empty()  # placeholder עם מיקום קבוע, נוצר בכל ריצה - כדי שכשעוברים לטאב אחר
# הוא יתרוקן במפורש (לא נשאר תוכן ישן/fragment קפוא) ולא רק יוסתר
with _tab_slot_history.container():
    if st.session_state.active_tab == "history":
        _render_journal_v3()


@st.cache_data(ttl=120)
def _scan_heartbeat_cached() -> str | None:
    """ה-heartbeat האחרון של הסורק (מ-origin כשאפשר - הקובץ המקומי מתיישן, ר' src/scan_status.py)."""
    return scan_status.latest_heartbeat(ROOT_DIR, db_path(cfg))


def _v3_index_cards(index_changes: dict) -> list[dict]:
    """נתוני ארבעת כרטיסי המדדים ל-iframe של ui_v3: לכל מדד סדרות מחירים לכל עצירת טווח (0 = היום/סגירה אחרונה)."""
    _meta = {
        "SP500": ('<span class="num">S&amp;P 500</span>', "SPX", [0, 1, 3, 7, 30, 90]),
        "NASDAQ100": ('<span class="num">NASDAQ-100</span>', "NDX", [0, 1, 3, 7, 30, 90]),
        "TA35": ('ת״א <span class="num">35</span>', "TA35", [0, 1, 3, 7, 30, 90]),
        "TA125": ('ת״א <span class="num">125</span>', "TA125", [0, 1, 3, 7, 30, 90]),
    }
    cards = []
    for idx in ("NASDAQ100", "SP500", "TA35", "TA125"):  # סדר הכרטיסים בדף הבית (מימין לשמאל): נאסד״ק, S&P, ת״א 35, ת״א 125
        label_html, mono, options = _meta[idx]
        trading_open = is_market_open(idx)
        # "יום אחרון" רק כשהשוק פתוח: כשהוא סגור זה אותו יום כמו עצירה 0 ("סגירה dd.mm"), אותו אחוז - כפל מיותר
        options = [o for o in options if not (o == 1 and not trading_open)]
        series, labels = {}, {}
        for d in options:
            if d == 0:
                prices, as_of = get_index_intraday_sparkline(idx, trading_open)
                actually_today = bool(as_of) and "/" not in as_of
                labels["0"] = (
                    "היום" if (trading_open and actually_today)
                    else (f'סגירה <span class="num">{as_of.replace("/", ".")}</span>' if as_of else "היום")
                )
            elif d == 1 and trading_open:
                prices, as_of = get_index_last_completed_sparkline(idx)
                labels["1"] = "יום אחרון"
            else:
                prices, as_of = get_index_sparkline(idx, d)
                labels[str(d)] = "יום אחרון" if d == 1 else f"{d} ימים"
            series[str(d)] = {"prices": prices, "as_of": as_of}
        cards.append({
            "label_html": label_html, "mono": mono, "options": options, "series": series, "labels": labels,
            "val": index_changes.get(idx),
        })
    return cards


def _v3_news_items() -> list[dict]:
    _news_index = (cfg.get("indices") or ALL_INDICES)[0]
    if _news_index not in ALL_INDICES:
        _news_index = ALL_INDICES[0]
    _movers = get_all_changes(_news_index)
    if _movers.empty:
        return []
    _top = _movers.reindex(_movers["שינוי יומי (%)"].abs().sort_values(ascending=False).index).head(3)
    _pairs = [(r.get("שם") or r["טיקר"], r["טיקר"]) for _, r in _top.iterrows()]
    _news = get_footer_news(_pairs, _news_index.upper() in ("TA35", "TA125"))
    items = list(_news["general"])
    for _name, _heads in _news["stock_news"].items():
        for _h in _heads:
            items.append({**_h, "source": f'{_h.get("source", "")} · {_name}'})
    return items[:6]


@st.cache_data(ttl=120)
def _holdings_open_pct(tickers: tuple[str, ...]) -> dict:
    """לכל טיקר: (שינוי בפתיחת המסחר, שינוי אחרון, תאריך הסשן) לפי נר 5 הדקות הראשון של הסשן האחרון מול הסגירה הקודמת."""
    out: dict = {}
    try:
        intra = market_data.fetch_universe_intraday_changes(list(tickers))
        daily = market_data.fetch_universe_daily_changes(list(tickers))
    except Exception:
        return out
    for t in tickers:
        c = intra.get(t)
        row = daily[daily["ticker"] == t] if daily is not None and not daily.empty else None
        if c is None or c.empty or row is None or row.empty:
            continue
        hist = row.iloc[0]["history"]
        sd = c.index[0].date()
        pc = _last_close_before(hist, sd) if hist is not None else None
        if not pc:
            continue
        last_px = float(c.iloc[-1])
        enough = len(c) >= 8
        out[t] = ((float(c.iloc[0]) - pc) / pc * 100, (last_px - pc) / pc * 100, sd,
                  enough and last_px >= float(c.max()) - 1e-9, enough and last_px <= float(c.min()) + 1e-9)
    return out


@st.cache_data(ttl=60)
def _idx_changes_cached() -> dict:
    return get_index_changes()


def _home_market_timing_items() -> list[tuple[str, str, str]]:
    """בורסה שנפתחת/נסגרת בתוך חצי שעה."""
    out = []
    for country, label, verb_open, verb_close in (("IL", 'בורסת ת"א', "נפתחת", "נסגרת"), ("US", "וול סטריט", "נפתחת", "נסגרת")):
        try:
            st_ = get_market_status(country)
            mins = (st_["next_change"] - st_["now"]).total_seconds() / 60
            if 0 < mins <= 30:
                out.append(("info", "", f"{label} {verb_close if st_['open'] else verb_open} בעוד {format_countdown(st_['next_change'], st_['now'])}"))
        except Exception:
            continue
    return out


def _home_alert_followups(fresh_alerts: pd.DataFrame) -> tuple[list, list]:
    """התראות של היום בבורסת ת"א מול המצב הנוכחי: מתאוששות (השינוי היומי השתפר לפחות בחצי אחוז מאז ההתראה) וממשיכות לרדת (החמיר לפחות באחוז).
    כל התראה (לא רק "לקנות"); סיגנל לקנות קודם. (recovering, falling) = [(score, name, text)]."""
    N = ui_v3.num
    try:
        if fresh_alerts is None or fresh_alerts.empty or "scan_date" not in fresh_alerts.columns:
            return [], []
        todays = fresh_alerts[fresh_alerts["scan_date"] == dt.date.today().isoformat()]
        if todays.empty:
            return [], []
        todays = todays.sort_values("scan_ts").drop_duplicates("ticker", keep="last")
        todays = todays[todays["ticker"].map(market_data._is_israeli_ticker)]  # רק בורסת ת"א
        if todays.empty:
            return [], []
        cur_df = get_current_changes_for(tuple(sorted(todays["ticker"].unique())))
        if cur_df is None or cur_df.empty:
            return [], []
        cur_map = dict(zip(cur_df["ticker"], cur_df["pct_change"]))
        gap_map = dict(zip(cur_df["ticker"], cur_df["prev_close_gap"].fillna(False))) if "prev_close_gap" in cur_df.columns else {}
    except Exception:
        return [], []
    rec, fall = [], []
    for _, r in todays.iterrows():
        cur, at = cur_map.get(r["ticker"]), r.get("pct_change")
        if cur is None or pd.isna(cur) or at is None or pd.isna(at) or gap_map.get(r["ticker"]):
            continue
        try:
            hour = int(str(r.get("scan_ts"))[11:13])
        except Exception:
            hour = None
        score, _ = strategy_mod.signal_score(r.get("index_name"), at, r.get("intraday_recovery_pct"), r.get("dist_from_ma50_pct"), r.get("sector"), hour)
        buy = score >= strategy_mod.buy_min_score()
        name = r.get("company_name") or r["ticker"]
        tail = f"{N(ui_v3.signed(cur, 1, '%'))} עכשיו לעומת {N(ui_v3.signed(at, 1, '%'))} בזמן ההתראה" + (" · סיגנל לקנות" if buy else "")
        delta = cur - at
        if delta >= 0.5:
            rec.append((int(buy) * 100 + delta, name, f"מתאוששת מהירידה היומית: {tail}"))
        elif delta <= -1.0:
            fall.append((int(buy) * 100 - delta, name, f"ממשיכה לרדת: {tail}"))
    rec.sort(reverse=True)
    fall.sort(reverse=True)
    return rec, fall


def _home_notice_items(rows: list[dict], day_pct: float | None, fresh_alerts: pd.DataFrame, open_map: dict | None = None,
                       minute: int = 0) -> list[tuple[str, str, str]]:
    """הודעות לראש עמוד הבית: חצייה/קרבה לסטופ ויעד, התאוששות/המשך ירידה של התראות היום, תנודות יומיות חריגות, שינוי התיק, התראות חדשות.
    עד 6 הודעות, בסבב בין הסוגים כדי שלא יידחקו החוצה (סבב של 6 הודעות = דקה = זמן הרענון)."""
    N = ui_v3.num
    stop_x, near_stop, targets, near_target, movers_out, extra, flips = [], [], [], [], [], [], []
    highlow, hold_days, vs_index, news_items = [], [], [], []

    def _open(r: dict) -> bool:
        return is_market_open("TA35" if market_data._is_israeli_ticker(r["ticker"]) else "SP500")

    # כשהמסחר סגור (סוף שבוע / אחרי הסגירה) ההודעות בלשון עבר על הסגירה האחרונה - לא "חצתה/עלתה היום" כאילו המסחר מתנהל עכשיו
    any_open = any(_open(r) for r in rows)
    when_day = "היום" if any_open else "בסגירה האחרונה"
    for r in rows:
        stop, cur = r.get("holding_stop_price"), r.get("current")
        live = _open(r)
        if stop and cur is not None:
            gap = stop_distance_pct(cur, stop)
            if gap < 0:
                stop_x.append(("loss", r["name"], f"חצתה את הסטופ-לוס ב-{N(f'{abs(gap):.1f}%')}" if live else f"נסגרה מתחת לסטופ-לוס ב-{N(f'{abs(gap):.1f}%')}"))
            elif gap <= 2.0:
                near_stop.append((gap, r["name"], live))
        pnl, tgt = r.get("pnl_pct"), strategy_mod.target_pct()
        if pnl is not None and tgt:
            if pnl >= tgt:
                targets.append(("gain", r["name"], "עברה את היעד" if live else "נסגרה מעל היעד"))
            elif tgt - pnl <= 1.0:
                near_target.append((tgt - pnl, r["name"], live))
    near_stop = [("warn", n, (f"קרובה לסטופ-לוס · {N(f'{g:.1f}%')} ממנו" if lv else f"נסגרה קרוב לסטופ-לוס · {N(f'{g:.1f}%')} ממנו")) for g, n, lv in sorted(near_stop)]
    near_target = [("gain", n, (f"קרובה ליעד · {N(f'{g:.1f}%')} ממנו" if lv else f"נסגרה קרוב ליעד · {N(f'{g:.1f}%')} ממנו")) for g, n, lv in sorted(near_target)]
    movers = [(r["daily_pct"], r["name"], _open(r)) for r in rows if r.get("daily_pct") is not None]
    if movers:
        up, down = max(movers), min(movers)
        if up[0] >= 2.0:
            movers_out.append(("gain", up[1], f"עלתה היום ב-{N(f'{up[0]:.1f}%')}" if up[2] else f"עלתה ב-{N(f'{up[0]:.1f}%')} בסגירה האחרונה"))
        if down[0] <= -2.0 and down != up:
            movers_out.append(("loss", down[1], f"ירדה היום ב-{N(f'{abs(down[0]):.1f}%')}" if down[2] else f"ירדה ב-{N(f'{abs(down[0]):.1f}%')} בסגירה האחרונה"))
    if day_pct is not None and abs(day_pct) >= 1.0:
        extra.append(("gain" if day_pct > 0 else "loss", "", f"התיק {'עלה' if day_pct > 0 else 'ירד'} {N(f'{abs(day_pct):.1f}%')} {when_day}" if not any_open else f"התיק {'עלה' if day_pct > 0 else 'ירד'} היום ב-{N(f'{abs(day_pct):.1f}%')}"))
    try:
        if fresh_alerts is not None and not fresh_alerts.empty and "scan_ts" in fresh_alerts.columns:
            ts = pd.to_datetime(fresh_alerts["scan_ts"], utc=True, errors="coerce")
            n_new = int((ts >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=60)).sum())
            if n_new:
                extra.append(("info", "", "התראה חדשה בשעה האחרונה" if n_new == 1 else f"{N(str(n_new))} התראות חדשות בשעה האחרונה"))
    except Exception:
        pass
    # אחזקה שהפכה כיוון מאז פתיחת המסחר (רווח -> הפסד או להפך)
    for r in rows:
        o = (open_map or {}).get(r.get("ticker"))
        cur = r.get("daily_pct")
        if not o or cur is None or o[2] != dt.date.today():
            continue
        op = o[0]
        if abs(op) >= 0.5 and abs(cur) >= 0.5 and (op > 0) != (cur > 0):
            idx = "TA35" if market_data._is_israeli_ticker(r["ticker"]) else "SP500"
            now_txt = "ועומדת על" if is_market_open(idx) else "ונסגרה על"
            frm, to = ("מעלייה לירידה", "loss") if op > 0 else ("מירידה לעלייה", "gain")  # כיוון השינוי היומי - לא רווח/הפסד של האחזקה מהקנייה
            flips.append((to, r["name"], f"עברה {frm} {now_txt} {N(ui_v3.signed(cur, 1, '%'))} לעומת {N(ui_v3.signed(op, 1, '%'))} בפתיחת המסחר"))
    # שיא/שפל של היום
    for r in rows:
        o = (open_map or {}).get(r.get("ticker"))
        if o and len(o) >= 5 and o[2] == dt.date.today():
            d = r.get("daily_pct")
            if o[3] and d is not None and d > 0:  # שיא יומי רק כשהמניה גם ירוקה, שפל רק כשהיא גם אדומה - אחרת ההודעה מטעה
                highlow.append(("gain", r["name"], "במחיר הגבוה של היום"))
            elif o[4] and d is not None and d < 0:
                highlow.append(("loss", r["name"], "במחיר הנמוך של היום"))
    # ימי החזקה מול אופק האסטרטגיה
    for r in rows:
        held = r.get("trading_days_held")
        if held:
            if held == strategy_mod.HOLD_MAX_DAYS:
                hold_days.append(("warn", r["name"], f"יום ההחזקה האחרון לפי האסטרטגיה ({N(str(held))} מתוך {N(str(strategy_mod.HOLD_MAX_DAYS))})"))
            elif strategy_mod.HOLD_MAX_DAYS < held <= strategy_mod.HOLD_MAX_DAYS + 2:  # רק חריגה טרייה - אחזקות ותיקות לא מציפות את הסבב
                hold_days.append(("warn", r["name"], f"מוחזקת {N(str(held))} ימי מסחר, מעבר לאופק של {N(str(strategy_mod.HOLD_MAX_DAYS))}"))
    # התיק מול המדד
    try:
        if day_pct is not None and rows:
            n_il = sum(1 for r in rows if market_data._is_israeli_ticker(r["ticker"]))
            ref = "TA35" if n_il * 2 >= len(rows) else "SP500"
            ch = _idx_changes_cached().get(ref)
            if ch is not None and abs(ch) < 0.05:
                ch = 0.0
            if ch is not None and abs(day_pct - ch) >= 0.5:
                word = "מנצח" if day_pct > ch else "מפגר אחרי"
                vs_index.append(("gain" if day_pct > ch else "loss", "", f"התיק {word} את {INDEX_LABELS[ref]} {when_day}: {N(ui_v3.signed(day_pct, 1, '%'))} לעומת {N(ui_v3.signed(ch, 1, '%'))}"))
    except Exception:
        pass
    # חדשות על אחזקות
    try:
        pairs = [(r["name"], r["ticker"]) for r in rows][:4]
        if pairs:
            sn = get_footer_news(pairs, True).get("stock_news", {})
            for nm, heads in sn.items():
                for h in heads[:1]:
                    title = (h.get("title") or "").strip()
                    if title:
                        news_items.append(("info", "", f"חדשות על {html.escape(nm)}: {html.escape(title[:80])}"))
    except Exception:
        pass
    rec, fall = _home_alert_followups(fresh_alerts)
    rec_items = [("gain", n, t) for _, n, t in rec]
    fall_items = [("loss", n, t) for _, n, t in fall[:2]]
    # דחופות (סטופ/יעד/היפוך כיוון) קודם, עד 4; את שאר המקומות ממלאים מהסוגים האחרים בסבב שמתחלף בכל דקה כדי שכולם יופיעו
    urgent = [stop_x, near_stop, targets, near_target, flips]
    others = [c for c in (rec_items, fall_items, highlow, hold_days, movers_out, vs_index, extra, _home_market_timing_items(), news_items) if c]
    out: list[tuple[str, str, str]] = []
    for i in range(4):
        for c in urgent:
            if i < len(c) and len(out) < 4:
                out.append(c[i])
    if others:
        k = minute % len(others)
        others = others[k:] + others[:k]
        for i in range(6):
            for c in others:
                if i < len(c) and len(out) < 6:
                    out.append(c[i])
    return out


def _render_home_v3() -> None:
    """עמוד הבית בעיצוב v3 (המוקאפים שאושרו): התיק + רדאר הסורק, מצב המדדים, אחזקות, תשואה תוך-יומית, זמני מסחר, חדשות."""

    @st.fragment(run_every="60s")
    def _home_top() -> None:
        fresh = load_alerts(db_path(cfg))
        holdings = fresh[fresh.get("bought") == 1] if (not fresh.empty and "bought" in fresh.columns) else pd.DataFrame()
        portfolio, today, value, proximity, _exposure = _compute_portfolio_summaries(holdings)
        _home_rows = _build_holding_rows(holdings) if not holdings.empty else []
        notice_html = ui_v3.notices(_home_notice_items(
            _home_rows, today[2] if today else None, fresh,
            _holdings_open_pct(tuple(r["ticker"] for r in _home_rows)) if _home_rows else {},
            int(dt.datetime.now().timestamp() // 60),
        ))
        strip_html = ""
        if portfolio and value:
            ccy = "USD" if portfolio[3] == "$" else "ILS"
            strip_html = ui_v3.portfolio_strip(
                value[1], value[4], portfolio[1], portfolio[2],
                today[1] if today else None, today[2] if today else None, ccy,
                day_label=_daily_label_with_date(
                    "שינוי יומי", ui_v3._daily_col_label([r.get("daily_pct_date") for r in _home_rows]), "US" if ccy == "USD" else "IL"),
            )
        minutes = scan_status.age_minutes(_scan_heartbeat_cached())
        radar_html = ui_v3.scanner_radar(scan_status.classify(minutes), minutes)
        st.markdown(
            f'<div class="v3h">{ui_v3.top_zone(notice_html, strip_html, radar_html)}</div>', unsafe_allow_html=True,
        )

    _home_top()

    st.markdown(f'<div class="v3h"><section class="block">{ui_v3.head("מדדים")}</section></div>', unsafe_allow_html=True)

    @st.fragment(run_every="60s")
    def _home_indices() -> None:
        changes = get_index_changes()
        last_good = st.session_state.setdefault("_last_good_index_changes", {})
        for k, v in changes.items():
            if v is not None:
                last_good[k] = v
            elif k in last_good:
                changes[k] = last_good[k]
        _html = _get_live_index_v3_template().replace("__ARGS_JSON__", json.dumps(_v3_index_cards(changes)))
        components.html(_html, height=190)

    _home_indices()

    @st.fragment(run_every="60s")
    def _home_holdings() -> None:
        fresh = load_alerts(db_path(cfg))
        holdings = fresh[fresh.get("bought") == 1] if (not fresh.empty and "bought" in fresh.columns) else pd.DataFrame()
        if holdings.empty:
            return
        rows = []
        for r in _build_holding_rows(holdings):
            if r["pnl_pct"] is None or not r["entry"]:
                continue
            stop = r.get("holding_stop_price")
            rows.append({
                "name": r["name"], "pnl_pct": r["pnl_pct"], "daily_pct": r.get("daily_pct"),
                "daily_pct_date": r.get("daily_pct_date"),
                "pnl_amt": r.get("pnl"), "ccy": r.get("ccy"),
                "daily_amt": (r["current_value"] - r["current_value"] / (1 + r["daily_pct"] / 100))
                if (r.get("current_value") is not None and r.get("daily_pct") is not None and r["daily_pct"] > -100) else None,
                "stop_pct": ((stop / r["entry"] - 1) * 100) if stop else None,
                "tgt_pct": ((_tp / r["entry"] - 1) * 100) if (stop and (_tp := live_target_price(r["entry"], stop, r.get("forecast_target")))) else strategy_mod.target_pct(),
            })
        chart_html = ""
        if rows:
            # מתג אחוזים / שווי לטבלת האחזקות (מיקום בפינה השמאלית של הכותרת - ר' CSS של home_hold_unit)
            with st.container(key="home_hold_unit"):
                _unit = st.segmented_control(
                    "תצוגת אחזקות", ["₪", "%"], default="%", selection_mode="single", key="home_hold_unit_sel", label_visibility="collapsed",
                ) or "%"
            st.markdown(
                f'<div class="v3h">{ui_v3.holdings_section(rows, strategy_mod.target_pct(), "value" if _unit == "₪" else "pct")}</div>',
                unsafe_allow_html=True,
            )
        _comp_df, _comp_as_of, _comp_dom_index, _comp_is_daily = _compute_portfolio_history(holdings)
        if _comp_df is not None and len(_comp_df) >= 2:
            idx = _comp_df.index
            picks = [idx[round(i * (len(idx) - 1) / 4)] for i in range(5)]
            fmt = "%d/%m" if _comp_is_daily else "%H:%M"
            times = [p.strftime(fmt) for p in picks]
            p_col, b_col = _comp_df.columns[0], _comp_df.columns[1]
            # התאריך כשהגרף אינו של היום: יום קודם (גם ביום מסחר לפני הפתיחה) או יום בלי מסחר; גרף של היום - בלי תאריך
            _chart_date = (_comp_as_of or "").replace("/", ".")
            if not _chart_date and _comp_dom_index and _no_trading_today(constituents.INDEX_COUNTRY_CODE.get(str(_comp_dom_index).upper(), "IL")):
                _chart_date = israel_today().strftime("%d.%m")
            chart_html = ui_v3.intraday_chart(
                [(p_col, [float(v) for v in _comp_df[p_col]]), (b_col, [float(v) for v in _comp_df[b_col]])],
                times, str(p_col), str(b_col), date_label=_chart_date,
            )
            st.markdown(f'<div class="v3h">{chart_html}</div>', unsafe_allow_html=True)

    _home_holdings()

    @st.fragment(run_every="60s")
    def _home_hours_news() -> None:
        markets = []
        for country, name in (("IL", "בורסת ת״א"), ("US", "וול סטריט")):
            status = get_market_status(country)
            markets.append({"name": name, "open": status["open"], "target_ms": int(status["next_change"].timestamp() * 1000)})
        try:
            news_items = _v3_news_items()
        except Exception:
            news_items = []
        st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)  # אותו מרווח בין סעיפים (60px) כמו בשאר העמוד
        # זמני מסחר לרוחב כל העמוד (שני השווקים זה לצד זה), החדשות מתחתיהם
        components.html(ui_v3.hours_iframe(markets), height=110)  # שעון רץ (שניות) בצד הלקוח; הגובה מתכוונן ב-fit()
        st.markdown('<div style="height:40px"></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="v3h">{ui_v3.news_section(news_items)}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="v3h">{ui_v3.home_footer()}</div>', unsafe_allow_html=True)

    _home_hours_news()


_LIVE_INDEX_V3_HTML = None


def _get_live_index_v3_template() -> str:
    global _LIVE_INDEX_V3_HTML
    if _LIVE_INDEX_V3_HTML is None:
        _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "live_index_v3", "index.html")
        with open(_path, "r", encoding="utf-8") as _f:
            _LIVE_INDEX_V3_HTML = _f.read()
    return _LIVE_INDEX_V3_HTML


# בעיצוב v3 כל טאב עומד בפני עצמו (כמו במוקאפים); עמוד הבית מוצג רק כשלא נבחר טאב
if st.session_state.active_tab is None:
    _render_home_v3()
st.stop()
