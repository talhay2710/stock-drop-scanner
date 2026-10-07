"""הצעת שער כניסה (לימיט), יעד מכירה ותרחיש יציאה - מבוסס אסטרטגיית "קנייה אחרי
תיקון, מכירה בריבאונד". אלו חישובים טכניים היוריסטיים בלבד, לא המלצת השקעה אישית -
יש לבחון כל הצעה בעצמך לפני קבלת החלטה.
"""
import dataclasses


@dataclasses.dataclass
class TradeIdea:
    entry_limit: float
    entry_note: str
    support_reference: float | None
    target_base: float
    stop_loss: float
    stop_loss_note: str
    liquidity_tier: str = "unknown"   # "high" / "medium" / "low" / "unknown"
    liquidity_note: str = ""


# הוגדל מ-1.5 ל-2.5 ב-23.8.2026, אחרי בדיקה על ~60-68 התראות היסטוריות
# (backtest.compare_stop_multipliers): מכפיל רחב יותר נתן תוחלת גבוהה יותר
# בעקביות (1.0x=3.26%, 1.5x=3.33%, 2.0x=3.84%, 2.5x=4.57%) - סטופ רחב מדי
# פוגע פחות ב"רעש" רגיל של המניה לפני שהיא ממשיכה לכיוון שצפוי. המגמה עוד
# עולה ב-2.5x (לא נמצא שיא), אבל נבחר כפשרה שמרנית - מדגם קטן ורחב מדי מקטין
# את מספר העסקאות שמוכרעות בתוך חלון הבדיקה (הטיה אפשרית כלפי מעלה).
ATR_STOP_MULTIPLIER = 2.5  # מרחק הסטופ מהכניסה = פי X מה-ATR (תנודתיות היום-יומית הרגילה)
MIN_TARGET_REWARD_RISK_RATIO = 1.0  # פולבאק בלבד עכשיו (ר' live_target_price) - לא רצפה פעילה על target_base יותר

# יעד קבוע (לא Fibonacci) - הוחלף ב-21.8.2026 אחרי בדיקה על ההיסטוריה בפועל
# (backtest.compare_target_strategies): יעד Fibonacci 50% (הקודם) נתן תוחלת
# (רווח ממוצע אמיתי, לא רק שיעור הצלחה) של 3.66%, בעוד יעד קבוע 5% נתן 4.02%
# ו-6% נתן 4.59% - יעד קבוע גדול יותר "מצליח" פחות (קשה יותר להגיע אליו) אבל
# משתלם יותר בממוצע כי כל הצלחה שווה יותר. נבחר 5% (לא 6%, השיא בבדיקה) כי
# המדגם קטן (56-76 עסקאות לאסטרטגיה) ו-5% שמרני יותר מ-6% שעלול להיות רעש.
FIXED_TARGET_PCT = 0.03  # שונה מ-5% ל-3% ב-7.10.2026: באופק החזקה של עד 3 ימים יעד של 3% מתממש הרבה יותר (ר' סיגנל כניסה למטה)

REWARD_RISK_RATIO = 1.5  # פולבאק בלבד (ר' live_target_price) - כשאין שום target_base שמור (אחזקה ידנית לגמרי)
# הרצפה (MIN_TARGET_REWARD_RISK_RATIO) אומתה ב-backtest על 64 התראות היסטוריות:
# כשמלווים אותה בהארכה יחסית של חלון-ההמתנה (ר' backtest.py), שיעור ההצלחה
# כמעט זהה (94.6% מול 92.9%) - בלי הרצפה יש עסקאות עם יחס סיכוי/סיכון גרוע
# מ-1:1 (למשל תיקון של רק 2.6% מול סטופ של 8%), שהרצפה מתקנת.


def target_from_stop(entry: float, stop_price: float, ratio: float = REWARD_RISK_RATIO) -> float:
    return entry + (entry - stop_price) * ratio


