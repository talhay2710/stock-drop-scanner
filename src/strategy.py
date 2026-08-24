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
FIXED_TARGET_PCT = 0.05

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
    if target_base is not None and target_base == target_base:
        return target_base
    return target_from_stop(entry, stop_price)

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
