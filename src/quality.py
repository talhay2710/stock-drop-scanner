"""סינון איכות פונדמנטלית - האם החברה מאחורי הירידה בריאה מספיק כדי שתזת "קניית
דיפ" תהיה הגיונית, ולא סתם מניה שנופלת כי היא בעייתית עסקית. מבוסס יחסים
פונדמנטליים בסיסיים מ-yfinance (info dict שכבר נשלף ב-market_data.get_stock_deep_info,
בלי קריאת רשת נוספת).

זהו תג מידע ("badge"), לא סינון קשיח - התראה לא נחסמת בגלל איכות נמוכה/לא ידועה,
כי הנתונים (בעיקר למניות ת"א) חסרים לעיתים קרובות ואי-אפשר להבדיל בין "איכות
נמוכה באמת" ל"אין מידע". חסימת התראות על בסיס נתון חסר הייתה מסתירה הזדמנויות
אמיתיות בלי סיבה טובה.
"""
import dataclasses


@dataclasses.dataclass
class QualityAssessment:
    tier: str              # "high" / "medium" / "low" / "unknown"
    tier_label: str
    tier_emoji: str
    score: float | None    # 0-100, None אם אין מספיק נתונים כדי לקבוע
    flags: list            # תיאורי בעיה שזוהו (לתצוגה בהודעה/בדשבורד)
    data_points_used: int


# מתחת לכך "לא ידוע" - לא מנחשים ציון על בסיס שדה פונדמנטלי בודד
_MIN_DATA_POINTS = 2


def assess_quality(deep_info: dict) -> QualityAssessment:
    flags: list[str] = []
    subscores: list[float] = []

    market_cap = deep_info.get("market_cap")
    if market_cap is not None:
        subscores.append(min(market_cap / 2_000_000_000, 1.0) * 100)
        if market_cap < 300_000_000:
            flags.append("שווי שוק קטן (מתחת ל-300M) - תנודתיות ונזילות בסיכון גבוה יותר")

    profit_margin = deep_info.get("profit_margin")
    if profit_margin is not None:
        subscores.append(max(0.0, min(profit_margin, 0.25)) / 0.25 * 100)
        if profit_margin < 0:
            flags.append("שולי רווח שליליים (הפסדית)")

    roe = deep_info.get("return_on_equity")
    if roe is not None:
        subscores.append(max(0.0, min(roe, 0.30)) / 0.30 * 100)
        if roe < 0:
            flags.append("תשואה על ההון שלילית")

    dte = deep_info.get("debt_to_equity")
    if dte is not None:
        # debtToEquity מ-yfinance מגיע בדרך כלל כאחוזים (150 = חוב פי 1.5 מההון)
        subscores.append(max(0.0, 1.0 - min(dte, 300) / 300) * 100)
        if dte > 200:
            # "~" במקום "כ-" בכוונה - מקף צמוד למספר בתוך עברית לא התיישר נכון
            # ויזואלית (bidi), גם עם סימני LRM/LRI/PDI. "~" נמנע מהבעיה לגמרי.
            flags.append(f"מינוף גבוה (יחס חוב/הון ~{dte:.0f}%)")

    revenue_growth = deep_info.get("revenue_growth")
    if revenue_growth is not None:
        subscores.append(max(0.0, min(revenue_growth + 0.10, 0.30)) / 0.30 * 100)
        if revenue_growth < -0.10:
            flags.append("ירידה בהכנסות (מעל 10%- שנה מול שנה)")

    current_ratio = deep_info.get("current_ratio")
    if current_ratio is not None:
        subscores.append(min(current_ratio / 2.0, 1.0) * 100)
        if current_ratio < 1.0:
            flags.append("יחס שוטף מתחת ל-1 - נזילות עסקית מוגבלת")

    if len(subscores) < _MIN_DATA_POINTS:
        return QualityAssessment(
            tier="unknown", tier_label="לא ידוע", tier_emoji="⚪",
            score=None, flags=flags, data_points_used=len(subscores),
        )

    score = round(sum(subscores) / len(subscores))
    if score >= 65:
        tier, label, emoji = "high", "גבוהה", "🏛️"
    elif score >= 40:
        tier, label, emoji = "medium", "בינונית", "🏚️"
    else:
        tier, label, emoji = "low", "נמוכה", "🚩"

    return QualityAssessment(
        tier=tier, tier_label=label, tier_emoji=emoji,
        score=score, flags=flags, data_points_used=len(subscores),
    )
