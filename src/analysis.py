"""ניתוח סיבת הירידה והערכת "תגובת יתר" - מבוסס כללים היוריסטיים על נתוני מחיר וחדשות.

חשוב: זהו ניתוח אוטומטי מבוסס היוריסטיקות וסינון חדשות חופשי - לא ייעוץ השקעות,
ולא תחליף לקריאת הדוח/החדשות בפועל. יש לאמת כל התרעה לפני קבלת החלטה.

נקודת הרחבה עתידית: ניתן להחליף/להעשיר את classify_drop() בקריאה למודל שפה
(Claude API) שיקרא את הכותרות ויסכם סיבה + הערכת תגובת-יתר בשפה חופשית,
במקום/בנוסף לכללים הקשיחים כאן.
"""
import dataclasses

from . import market_data
from . import news as news_mod
from . import quality as quality_mod


@dataclasses.dataclass
class DropAnalysis:
    ticker: str
    reasons: list          # תגיות: market_wide / sector_pressure / earnings_reaction / profit_taking / stock_specific / unclear
    reason_text: str       # תיאור בעברית
    headlines: list
    has_headlines: bool
    overreaction_verdict: str
    overreaction_score: int
    zscore: float | None
    rsi: float | None
    index_change_pct: float | None
    sector: str | None
    sector_change_pct: float | None
    trailing_rally_pct: float | None
    volume_ratio: float | None = None
    vix_level: float | None = None
    intraday_recovery_pct: float | None = None
    quality: "quality_mod.QualityAssessment | None" = None
    rebound_tier: str = "C"      # "A" / "B" / "C" - שילוב ציון תגובת-יתר + איכות פונדמנטלית
    rebound_label: str = ""
    residual_drop_pct: float | None = None   # הירידה שלא מוסברת ע"י המדד/הסקטור (ר' חישוב ב-classify_drop)
    dist_from_ma50_pct: float | None = None  # מרחק המחיר מהממוצע הנע 50 יום, אחוזים (חיובי=מעל)


_SPLIT_RATIOS = (0.5, 1 / 3, 2 / 3, 0.25, 0.75, 0.2, 0.4, 0.6, 0.8, 0.1, 0.05)


def _looks_like_split(prev_close: float | None, last_close: float | None, tolerance: float = 0.015) -> float | None:
    """אם היחס בין מחיר הסגירה האחרון לקודם קרוב מאוד ליחס פיצול מניה נפוץ
    (חצי, שליש, רבע וכו') - זו כמעט תמיד עדות לפיצול מניה שלא טופל בנתונים,
    לא ירידה אמיתית. מחזיר את היחס שזוהה, או None אם שום דבר לא מתאים."""
    if not prev_close or not last_close:
        return None
    ratio = last_close / prev_close
    for split_ratio in _SPLIT_RATIOS:
        if abs(ratio - split_ratio) <= tolerance:
            return split_ratio
    return None


