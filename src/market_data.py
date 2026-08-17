"""שליפת נתוני מחירים (Yahoo Finance דרך yfinance)."""
import concurrent.futures
import datetime as dt
import logging
import pandas as pd
import numpy as np
import yfinance as yf

from .constituents import INDEX_PROXY_TICKER
from .market_hours import is_market_open

logger = logging.getLogger(__name__)

# מניות ת"א (.TA) מדווחות ב-Yahoo Finance באגורות (currency='ILA'), לא בש"ח -
# ממירים לש"ח (חלקי 100) מיד עם השליפה כדי שכל שאר האפליקציה תעבוד ביחידה עקבית.
def _is_israeli_ticker(ticker: str) -> bool:
    return ticker.upper().endswith(".TA")


_CLOSED_WEEKDAYS = {5, 6}  # Mon=0..Sun=6: שבת=5, ראשון=6 - מ-5.1.2026 זהה לת"א ולארה"ב (ר' market_hours.py)


def _expected_last_close_date(as_of: dt.date) -> dt.date:
    """יום המסחר האחרון שכבר אמור להיות זמין נכון ל-as_of (לא כולל as_of עצמו).
    לא לוקח בחשבון חגים ספציפיים - הערכה גסה שנועדה לתפוס פערי נתונים אמיתיים
    (יום-יומיים), לא דיוק מושלם."""
    d = as_of - dt.timedelta(days=1)
    while d.weekday() in _CLOSED_WEEKDAYS:
        d -= dt.timedelta(days=1)
    return d


def is_data_stale(last_close_date, ticker: str, as_of: dt.date | None = None) -> bool:
    """True אם last_close_date ישן יותר מיום המסחר האחרון שכבר אמור להיות זמין -
    כלומר יש פער אמיתי בנתונים (המקור לא התעדכן), לא סתם שהשוק סגור כרגע.
    מנגנון מרכזי אחד לבדיקת טריות - כל מקום שמשתמש ב-last_close/prev_close
    צריך לעבור דרכו לפני שהוא מציג/מפעיל החלטה על "שינוי יומי", כדי שלא יקרה
    שוב שהשוואה של יומיים-שלושה אחורה תוצג/תשמש כאילו היא של אתמול/היום."""
    if last_close_date is None:
        return True
    expected = _expected_last_close_date(as_of or dt.date.today())
    return last_close_date < expected

# מיפוי סקטור GICS -> ETF סקטוריאלי (SPDR) לצורך השוואת "לחץ סקטוריאלי" בשוק האמריקאי בלבד
US_SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


def fetch_universe_daily_changes(tickers: list[str], history_period: str = "3mo") -> pd.DataFrame:
    """מוריד היסטוריית מחירים עבור כל המניות ברשימה בבת אחת, ומחזיר טבלת
    שינוי יומי אחוזי לכל מניה (סגירה אחרונה מול הסגירה הקודמת).
    """
    data = yf.download(
        tickers=tickers,
        period=history_period,
        interval="1d",
        group_by="ticker",
        threads=True,
        auto_adjust=False,
        progress=False,
    )

    rows = []
    for ticker in tickers:
        try:
            # yfinance מחזיר עמודות MultiIndex (עם רמת הטיקר) עם group_by="ticker"
            # תמיד - גם כשמורידים טיקר בודד - אז אין צורך (ואסור) להתייחס לזה כמקרה מיוחד
            sub = data[ticker] if isinstance(data.columns, pd.MultiIndex) else data
            closes = sub["Close"].dropna()
            volumes = sub["Volume"].dropna()
            lows = sub["Low"].dropna()
            highs = sub["High"].dropna()
            if _is_israeli_ticker(ticker):
                closes = closes / 100.0
                lows = lows / 100.0
                highs = highs / 100.0
            if len(closes) < 2:
                continue
            last_close = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2])
            pct_change = (last_close - prev_close) / prev_close * 100.0
            rows.append({
                "ticker": ticker,
                "last_close": last_close,
                "prev_close": prev_close,
                "pct_change": pct_change,
                # תאריך הסגירה האחרונה שבפועל התקבלה - כדי שמי שצריך לוודא "טריות"
                # (למשל התראת עלייה באחזקה, שלא כדאי שתשווה מול סגירה מלפני הקנייה)
                # יוכל לבדוק בעצמו, בלי להסתיר את המחיר האחרון הידוע משאר האפליקציה
                "last_close_date": closes.index[-1].date(),
                "prev_close_date": closes.index[-2].date(),
                "last_low": float(lows.iloc[-1]) if len(lows) else None,
                "recent_20d_low": float(lows.tail(20).min()) if len(lows) else None,
                "last_volume": float(volumes.iloc[-1]) if len(volumes) else None,
                "avg_volume_20d": float(volumes.tail(20).mean()) if len(volumes) else None,
                "history": closes,
                "highs": highs,
                "lows_series": lows,
            })
        except Exception as e:
            logger.debug("דילוג על %s: %s", ticker, e)
            continue

    _fix_stale_rows_with_live_quote(rows)
    return pd.DataFrame(rows)