def live_target_price(entry: float, stop_price: float, target_base: float | None) -> float:
    """היעד החי המוצג/מתריע עבור אחזקה: target_base (כפי שחושב ונשמר בזמן
    ההתראה המקורית, קבוע ולא זז לעולם בגלל מרחק הסטופ - ר' ATR_STOP_MULTIPLIER);
    אם אין target_base בכלל (אחזקה ידנית לגמרי בלי התראה מקורית) - פולבאק
    ל-REWARD_RISK_RATIO. מקור אמת יחיד - גם לתצוגה בדשבורד וגם להתראת טלגרם,
    כדי ששניהם תמיד יראו את אותו יעד בדיוק."""
    # target_base == target_base שוללת NaN (בלי תלות ב-pandas כאן) - זה יכול
    # להגיע כ-NaN כשהקורא הוא DataFrame (הדשבורד), לא רק None (התראת טלגרם).
    # 7.10.2026: היעד של אחזקה נגזר מהאסטרטגיה הנוכחית (+FIXED_TARGET_PCT מעל מחיר הכניסה
    # בפועל, אופק עד HOLD_MAX_DAYS ימים) ולא מה-target_base שנשמר בהתראה - אחרת אחזקות שנפתחו
    # לפני שינוי האסטרטגיה נשארו עם יעד של 5% בתצוגה ובגרפים. target_base/stop_price נשארו בחתימה
    # לתאימות עם הקוראים.
    return round(entry * (1 + FIXED_TARGET_PCT), 2)


def stop_distance_pct(current: float, stop_price: float) -> float:
    """כמה % המחיר הנוכחי מעל/מתחת לסטופ-לוס, *יחסית למחיר הסטופ עצמו*
    (לא יחסית לכניסה - שני דברים שונים ששווים רק כשהכניסה=הסטופ במקרה).
    מקור אמת יחיד - במקום 3+ מימושים נפרדים שהתפצלו בפועל (15.9.2026:
    כרטיס 'התיק שלי' הראה 1.6% וכרטיס האחזקה עצמה הראה 2.0% לאותה אחזקה
    באותו רגע, וגרף רווח/הפסד הציג בטולטיפ מספר שלישי לא-קשור בכלל).
    שלילי = כבר חצתה את הסטופ."""
    return (current - stop_price) / stop_price * 100


def target_distance_pct(current: float, target_price: float) -> float:
    """כמו stop_distance_pct, ליעד: כמה % המחיר הנוכחי מתחת ליעד, יחסית
    ליעד עצמו. שלילי = כבר עברה את היעד."""
    return (target_price - current) / target_price * 100


# ספי נזילות (נפח מסחר ממוצע יומי בערך $/₪) לצורך מרווח נוסף בלימיט הכניסה.
# אין מקור נתונים חינמי ואמין ל-bid/ask spread אמיתי (בטח לא היסטורית), ולכן
# זהו פרוקסי מבוסס נפח מסחר - לא מדד spread מדויק, אבל נפח נמוך מתאם בפועל
# עם spread רחב יותר וסיכון החלקה (slippage) גבוה יותר במימוש הזמנה בפועל.
LIQUIDITY_HIGH_THRESHOLD = 10_000_000
LIQUIDITY_MEDIUM_THRESHOLD = 2_000_000


def _liquidity_adjustment(avg_dollar_volume: float | None) -> tuple[float, str, str]:
    if avg_dollar_volume is None:
        return 0.0, "unknown", "אין נתוני נפח מספיקים להערכת נזילות"
    if avg_dollar_volume >= LIQUIDITY_HIGH_THRESHOLD:
        return 0.0, "high", "נזילות גבוהה (לפי נפח מסחר $ ממוצע יומי) - לא נדרש מרווח נוסף בלימיט"
    if avg_dollar_volume >= LIQUIDITY_MEDIUM_THRESHOLD:
        return 0.003, "medium", "נזילות בינונית - נוסף מרווח קטן ללימיט הכניסה כדי לצמצם סיכון החלקה (slippage)"
    return 0.007, "low", "נזילות נמוכה - נוסף מרווח משמעותי ללימיט, ייתכן קושי לממש בדיוק במחיר המבוקש"