def classify_drop(
    ticker: str,
    yahoo_symbol: str,
    company_name: str | None,
    is_israeli: bool,
    pct_change: float,
    close_history,
    index_change_pct: float | None,
    cfg: dict,
    volume_ratio: float | None = None,
    vix_level: float | None = None,
    intraday_recovery_pct: float | None = None,
) -> DropAnalysis:
    reasons = []
    deep = market_data.get_stock_deep_info(yahoo_symbol)
    quality = quality_mod.assess_quality(deep)
    zscore = market_data.compute_volatility_zscore(close_history, pct_change)
    rsi = market_data.compute_rsi(close_history)
    trailing_rally = market_data.compute_trailing_rally_pct(
        close_history, cfg.get("lookback_rally_days", 10)
    )

    # -1. ירידה טכנית עקב פיצול מניה (Stock Split) שלא טופל בנתונים - לא ירידה
    # אמיתית בשווי, ובטח שלא הזדמנות "קניית דיפ". מזוהה לפי יחס המחיר עצמו
    # (חצי/שליש/רבע וכו'), כי לא תמיד יש נתון פיצול אמין/עדכני מהמקור.
    prev_close = float(close_history.iloc[-2]) if close_history is not None and len(close_history) >= 2 else None
    split_ratio = _looks_like_split(prev_close, float(close_history.iloc[-1]) if close_history is not None and len(close_history) else None)
    if split_ratio is not None:
        reason_text = (
            f"{REASON_LABELS['stock_split']} (המחיר ירד ביחס של כ-{split_ratio:.2f} מהמחיר הקודם - "
            f"תואם פיצול מניה נפוץ, לא ירידה אמיתית)"
        )
        headlines = news_mod.get_recent_headlines(yahoo_symbol, is_israeli, company_name)
        return DropAnalysis(
            ticker=ticker,
            reasons=["stock_split"],
            reason_text=reason_text,
            headlines=headlines,
            has_headlines=len(headlines) > 0,
            overreaction_verdict="ירידה טכנית ולא אמיתית (כנראה פיצול מניה) - לא מומלץ להתייחס כהזדמנות 'קניית דיפ'",
            overreaction_score=0,
            zscore=zscore,
            rsi=rsi,
            index_change_pct=index_change_pct,
            sector=deep.get("sector"),
            sector_change_pct=None,
            trailing_rally_pct=trailing_rally,
            volume_ratio=volume_ratio,
            vix_level=vix_level,
            intraday_recovery_pct=intraday_recovery_pct,
            quality=quality,
        )

    # 0. ירידה טכנית עקב ניתוק דיבידנד (Ex-Dividend) - לא ירידה "אמיתית", לא הזדמנות קנייה
    ex_div_amount = deep.get("ex_dividend_amount")
    ex_div_pct = (ex_div_amount / prev_close * 100.0) if (ex_div_amount and prev_close) else None
    if ex_div_pct is not None and ex_div_pct >= abs(pct_change) * 0.5:
        reason_text = (
            f"{REASON_LABELS['ex_dividend']} (חלוקה של כ-{ex_div_pct:.1f}% מהמחיר - "
            f"מסבירה את רוב הירידה הנצפית)"
        )
        headlines = news_mod.get_recent_headlines(yahoo_symbol, is_israeli, company_name)
        return DropAnalysis(
            ticker=ticker,
            reasons=["ex_dividend"],
            reason_text=reason_text,
            headlines=headlines,
            has_headlines=len(headlines) > 0,
            overreaction_verdict="ירידה טכנית ולא אמיתית - לא מומלץ להתייחס כהזדמנות 'קניית דיפ'",
            overreaction_score=0,
            zscore=zscore,
            rsi=rsi,
            index_change_pct=index_change_pct,
            sector=deep.get("sector"),
            sector_change_pct=None,
            trailing_rally_pct=trailing_rally,
            volume_ratio=volume_ratio,
            vix_level=vix_level,
            intraday_recovery_pct=intraday_recovery_pct,
            quality=quality,
        )

    # 1. יום חלש בשוק
    market_wide = False
    if index_change_pct is not None and index_change_pct <= -1.0:
        excess = pct_change - index_change_pct  # כמה גרוע יותר מהמדד (שלילי=גרוע יותר)
        if excess >= -3.0:  # רוב הירידה מוסברת ע"י השוק הכללי
            reasons.append("market_wide")
            market_wide = True

    # 2. לחץ סקטוריאלי
    sector_change = deep.get("sector_etf_change_pct")
    if sector_change is not None and sector_change <= -1.0:
        sector_excess = pct_change - sector_change
        if sector_excess >= -3.0:
            reasons.append("sector_pressure")

    # 3. תגובה לדוח כספי
    if deep.get("recent_earnings"):
        reasons.append("earnings_reaction")

    # 4. מימושים אחרי עלייה
    rally_threshold = cfg.get("rally_threshold_pct", 8.0)
    if trailing_rally is not None and trailing_rally >= rally_threshold:
        reasons.append("profit_taking")

    # ירידה עודפת (Relative Strength / residual drop): כמה מהירידה לא מוסברת
    # ע"י המדד או הסקטור - חיסור פשוט, לא רגרסיה, אבל מספיק כדי להראות אם
    # מניה ספציפית חלשה יותר מהסביבה שלה. None אם אין שום נתון השוואה זמין
    # (למשל מניית ת"א בלי sector_etf_change_pct).
    residual_drop_pct = None
    if index_change_pct is not None or sector_change is not None:
        residual_drop_pct = pct_change - (index_change_pct or 0.0) - (sector_change or 0.0)

    # מרחק מהממוצע הנע 50 יום - "כמה רחוק מהמגמה" נפלה המניה. מוגבל ל-50 יום
    # (לא 200) כי חלון הנתונים הרגיל (3 חודשים) לא מכיל מספיק היסטוריה ל-200
    # יום, ולהרחיב אותו לכל מניה נסרקת יקר מדי מול המגבלה של yfinance החינמי.
    dist_from_ma50_pct = None
    if close_history is not None and len(close_history) >= 50:
        ma50 = float(close_history.tail(50).mean())
        if ma50:
            dist_from_ma50_pct = (float(close_history.iloc[-1]) - ma50) / ma50 * 100

    headlines = news_mod.get_recent_headlines(yahoo_symbol, is_israeli, company_name)
    has_headlines = len(headlines) > 0
    if not reasons:
        reasons.append("stock_specific_news" if has_headlines else "unclear")

    reason_text = _build_reason_text(
        reasons, index_change_pct, sector_change, trailing_rally, deep, volume_ratio, vix_level
    )

    overreaction_score, overreaction_verdict = _score_overreaction(
        zscore, rsi, reasons, has_headlines, cfg, volume_ratio, vix_level, headlines, intraday_recovery_pct
    )
    rebound_tier, rebound_label = _classify_rebound(overreaction_score, quality)

    return DropAnalysis(
        ticker=ticker,
        reasons=reasons,
        reason_text=reason_text,
        headlines=headlines,
        has_headlines=has_headlines,
        overreaction_verdict=overreaction_verdict,
        overreaction_score=overreaction_score,
        zscore=zscore,
        rsi=rsi,
        index_change_pct=index_change_pct,
        sector=deep.get("sector"),
        sector_change_pct=sector_change,
        trailing_rally_pct=trailing_rally,
        volume_ratio=volume_ratio,
        vix_level=vix_level,
        intraday_recovery_pct=intraday_recovery_pct,
        quality=quality,
        rebound_tier=rebound_tier,
        rebound_label=rebound_label,
        residual_drop_pct=residual_drop_pct,
        dist_from_ma50_pct=dist_from_ma50_pct,
    )