def _fix_stale_rows_with_live_quote(rows: list[dict]) -> None:
    """ל-yf.download() בבת אחת יש נטייה לפגר יום שלם מאחורי הציטוט החי
    (regularMarketPrice) - במיוחד במניות ת"א. בנוסף, כשהשוק *פתוח כרגע*, נתון
    הסגירה היומית (שמתעדכן רק בסוף היום) אף פעם לא באמת "עדכני" - צריך את
    הציטוט החי כדי לשקף תנועה תוך-יומית. בשני המקרים מתקנים עם ציטוט חי בודד
    למניה (במקביל, כדי לא להאט יותר מדי) - רק אם זה באמת משפר את הטריות.
    בלי זה: (1) "שינוי יומי" נשאר תקוע יום-יומיים מאחורי המציאות בלי שאף אחד
    ישים לב, וגם (2) כשהשוק נפתח מחדש, המערכת עלולה "להתריע" שוב על אותה
    ירידה שכבר התריעה עליה אתמול, כי הנתון היומי עדיין אותו נתון בדיוק."""
    target_rows = [
        r for r in rows
        if is_data_stale(r.get("last_close_date"), r["ticker"])
        or is_market_open("TA35" if _is_israeli_ticker(r["ticker"]) else "NASDAQ100")
    ]
    if not target_rows:
        return

    def _fetch_live(row: dict) -> None:
        try:
            info = yf.Ticker(row["ticker"]).info
            price, prev = info.get("regularMarketPrice"), info.get("regularMarketPreviousClose")
            ts = info.get("regularMarketTime")
            if price is None or prev is None or not ts or not prev:
                return
            close_date = dt.datetime.fromtimestamp(ts).date()
            # רק אם הציטוט החי ישן יותר ממה שכבר יש מדלגים (לא רוצים לרגרס
            # לאחור). "אותו תאריך" עדיין מוחלף - price+prev מגיעים תמיד יחד
            # מאותו ציטוט, זוג עקבי. לעומת זאת ה-.history() בבת אחת התברר
            # כבעל "חורים" (למשל דילג יום שלם) - כשזה קורה, ה-Close של יומיים
            # אחורה (יומיים!) מזדווג בטעות עם ה-Close של היום כאילו הוא "אתמול",
            # וממשיך להיראות "לא ישן" כי last_close_date בעצמו עדכני. לכן אין
            # להסתפק בבדיקת last_close_date בלבד - תמיד מעדיפים את הזוג
            # העקבי מהציטוט החי על פני הרכבה-מחדש שעלולה לצרף תאריכים לא רצופים.
            if row.get("last_close_date") and close_date < row["last_close_date"]:
                return
            if _is_israeli_ticker(row["ticker"]):
                price, prev = price / 100.0, prev / 100.0
            row["last_close"] = float(price)
            row["prev_close"] = float(prev)
            row["pct_change"] = (price - prev) / prev * 100.0
            row["last_close_date"] = close_date
        except Exception as e:
            logger.debug("נכשל ניסיון תיקון-טריות עבור %s: %s", row["ticker"], e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        list(executor.map(_fetch_live, target_rows))


def fetch_current_price(ticker: str) -> float | None:
    """מחיר עדכני אמיתי (regularMarketPrice) לטיקר בודד - בניגוד ל-Close היומי
    שמגיע מ-yf.download() בבת אחת עבור הרבה טיקרים, שמתגלה לפעמים כפער/מפגר
    (לא מעודכן לסשן המסחר האחרון בפועל). איטי יותר (קריאת רשת בודדת), ולכן
    מיועד למספר קטן של טיקרים - כמו האחזקות שלך - לא לסריקת יקום שלם."""
    try:
        info = yf.Ticker(ticker).info
        price = info.get("regularMarketPrice")
        if price is None:
            return None
        return float(price) / 100.0 if _is_israeli_ticker(ticker) else float(price)
    except Exception as e:
        logger.debug("נכשלה שליפת מחיר עדכני עבור %s: %s", ticker, e)
        return None


def fetch_index_proxy_change(index: str) -> float | None:
    proxy = INDEX_PROXY_TICKER.get(index.upper())
    if not proxy:
        return None
    try:
        hist = yf.Ticker(proxy).history(period="5d")
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return None
        return float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100.0)
    except Exception as e:
        logger.warning("נכשלה שליפת שינוי המדד (%s): %s", proxy, e)
        return None


