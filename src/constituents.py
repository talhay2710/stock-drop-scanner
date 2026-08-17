"""שליפת רשימת המניות (טיקרים) עבור המדד הנבחר, ממקורות מוסמכים:
- NASDAQ100: ה-API הרשמי של Nasdaq (api.nasdaq.com) - המקור הישיר של הבורסה עצמה
- SP500: stockanalysis.com - אתר נתונים פיננסיים (אין מקור חינמי "רשמי" בפועל,
  כי הרכב S&P 500 הוא קניין של S&P Dow Jones Indices; זהו האתר האמין ביותר
  שזמין בחינם ומתעדכן בזמן אמת)
- TA35/TA125: קובץ מקומי מאומת. אתר הבורסה הישראלית (tase.co.il) מוגן ע"י
  הגנת בוטים (Incapsula) שחוסמת גישה תכנותית - לא ניתן וגם לא ראוי לעקוף הגנה כזו,
  לכן נעשה שימוש בקובץ מאומת מול Yahoo Finance שיש לעדכן ידנית מול אתר הבורסה מדי רבעון.
"""
import os
import logging
import requests
import pandas as pd
import io

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

NASDAQ_API_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
STOCKANALYSIS_SP500_URL = "https://stockanalysis.com/list/sp-500-stocks/"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

INDEX_PROXY_TICKER = {
    "SP500": "^GSPC",
    "NASDAQ100": "^NDX",
    "TA35": "TA35.TA",
    # ל-TA125 עצמו אין ציטוט ב-Yahoo Finance; משתמשים בקרן סל שעוקבת אחרי המדד כפרוקסי
    "TA125": "TCH-F2.TA",
}

INDEX_CURRENCY = {
    "SP500": "USD",
    "NASDAQ100": "USD",
    "TA35": "ILS",
    "TA125": "ILS",
}

INDEX_COUNTRY_CODE = {
    "SP500": "US",
    "NASDAQ100": "US",
    "TA35": "IL",
    "TA125": "IL",
}


def _from_local_csv(filename: str) -> list[str]:
    path = os.path.join(DATA_DIR, filename)
    df = pd.read_csv(path, comment="#")
    return df["yahoo_ticker"].dropna().astype(str).str.strip().tolist()


def _sp500_from_stockanalysis() -> list[str]:
    resp = requests.get(STOCKANALYSIS_SP500_URL, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]
    tickers = df["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False)
    return tickers.tolist()


def _nasdaq100_from_nasdaq_api() -> list[str]:
    resp = requests.get(NASDAQ_API_URL, headers={**_HEADERS, "Accept": "application/json"}, timeout=20)
    resp.raise_for_status()
    rows = resp.json()["data"]["data"]["rows"]
    return [row["symbol"].strip() for row in rows if row.get("symbol")]


_NASDAQ_NAME_SUFFIXES = [
    " Common Stock", " Class A Common Stock", " Class B Common Stock",
    " Class C Common Stock", " Capital Stock",
]


def get_us_name_map(index: str) -> dict:
    """מיפוי טיקר -> שם חברה, עבור SP500/NASDAQ100 - מגיע חינם באותה קריאה
    ששולפת את רשימת הטיקרים, בלי בקשות נוספות."""
    index = index.upper()
    try:
        if index == "SP500":
            resp = requests.get(STOCKANALYSIS_SP500_URL, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            tables = pd.read_html(io.StringIO(resp.text))
            df = tables[0]
            symbols = df["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False)
            names = df["Company Name"].astype(str).str.strip()
            return dict(zip(symbols, names))
        if index == "NASDAQ100":
            resp = requests.get(NASDAQ_API_URL, headers={**_HEADERS, "Accept": "application/json"}, timeout=20)
            resp.raise_for_status()
            rows = resp.json()["data"]["data"]["rows"]
            name_map = {}
            for row in rows:
                symbol = (row.get("symbol") or "").strip()
                name = (row.get("companyName") or "").strip()
                for suffix in _NASDAQ_NAME_SUFFIXES:
                    if name.endswith(suffix):
                        name = name[: -len(suffix)]
                        break
                if symbol:
                    name_map[symbol] = name
            return name_map
    except Exception as e:
        logger.warning("נכשלה שליפת שמות חברות עבור %s: %s", index, e)
    return {}


def get_il_name_map(index: str) -> dict:
    """מיפוי טיקר -> שם חברה בעברית, עבור TA35/TA125 (מהקובץ המקומי)."""
    filename = "ta35_constituents.csv" if index.upper() == "TA35" else "ta125_constituents.csv"
    path = os.path.join(DATA_DIR, filename)
    try:
        df = pd.read_csv(path, comment="#")
        return dict(zip(df["yahoo_ticker"], df["name"]))
    except Exception:
        return {}


def get_constituents(index: str) -> list[str]:
    """מחזיר רשימת טיקרים (בפורמט Yahoo Finance) עבור המדד המבוקש.

    SP500: stockanalysis.com (חי). NASDAQ100: ה-API הרשמי של Nasdaq (חי).
    TA35/TA125: קובץ מקומי מאומת (data/ta35_constituents.csv, data/ta125_constituents.csv)
    שיש לעדכן מדי פעם מול אתר הבורסה: https://www.tase.co.il - ראה הסבר בראש הקובץ.
    """
    index = index.upper()
    if index == "TA35":
        return _from_local_csv("ta35_constituents.csv")
    if index == "TA125":
        return _from_local_csv("ta125_constituents.csv")
    if index == "SP500":
        try:
            return _sp500_from_stockanalysis()
        except Exception as e:
            raise RuntimeError(
                "נכשלה שליפת רכיבי SP500 מ-stockanalysis.com. בדוק חיבור לאינטרנט ונסה שוב."
            ) from e
    if index == "NASDAQ100":
        try:
            return _nasdaq100_from_nasdaq_api()
        except Exception as e:
            raise RuntimeError(
                "נכשלה שליפת רכיבי NASDAQ100 מה-API הרשמי של Nasdaq. בדוק חיבור לאינטרנט ונסה שוב."
            ) from e
    raise ValueError(f"מדד לא נתמך: {index}")