def suggest_strategy(last_close: float, last_low: float | None,
                      recent_20d_low: float | None, overreaction_score: int,
                      atr: float | None = None, avg_dollar_volume: float | None = None) -> TradeIdea:
    # שער כניסה: מעט מתחת למחיר הנוכחי, כדי לתת מרווח לקפיטולציה נוספת.
    # ככל שסבירות תגובת-היתר גבוהה יותר (ניקוד 0-100), המרווח שנדרש קטן יותר -
    # מדורג באופן רציף לפי הציון המשוקלל, כך שכל שינוי בציון (לא רק חציית סף)
    # משפיע בפועל על מרחק הכניסה. בנוסף, מניות דלות-נזילות מקבלות מרווח נוסף
    # (ראו _liquidity_adjustment) כדי להקטין סיכון החלקה בין הלימיט למימוש בפועל.
    score_buffer_pct = max(0.005, 0.015 - (overreaction_score / 100) * 0.010)
    liquidity_buffer_pct, liquidity_tier, liquidity_note = _liquidity_adjustment(avg_dollar_volume)
    buffer_pct = score_buffer_pct + liquidity_buffer_pct
    entry_limit = round(last_close * (1 - buffer_pct), 2)

    entry_note = (
        f"לימיט כ-{buffer_pct*100:.1f}% מתחת למחיר הנוכחי, כדי לתפוס המשך ירידה קלה "
        f"מבלי לרדוף אחרי המניה"
    )
    if liquidity_tier in ("medium", "low"):
        entry_note += f" (כולל מרווח נוסף בשל נזילות {('בינונית' if liquidity_tier == 'medium' else 'נמוכה')})"

    target_base = round(last_close * (1 + FIXED_TARGET_PCT), 2)

    stop_ref = last_low if last_low is not None else last_close
    anchor = min(stop_ref, entry_limit)
    if atr is not None and atr > 0:
        # סטופ לפי תנודתיות אמיתית של המניה (ATR) במקום אחוז קבוע לכולן - מניה
        # תנודתית מקבלת סטופ רחוק יותר, מניה יציבה מקבלת סטופ צמוד יותר.
        stop_loss = round(anchor - ATR_STOP_MULTIPLIER * atr, 2)
        stop_pct = (stop_loss / anchor - 1) * 100
        stop_loss_note = f"כ-{ATR_STOP_MULTIPLIER:g}x ATR מתחת לשפל היום / שער הכניסה (בפועל {abs(stop_pct):.1f}%, לפי תנודתיות המניה)"
    else:
        stop_loss = round(anchor * 0.97, 2)
        stop_loss_note = "כ-3% מתחת לשפל היום / שער הכניסה, לפי הנמוך מביניהם (אין נתוני ATR זמינים)"

    # יעד המכירה לא יורד מתחת לרווח מינימלי של 3% מעל שער הכניסה (הצדקת כניסה
    # לעסקה אחרי עמלות ומס). בעבר הייתה כאן גם רצפת יחס סיכוי/סיכון 1:1 מול
    # מרחק הסטופ - הוסרה בכוונה ב-23.8.2026 יחד עם הרחבת הסטופ (ATR_STOP_MULTIPLIER
    # ל-2.5x): המשתמש ביקש במפורש שהיעד לא יזוז לעולם בגלל מרחק הסטופ, וקיבל
    # את הפשרה - יחס סיכוי/סיכון עלול להיות גרוע מ-1:1 במניות תנודתיות, בלי הגנה.
    min_target_profit = round(entry_limit * 1.03, 2)
    target_base = max(target_base, min_target_profit)

    return TradeIdea(
        entry_limit=entry_limit,
        entry_note=entry_note,
        support_reference=recent_20d_low,
        target_base=target_base,
        stop_loss=stop_loss,
        stop_loss_note=stop_loss_note,
        liquidity_tier=liquidity_tier,
        liquidity_note=liquidity_note,
    )