REASON_LABELS = {
    "market_wide": "יום חלש בשוק הכללי",
    "sector_pressure": "לחץ סקטוריאלי רוחבי",
    "earnings_reaction": "תגובה לדוח כספי שפורסם לאחרונה",
    "profit_taking": "מימושים לאחר עלייה חדה",
    "stock_specific_news": "ייתכן שיש חדשות ספציפיות למניה - יש לבדוק בכותרות למטה",
    "ex_dividend": "ירידה טכנית עקב ניתוק דיבידנד (Ex-Dividend)",
    "stock_split": "ירידה טכנית עקב פיצול מניה (Stock Split)",
    "unclear": "לא נמצאה סיבה ברורה",
}


def _build_reason_text(reasons, index_change_pct, sector_change, trailing_rally, deep,
                        volume_ratio=None, vix_level=None) -> str:
    parts = []
    for r in reasons:
        label = REASON_LABELS[r]
        if r == "market_wide" and index_change_pct is not None:
            label += f" (המדד ירד {index_change_pct:.1f}% היום)"
        if r == "sector_pressure" and sector_change is not None:
            etf = deep.get("sector_etf_ticker", "")
            label += f" (סקטור {deep.get('sector', '')} / {etf} ירד {sector_change:.1f}%)"
        if r == "profit_taking" and trailing_rally is not None:
            label += f" (עלתה כ-{trailing_rally:.1f}% בימים שקדמו לירידה)"
        parts.append(label)

    if volume_ratio is not None and volume_ratio >= 2.0:
        parts.append(f"נפח מסחר גבוה פי {volume_ratio:.1f} מהממוצע - ייתכן מכירת פאניקה")
    elif volume_ratio is not None and volume_ratio < 0.7:
        parts.append(f"נפח מסחר נמוך מהרגיל (פי {volume_ratio:.1f}) - האיתות פחות אמין")

    if vix_level is not None and vix_level >= 30:
        parts.append(f"מדד הפחד (VIX) ברמה קיצונית של {vix_level:.0f} - עצבנות רחבה בשוק")
    elif vix_level is not None and vix_level >= 22:
        parts.append(f"מדד הפחד (VIX) ברמה מוגברת של {vix_level:.0f}")

    return " | ".join(parts)