def fetch_index_history(index: str, period: str) -> pd.Series:
    """היסטוריית סגירות יומיות של פרוקסי המדד (למשל TA35.TA), לשימוש בגרף
    השוואת תשואת התיק מול המדד. אין המרת אגורות/ש"ח כאן בכוונה - הקורא צריך
    רק את השינוי היחסי (%), לא את המחיר המוחלט, אז יחידת המידה לא משנה."""
    proxy = INDEX_PROXY_TICKER.get(index.upper())
    if not proxy:
        return pd.Series(dtype=float)
    try:
        hist = yf.Ticker(proxy).history(period=period)
        return hist["Close"].dropna()
    except Exception as e:
        logger.warning("נכשלה שליפת היסטוריית המדד (%s): %s", proxy, e)
        return pd.Series(dtype=float)


def compute_volatility_zscore(close_history: pd.Series, today_pct_change: float, window: int = 30) -> float | None:
    """מחשב z-score של שינוי המחיר היום ביחס לתנודתיות היומית הרגילה של המניה
    (סטיית תקן של תשואות יומיות ב-window הימים האחרונים, לא כולל היום)."""
    if close_history is None or len(close_history) < window + 2:
        return None
    returns = close_history.pct_change().dropna() * 100.0
    baseline = returns.iloc[-(window + 1):-1]
    std = baseline.std()
    if not std or np.isnan(std) or std == 0:
        return None
    return float(today_pct_change / std)


