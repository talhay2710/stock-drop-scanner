"""חישוב עמלות, מס רווח הון ודמי ניהול - תמונת ברוטו מול נטו.

ההנחות (ניתנות לעריכה ב-config.yaml):
- עמלת קנייה/מכירה: אחוז ממחזור העסקה, בכפוף לעמלת מינימום
- מס רווח הון: 25% על הרווח לאחר עמלות (רק אם חיובי)
- דמי ניהול: אחוז שנתי, נפרס יחסית לתקופת ההחזקה בפועל (ימים/365), מחושב על שווי הכניסה
"""
import dataclasses


@dataclasses.dataclass
class NetResult:
    country_code: str
    currency: str
    qty: float
    buy_price: float
    sell_price: float
    gross_pnl: float
    buy_commission: float
    sell_commission: float
    total_commission: float
    management_fee: float
    capital_gains_tax: float
    net_pnl: float
    net_return_pct: float
    gross_return_pct: float
    holding_days: int


def compute_risk_based_position_size(
    entry_price: float,
    stop_price: float,
    risk_amount: float,
    reference_size: float,
    max_size: float,
) -> float:
    """גודל השקעה לפי כמה מוכן להפסיד, לא לפי כמה רוצה להרוויח - הפוך מהגישה
    הקודמת (compute_dynamic_position_size, שהוסרה): זו הייתה מגדילה את הגודל
    כשהתשואה הצפויה קטנה כדי "לרדוף" רווח נטו קבוע, כלומר מסתכנת ביותר כסף
    דווקא כשהביטחון בעסקה נמוך יותר - הפוך מניהול סיכונים תקין. כאן: קובעים
    כמה מוכן להפסיד בעסקה בודדת (risk_amount), ומחלקים במרחק הסטופ באחוזים -
    סטופ קרוב (עסקה "בטוחה" יותר) מאפשר פוזיציה גדולה יותר לאותו סיכון קבוע,
    סטופ רחוק דורש פוזיציה קטנה יותר. עדיין מוגבל ל-max_size, ולא יורד מתחת
    ל-20% מ-reference_size (כדי לא "להיעלם" לגמרי בעסקאות עם סטופ רחוק מאוד)."""
    stop_distance_pct = (entry_price - stop_price) / entry_price
    if stop_distance_pct <= 0:
        return reference_size  # לא אמור לקרות (סטופ תמיד מתחת לכניסה) - נפילה בטוחה לגודל הבסיס
    size = risk_amount / stop_distance_pct
    return min(max(size, reference_size * 0.2), max_size)


def compute_net_result(
    country_code: str,
    buy_price: float,
    sell_price: float,
    position_size_ccy: float,
    holding_days: int,
    fees_cfg: dict,
) -> NetResult:
    cc = fees_cfg[country_code]
    qty = position_size_ccy / buy_price if buy_price else 0.0

    buy_value = qty * buy_price
    sell_value = qty * sell_price
    gross_pnl = sell_value - buy_value

    buy_commission = max(buy_value * cc["commission_pct"] / 100.0, cc["commission_min"])
    sell_commission = max(sell_value * cc["commission_pct"] / 100.0, cc["commission_min"])
    total_commission = buy_commission + sell_commission

    profit_after_commission = gross_pnl - total_commission

    management_fee = buy_value * (cc["management_fee_annual_pct"] / 100.0) * (holding_days / 365.0)

    capital_gains_tax = max(profit_after_commission, 0.0) * (cc["capital_gains_tax_pct"] / 100.0)

    net_pnl = profit_after_commission - management_fee - capital_gains_tax

    return NetResult(
        country_code=country_code,
        currency=cc["currency"],
        qty=qty,
        buy_price=buy_price,
        sell_price=sell_price,
        gross_pnl=gross_pnl,
        buy_commission=buy_commission,
        sell_commission=sell_commission,
        total_commission=total_commission,
        management_fee=management_fee,
        capital_gains_tax=capital_gains_tax,
        net_pnl=net_pnl,
        net_return_pct=(net_pnl / buy_value * 100.0) if buy_value else 0.0,
        gross_return_pct=(gross_pnl / buy_value * 100.0) if buy_value else 0.0,
        holding_days=holding_days,
    )