# ---------------------------------------------------------------------------
# סיגנל כניסה: 🟢 לקנות / 🟡 לחכות / 🔴 לא לקנות (7.10.2026) - כרטיס ניקוד רב-גורמי
#
# אופק האסטרטגיה: החזקה של כמה שעות עד 3 ימי מסחר (HOLD_MAX_DAYS), יעד +3% (FIXED_TARGET_PCT),
# כניסה במחיר ההתראה. התוצאות נמדדות *מרגע ההתראה בלבד*, מנתוני 5 דקות (ר' post_alert.py) -
# המדידה הקודמת מנתונים יומיים ספרה גם את השיא של לפני ההתראה והגזימה (הצלחה ~58% במקום ~43%).
#
# הגורמים נבחרו כי הכיוון שלהם זהה בשתי מחציות הזמן של הנתונים, והוסיפו יכולת הבחנה מחוץ
# למדגם (AUC על המחצית המאוחרת: ישראל 0.57 לגודל הירידה לבד -> ~0.71 עם כל הגורמים;
# ארה"ב 0.56 -> 0.66; משקלים נקבעו על המחצית המוקדמת ונבדקו על המאוחרת, ולהפך):
#   1. גודל הירידה (גורם חזק ביותר).        2. מרחק מהממוצע הנע 50 יום (רחוק מתחת = טוב, מעליו = רע).
#   3. סקטור (תשתיות/טכנולוגיה חזקים; נדל"ן/אנרגיה חלשים).
#   4. ישראל: שעת ההתראה (עד 12:59 עדיף).  ארה"ב: המחיר כבר התאושש מהשפל של היום.
# גורמים שנבדקו ולא הוסיפו יכולת הבחנה יציבה: ציון תגובת-יתר, איכות פונדמנטלית, A/B/C,
# נפח מסחר, RSI, VIX, סוג שוק, וסיבת הירידה (דוח/מימושים/חדשות).
# תוצאות (ישראל, 345 התראות, 32 ימים): ניקוד 4+ -> 71% הגיעו ליעד, +1.2% לעסקה; 2-3 -> ~48%,
# בערך אפס; 1 ומטה -> ~32%, -0.7% לעסקה. ארה"ב (682 התראות, 20 ימים): 4+ -> 68%, +1.4%.
# ברוטו, לפני עמלות ומס. התראות מקובצות בימים (30 ימים בלבד) - לבחון מחדש עם עוד נתונים.
# ---------------------------------------------------------------------------
HOLD_MAX_DAYS = 3
TARGET_PCT = FIXED_TARGET_PCT * 100
SIGNAL_BUY, SIGNAL_WAIT, SIGNAL_AVOID, SIGNAL_UNKNOWN = "buy", "wait", "avoid", "unknown"
SIGNAL_EMOJI = {SIGNAL_BUY: "🟢", SIGNAL_WAIT: "🟡", SIGNAL_AVOID: "🔴", SIGNAL_UNKNOWN: "⚪"}
SIGNAL_LABEL = {SIGNAL_BUY: "לקנות", SIGNAL_WAIT: "לחכות", SIGNAL_AVOID: "לא לקנות", SIGNAL_UNKNOWN: "אין נתונים"}
ISRAELI_INDICES = ("TA35", "TA125")
BUY_MIN_SCORE = 4
MAX_SIGNAL_SCORE = 6  # הניקוד המקסימלי האפשרי: ירידה חדה 2 + רחוק מהממוצע 1 + סקטור חזק 2 + בוקר/התאוששות 1
WAIT_MIN_SCORE = 2

_SECTOR_HE = {
    "Utilities": "תשתיות", "Technology": "טכנולוגיה", "Real Estate": 'נדל"ן', "Energy": "אנרגיה",
    "Basic Materials": "חומרי גלם", "Consumer Cyclical": "צריכה מחזורית", "Financial Services": "פיננסים",
    "Industrials": "תעשייה", "Healthcare": "בריאות", "Communication Services": "תקשורת",
    "Consumer Defensive": "צריכה בסיסית",
}


REBOUND_CLASS = {SIGNAL_BUY: "A", SIGNAL_WAIT: "B", SIGNAL_AVOID: "C", SIGNAL_UNKNOWN: "—"}