def compute_atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> float | None:
    """Average True Range - מדד תנודתיות סטנדרטי במונחי מחיר (לא אחוזים), כדי
    שסטופ-לוס יתאים לתנודתיות האמיתית של המניה במקום אחוז קבוע לכולן. True
    Range ליום = הגדול מבין: high-low, |high-prev_close|, |low-prev_close|.
    ATR = ממוצע נע של ה-True Range על פני period ימים."""
    if highs is None or lows is None or closes is None:
        return None
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None
    prev_closes = closes.shift(1)
    true_range = pd.concat([
        highs - lows,
        (highs - prev_closes).abs(),
        (lows - prev_closes).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.dropna().tail(period).mean()
    return float(atr) if pd.notna(atr) else None


def compute_n_day_change_pct(close_history: pd.Series, n: int = 3) -> float | None:
    """שינוי מצטבר (%) ב-n ימי המסחר האחרונים, כולל היום (מהסגירה לפני n ימים ועד הסגירה האחרונה)."""
    if close_history is None or len(close_history) < n + 1:
        return None
    last_close = close_history.iloc[-1]
    base_close = close_history.iloc[-(n + 1)]
    if base_close == 0:
        return None
    return float((last_close - base_close) / base_close * 100.0)


def get_close_n_days_ago(close_history: pd.Series, n: int) -> float | None:
    """מחיר הסגירה מלפני n ימי מסחר (לא כולל היום) - משמש כבסיס לחישוב גודל תיקון
    כשההתראה מבוססת על ירידה מצטברת רב-יומית ולא רק ירידה של יום בודד."""
    if close_history is None or len(close_history) < n + 1:
        return None
    return float(close_history.iloc[-(n + 1)])


def fetch_vix_level() -> tuple[float | None, float | None]:
    """שולף את רמת מדד הפחד (VIX) הנוכחית ואת השינוי היומי שלו (%) - אינדיקציה
    למידת העצבנות הכללית בשוק, לשימוש בכיול הערכת תגובת-היתר."""
    try:
        hist = yf.Ticker("^VIX").history(period="5d")
        closes = hist["Close"].dropna()
        if len(closes) < 1:
            return None, None
        level = float(closes.iloc[-1])
        change_pct = None
        if len(closes) >= 2 and closes.iloc[-2]:
            change_pct = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100.0)
        return level, change_pct
    except Exception as e:
        logger.warning("נכשלה שליפת VIX: %s", e)
        return None, None


def compute_trailing_rally_pct(close_history: pd.Series, lookback_days: int) -> float | None:
    """תשואה מצטברת ב-lookback_days ימי מסחר שקדמו לירידה של היום (לא כולל היום)."""
    if close_history is None or len(close_history) < lookback_days + 2:
        return None
    pre_drop_close = close_history.iloc[-2]
    start_close = close_history.iloc[-(lookback_days + 2)]
    if start_close == 0:
        return None
    return float((pre_drop_close - start_close) / start_close * 100.0)


def compute_rsi(close_history: pd.Series, period: int = 14) -> float | None:
    """RSI(14) סטנדרטי, מחושב עד ליום המסחר האחרון הזמין (כולל הירידה)."""
    if close_history is None or len(close_history) < period + 1:
        return None
    delta = close_history.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0 or np.isnan(avg_loss):
        return 100.0 if avg_gain and avg_gain > 0 else None
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def fetch_latest_prices(tickers: list[str]) -> dict[str, float]:
    """שולף את מחיר הסגירה האחרון הזמין עבור רשימת טיקרים, בבת אחת."""
    if not tickers:
        return {}
    try:
        data = yf.download(
            tickers=tickers, period="2d", interval="1d",
            group_by="ticker", threads=True, auto_adjust=False, progress=False,
        )
    except Exception as e:
        logger.warning("נכשלה שליפת מחירים עדכניים: %s", e)
        return {}

    prices = {}
    for ticker in tickers:
        try:
            sub = data if len(tickers) == 1 else data[ticker]
            closes = sub["Close"].dropna()
            if len(closes):
                price = float(closes.iloc[-1])
                if _is_israeli_ticker(ticker):
                    price /= 100.0
                prices[ticker] = price
        except Exception:
            continue
    return prices


def get_stock_deep_info(ticker: str) -> dict:
    """שליפת מידע מפורט (סקטור, דוחות קרובים, דיבידנד אחרון) עבור מניה בודדת - להריץ רק על מניות שסומנו."""
    info = {"sector": None, "industry": None, "currency": None, "recent_earnings": False,
            "sector_etf_change_pct": None, "short_name": None, "ex_dividend_amount": None,
            "market_cap": None, "profit_margin": None, "return_on_equity": None,
            "debt_to_equity": None, "revenue_growth": None, "current_ratio": None}
    try:
        tk = yf.Ticker(ticker)
        raw_info = tk.get_info() if hasattr(tk, "get_info") else tk.info
        info["sector"] = raw_info.get("sector")
        info["industry"] = raw_info.get("industry")
        info["currency"] = raw_info.get("currency")
        info["short_name"] = raw_info.get("shortName") or raw_info.get("longName")
        # שדות פונדמנטליים לסינון איכות (quality.py) - נשלפים מאותה קריאת .info
        # שכבר בוצעה למעלה, בלי בקשת רשת נוספת. שדות אלה נעדרים לעיתים קרובות
        # למניות ת"א ב-yfinance - הטיפול בערכי None קורה ב-quality.assess_quality.
        info["market_cap"] = raw_info.get("marketCap")
        info["profit_margin"] = raw_info.get("profitMargins")
        info["return_on_equity"] = raw_info.get("returnOnEquity")
        info["debt_to_equity"] = raw_info.get("debtToEquity")
        info["revenue_growth"] = raw_info.get("revenueGrowth")
        info["current_ratio"] = raw_info.get("currentRatio")

        sector_etf = US_SECTOR_ETF.get(info["sector"])
        if sector_etf:
            try:
                hist = yf.Ticker(sector_etf).history(period="5d")
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    info["sector_etf_change_pct"] = float(
                        (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100.0
                    )
                    info["sector_etf_ticker"] = sector_etf
            except Exception:
                pass

        try:
            edates = tk.get_earnings_dates(limit=4)
            if edates is not None and len(edates):
                now = pd.Timestamp.now(tz=edates.index.tz)
                recent = edates.index[(edates.index <= now) & (edates.index >= now - pd.Timedelta(days=2))]
                info["recent_earnings"] = len(recent) > 0
        except Exception:
            pass

        try:
            divs = tk.dividends
            if divs is not None and len(divs):
                today = pd.Timestamp.now(tz=divs.index.tz).normalize()
                todays_div = divs[divs.index.normalize() == today]
                if len(todays_div):
                    amount = float(todays_div.iloc[-1])
                    info["ex_dividend_amount"] = amount / 100.0 if _is_israeli_ticker(ticker) else amount
        except Exception:
            pass
    except Exception as e:
        logger.warning("נכשלה שליפת מידע מורחב עבור %s: %s", ticker, e)
    return info