# ציון סופי הוא ממוצע משוקלל של 6 תת-ציונים רציפים (0-100 כל אחד), לא ספירת
# תגיות בינארית - כדי שהפרש עדין בין שני מקרים (למשל z-score 2.1 מול 3.8, שניהם
# מעל אותו סף) ישפיע בפועל על הציון הסופי ולא רק על מעבר/אי-מעבר סף.
# המשקלים: חריגה סטטיסטית (22.5%) ופחד בשוק/VIX (18%) הם האיתותים הכמותיים
# החזקים ביותר; בהירות הסיבה (18%) ותגובת דוח (13.5%) תלויים באיכות המקורות
# החופשיים; נפח מסחר ו-RSI (9% כל אחד) הם גורמים תומכים משניים. Intraday
# Recovery (10%, נוסף 22.8.2026) - איפה המניה נסגרה בתוך הטווח היומי שלה -
# הוזז לכאן מ-11 מקום פינוי יחסי מכל שאר המשקלים (כל אחד *0.9), כי אין עדיין
# דאטה מספיק לכייל משקלים אמפירית (ר' backtest, project_scoring_weight_validation).
MAX_OVERREACTION_SCORE = 100

# 🔒 מוקפא (v1.0, 2026-08-23) - אחרי ביקורת GPT שנייה על האסטרטגיה, הוחלט
# להפסיק לכייל את המשקלים/הספים האלה עד שיצטבר מספיק דאטה (ר' signal_log,
# scanner._log_shadow_signals) לבדיקה אמיתית מחוץ-למדגם (walk-forward) - כל
# עוד בודקים-ומשנים-בודקים-ומשנים על אותו דאטה, יש סיכון אמיתי ל-overfitting
# להיסטוריה. פרטים מלאים ב-project_strategy_gpt_feedback_overhaul (זיכרון).
# לפני שינוי כאן: לוודא שיש סיבה אמיתית שאינה "בדיקה נוספת על אותה היסטוריה".
_SCORE_WEIGHTS = {
    "zscore": 0.225,
    "vix": 0.18,
    "reason": 0.18,
    "earnings": 0.135,
    "volume": 0.09,
    "rsi": 0.09,
    "intraday_recovery": 0.10,
}

_EARNINGS_BEAT_KEYWORDS = ("beats", "beat ", "tops estimates", "exceeds", "surpasses", "better-than-expected")
_EARNINGS_MISS_KEYWORDS = ("misses", "miss ", "falls short", "disappoints", "worse-than-expected",
                           "cuts guidance", "lowers guidance", "warns")


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _zscore_subscore(zscore, threshold) -> float:
    """50 בדיוק בסף שהוגדר בהגדרות (התנהגות דומה לגרסה הבינארית הישנה בנקודה
    הזו), 0 בלי חריגה כלל, 100 בפי 2 מהסף - כדי שחריגה קיצונית תתגמל יותר
    מחריגה גבולית, במקום שתיהן לקבל את אותה נקודה כמו בגרסה הבינארית."""
    if zscore is None:
        return 50.0
    return _clamp(abs(zscore) / (threshold * 2) * 100)


def _vix_subscore(vix_level) -> float:
    if vix_level is None:
        return 50.0
    return _clamp((vix_level - 12) / (35 - 12) * 100)


def _reason_subscore(reasons, has_headlines) -> float:
    macro_reason = any(r in reasons for r in ("market_wide", "sector_pressure", "profit_taking"))
    if macro_reason and not has_headlines:
        return 90.0  # הסבר רחב/טכני מובהק, בלי חדשות שליליות ספציפיות למניה
    if macro_reason and has_headlines:
        return 65.0  # הסבר רחב קיים, אבל יש גם חדשות ספציפיות - איתות מעורב
    if reasons == ["unclear"] and not has_headlines:
        return 70.0  # אין הסבר גלוי בכלל - חשד סביר לתגובת יתר טכנית
    if reasons == ["unclear"] and has_headlines:
        return 40.0  # יש כותרות אך לא סווגו - עמימות, נוטה לזהירות
    if reasons == ["stock_specific_news"]:
        return 35.0  # חדשות ספציפיות למניה נמצאו - סביר שהירידה מוצדקת עסקית
    return 50.0


def _earnings_subscore(reasons, headlines) -> float:
    if "earnings_reaction" not in reasons:
        return 50.0  # הגורם לא רלוונטי למקרה הזה - נייטרלי, לא מטה את הממוצע המשוקלל
    headline_text = " ".join((h.get("title") or "") for h in (headlines or [])).lower()
    beat = any(k in headline_text for k in _EARNINGS_BEAT_KEYWORDS)
    miss = any(k in headline_text for k in _EARNINGS_MISS_KEYWORDS)
    if beat and not miss:
        return 85.0  # דוח טוב אבל המניה ירדה בכל זאת - תומך בתגובת יתר
    if miss and not beat:
        return 15.0  # דוח חלש - סביר שהירידה מוצדקת פונדמנטלית
    return 50.0  # לא ניתן לקבוע מהכותרות - נייטרלי


