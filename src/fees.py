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


def compute_dynamic_position_size(
    country_code: str,
    buy_price: float,
    sell_price: float,
    target_net_profit: float,
    reference_size: float,
    max_size: float,
    holding_days: int,
    fees_cfg: dict,
) -> float:
    """גודל השקעה שיניב בקירוב target_net_profit נטו ביעד, במקום גודל קבוע -
    כשה-% הצפוי לרווח קטן צריך להשקיע יותר כדי להגיע לאותו סכום נטו, ולהפך.
    מוגבל תמיד ל-max_size (תקרת סיכון) ולא יורד מתחת ל-20% מ-reference_size."""
    reference_result = compute_net_result(country_code, buy_price, sell_price, reference_size, holding_days, fees_cfg)
    if reference_result.net_return_pct <= 0:
        return reference_size  # אין רווח צפוי לפי ה-% הזה - אין טעם להגדיל סיכון כדי "לרדוף" יעד
    required_size = target_net_profit / (reference_result.net_return_pct / 100.0)
    return min(max(required_size, reference_size * 0.2), max_size)


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