def rebound_class(signal: str) -> str:
    """סיווג ריבאונד A/B/C = הרמזור של האסטרטגיה (A=🟢 לקנות, B=🟡 לחכות, C=🔴 לא לקנות), במקום
    הסיווג הישן (60% תגובת יתר + 40% איכות), שלא הבדיל בין הצלחה לכישלון (7.10.2026)."""
    return REBOUND_CLASS.get(signal, "—")


def sector_he(sector: str | None) -> str:
    return _SECTOR_HE.get(sector, sector) if sector else "—"
_IL_STRONG_SECTORS = {"Utilities", "Technology"}
_IL_WEAK_SECTORS = {"Real Estate", "Energy", "Basic Materials"}
_US_STRONG_SECTORS = {"Utilities", "Technology", "Basic Materials"}
_US_WEAK_SECTORS = {"Real Estate", "Energy", "Consumer Cyclical", "Financial Services"}


def _known(x) -> bool:
    return x is not None and x == x  # x == x שוללת NaN


def signal_score(index_name: str | None, pct_change: float, intraday_recovery_pct=None,
                 dist_from_ma50_pct=None, sector: str | None = None,
                 alert_hour: int | None = None) -> tuple[int, list[tuple[str, int]]]:
    """(ניקוד כולל, רשימת (גורם, נקודות)). גורם שחסר לו נתון פשוט לא תורם."""
    drop = abs(pct_change)
    is_il = (index_name or "").upper() in ISRAELI_INDICES
    parts: list[tuple[str, int]] = []

    if is_il:
        if drop >= 4.5:
            parts.append((f"ירידה חדה {drop:.1f}%", 2))
    else:
        if drop >= 6:
            parts.append((f"ירידה חדה {drop:.1f}%", 2))
        elif drop >= 4.5:
            parts.append((f"ירידה {drop:.1f}%", 1))

    if _known(dist_from_ma50_pct):
        if dist_from_ma50_pct <= -10:
            parts.append((f"רחוק מהממוצע ({dist_from_ma50_pct:.0f}%)", 1))
        elif dist_from_ma50_pct > 0.9:
            parts.append(("מעל הממוצע הנע", -1))

    strong, weak = (_IL_STRONG_SECTORS, _IL_WEAK_SECTORS) if is_il else (_US_STRONG_SECTORS, _US_WEAK_SECTORS)
    if sector in strong:
        parts.append((f"סקטור חזק ({_SECTOR_HE.get(sector, sector)})", 2))
    elif sector in weak:
        parts.append((f"סקטור חלש ({_SECTOR_HE.get(sector, sector)})", -2))

    if is_il:
        if alert_hour is not None and alert_hour <= 12:
            parts.append(("התראה בבוקר", 1))
    elif _known(intraday_recovery_pct) and intraday_recovery_pct >= 12:
        parts.append(("התאושש מהשפל", 1))

    return sum(p for _, p in parts), parts


def entry_signal(index_name: str | None, pct_change: float, intraday_recovery_pct=None,
                 dist_from_ma50_pct=None, sector: str | None = None,
                 alert_hour: int | None = None) -> tuple[str, str]:
    """מחזיר (סיגנל, הסבר עם הגורמים). אופק החזקה: עד HOLD_MAX_DAYS ימים, יעד TARGET_PCT%."""
    if not _known(pct_change):
        return SIGNAL_UNKNOWN, "אין נתון על גודל הירידה"
    score, parts = signal_score(index_name, pct_change, intraday_recovery_pct, dist_from_ma50_pct, sector, alert_hour)
    if score >= BUY_MIN_SCORE:
        signal = SIGNAL_BUY
    elif score >= WAIT_MIN_SCORE:
        signal = SIGNAL_WAIT
    else:
        signal = SIGNAL_AVOID
    detail = " · ".join(f"{name} ({pts:+d})" for name, pts in parts) if parts else "אין גורם תומך"
    return signal, f"ניקוד {max(score, 0)} מתוך {MAX_SIGNAL_SCORE}: {detail}"