def _volume_subscore(volume_ratio, intraday_recovery_pct=None) -> float:
    """נפח חריג לבדו הוא איתות מעורב, לא חד-משמעי: יכול להיות קפיטולציה
    (פאניקת מכירה שנגמרת -> תומך בריבאונד) אבל גם מכירה מוסדית שממשיכה
    (לא תומך). היכן שהמניה נסגרה בטווח היומי שלה (intraday_recovery_pct)
    מבדיל בין השניים - נסגרה קרוב לשפל למרות נפח גבוה = דגל אדום (ממשיכים
    למכור), נסגרה קרוב לשיא עם נפח גבוה = קפיטולציה+התאוששות אמיתית."""
    if volume_ratio is None:
        return 50.0
    base = _clamp((volume_ratio - 0.5) / (3.0 - 0.5) * 100)
    if intraday_recovery_pct is None or volume_ratio < 1.5:
        return base  # נפח לא באמת חריג, או אין נתון טווח יומי - משאירים כמו שהיה
    if intraday_recovery_pct <= 30:
        return base * 0.4
    if intraday_recovery_pct >= 70:
        return min(100.0, base * 1.15)
    return base


def _rsi_subscore(rsi) -> float:
    if rsi is None:
        return 50.0
    return _clamp((50 - rsi) / (50 - 15) * 100)


def _intraday_recovery_subscore(intraday_recovery_pct) -> float:
    """נסגרה קרוב לשיא היום (למרות שהיום כולו היה יום ירידה) = קונים נכנסו
    לקראת הסגירה, תומך בתגובת יתר/ריבאונד. נסגרה קרוב לשפל = המשיכו למכור
    עד הסוף, פחות תומך. הסולם כבר 0-100 מטבעו, אין צורך בעוד נרמול."""
    if intraday_recovery_pct is None:
        return 50.0
    return _clamp(intraday_recovery_pct)


def _score_overreaction(zscore, rsi, reasons, has_headlines, cfg, volume_ratio=None, vix_level=None,
                         headlines=None, intraday_recovery_pct=None) -> tuple[int, str]:
    threshold = cfg.get("overreaction_zscore", 2.5)
    subscores = {
        "zscore": _zscore_subscore(zscore, threshold),
        "vix": _vix_subscore(vix_level),
        "reason": _reason_subscore(reasons, has_headlines),
        "earnings": _earnings_subscore(reasons, headlines),
        "volume": _volume_subscore(volume_ratio, intraday_recovery_pct),
        "rsi": _rsi_subscore(rsi),
        "intraday_recovery": _intraday_recovery_subscore(intraday_recovery_pct),
    }
    score = round(sum(subscores[k] * _SCORE_WEIGHTS[k] for k in _SCORE_WEIGHTS))

    if score >= 70:
        verdict = "סבירות גבוהה לתגובת יתר טכנית - מועמדת פוטנציאלית לריבאונד, בכפוף לבדיקה ידנית"
    elif score >= 45:
        verdict = "לא חד משמעי - ייתכן שילוב של גורמים, מומלץ לבדוק את הכותרות והדוח לפני החלטה"
    else:
        verdict = "הירידה עשויה להיות מוצדקת פונדמנטלית - להיזהר מ'קניית הדיפ' ללא בדיקה מעמיקה"
    return score, verdict


def _classify_rebound(overreaction_score: int, quality) -> tuple[str, str]:
    """מסווג "סיכוי ריבאונד" (A/B/C) - לא רק מהציון הטכני, אלא בשילוב עם איכות
    פונדמנטלית: איכות נמוכה (חברה בעייתית עסקית) מורידה ל-C גם אם האיתות הטכני
    חזק, כי איתות טכני חיובי לא מפצה על חברה שנופלת מסיבה עסקית אמיתית."""
    quality_low = quality is not None and quality.tier == "low"
    if quality_low:
        return "C", "🔴 סיכוי ריבאונד נמוך - איכות פונדמנטלית חלשה מטילה ספק גם באיתות טכני חיובי"
    if overreaction_score >= 70:
        return "A", "🟢 סיכוי גבוה לריבאונד - איתות טכני חזק, ללא דגל איכות פונדמנטלי משמעותי"
    if overreaction_score >= 45:
        return "B", "🟡 סיכוי אפשרי לריבאונד - איתות מעורב, מומלץ לבדוק ידנית לפני החלטה"
    return "C", "🔴 סיכוי ריבאונד נמוך - הירידה עשויה להיות מוצדקת ולא רק תגובת יתר"
