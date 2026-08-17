"""שליפת חדשות רלוונטיות ממקורות חינמיים אך מוסמכים (סוכנויות/גופי חדשות מוכרים).

מקורות:
- yfinance Ticker.news - אגרגציית Yahoo Finance, כוללת תוכן מסוכנויות (Reuters/AP) ומו"לים פיננסיים מוכרים
- Seeking Alpha per-symbol RSS - חדשות וניתוחים ספציפיים למניה (ארה"ב/נאסד"ק)
- Nasdaq per-symbol RSS - חדשות ספציפיות למניה
- Globes / Calcalist RSS - חדשות עסקיות עבריות כלליות, מסוננות לפי שם החברה (ישראל)
"""
import logging
import datetime as dt
import feedparser
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

SEEKING_ALPHA_RSS = "https://seekingalpha.com/api/sa/combined/{symbol}.xml"
NASDAQ_RSS = "https://www.nasdaq.com/feed/rssoutbound?symbol={symbol}"
GLOBES_RSS = "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=2"
CALCALIST_RSS = "https://www.calcalist.co.il/GeneralRSS/0,16335,L-8,00.xml"

MAX_AGE_DAYS = 3
MAX_HEADLINES = 5
RSS_TIMEOUT_SECONDS = 10


def _parse_feed(url: str) -> feedparser.FeedParserDict:
    """feedparser.parse(url) לא קובע timeout בעצמו ויכול להיתקע לצמיתות על חיבור
    תקוע - שולפים דרך requests עם timeout מפורש ומעבירים את התוכן הגולמי במקום."""
    resp = requests.get(url, timeout=RSS_TIMEOUT_SECONDS, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def _recent(published: dt.datetime | None) -> bool:
    if published is None:
        return True  # אם אין תאריך, לא פוסלים - עדיף להראות מאשר לפספס
    now = dt.datetime.now(dt.timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=dt.timezone.utc)
    return (now - published) <= dt.timedelta(days=MAX_AGE_DAYS)


def _from_yfinance(symbol: str) -> list[dict]:
    out = []
    try:
        items = yf.Ticker(symbol).news or []
        for it in items[:10]:
            content = it.get("content", it)
            title = content.get("title") or it.get("title")
            if not title:
                continue
            pub_str = content.get("pubDate") or content.get("displayTime")
            published = None
            if pub_str:
                try:
                    published = dt.datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                except Exception:
                    published = None
            if not _recent(published):
                continue
            link = (content.get("canonicalUrl") or {}).get("url") or it.get("link")
            source = (content.get("provider") or {}).get("displayName") or "Yahoo Finance"
            out.append({"title": title, "source": source, "link": link, "published": published})
    except Exception as e:
        logger.debug("yfinance news נכשל עבור %s: %s", symbol, e)
    return out


def _from_symbol_rss(url_template: str, symbol: str, source_name: str) -> list[dict]:
    out = []
    try:
        feed = _parse_feed(url_template.format(symbol=symbol))
        for entry in feed.entries[:10]:
            published = None
            if getattr(entry, "published_parsed", None):
                published = dt.datetime(*entry.published_parsed[:6], tzinfo=dt.timezone.utc)
            if not _recent(published):
                continue
            out.append({
                "title": entry.get("title"),
                "source": source_name,
                "link": entry.get("link"),
                "published": published,
            })
    except Exception as e:
        logger.debug("RSS (%s) נכשל עבור %s: %s", source_name, symbol, e)
    return out


def _from_hebrew_general_feed(url: str, company_name: str, source_name: str) -> list[dict]:
    out = []
    if not company_name:
        return out
    try:
        feed = _parse_feed(url)
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if company_name in title or company_name in summary:
                published = None
                if getattr(entry, "published_parsed", None):
                    published = dt.datetime(*entry.published_parsed[:6], tzinfo=dt.timezone.utc)
                if not _recent(published):
                    continue
                out.append({
                    "title": title,
                    "source": source_name,
                    "link": entry.get("link"),
                    "published": published,
                })
    except Exception as e:
        logger.debug("RSS כללי (%s) נכשל: %s", source_name, e)
    return out


def _from_hebrew_general_feed_all(
    url: str, source_name: str, limit: int = 8, company_names: set[str] | None = None,
) -> list[dict]:
    """company_names: אם מסופק, מסנן רק כתבות שמזכירות אחת מהחברות ברשימה (למשל
    כל רכיבי ת"א 35/125) - כדי לא להציג חדשות כלכליות כלליות שלא נוגעות לאף
    מניה שאנחנו סורקים בפועל."""
    out = []
    try:
        feed = _parse_feed(url)
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if company_names is not None and not any(name in title or name in summary for name in company_names):
                continue
            published = None
            if getattr(entry, "published_parsed", None):
                published = dt.datetime(*entry.published_parsed[:6], tzinfo=dt.timezone.utc)
            out.append({
                "title": title,
                "source": source_name,
                "link": entry.get("link"),
                "published": published,
            })
            if len(out) >= limit:
                break
    except Exception as e:
        logger.debug("RSS כללי (%s) נכשל: %s", source_name, e)
    return out


def get_general_market_news(limit: int = 6, il_company_names: set[str] | None = None) -> list[dict]:
    """חדשות כלכליות כלליות (לא ספציפיות למניה) - למדד השוק הכללי (ארה"ב) ומגופי חדשות
    עבריים (ישראל). il_company_names: רשימת שמות חברות (בד"כ כל רכיבי ת"א 35/125) לסינון
    כתבות Globes/Calcalist - כך שרק כתבות שנוגעות בפועל למניה מהמדדים שלנו יוצגו. אם None,
    לא מסננים (מחזיר את כל הכתבות מה-RSS הכללי, כמו בעבר)."""
    headlines = _from_yfinance("^GSPC") \
        + _from_hebrew_general_feed_all(GLOBES_RSS, "Globes", company_names=il_company_names) \
        + _from_hebrew_general_feed_all(CALCALIST_RSS, "Calcalist", company_names=il_company_names)

    seen_titles = set()
    deduped = []
    for h in headlines:
        t = (h.get("title") or "").strip()
        if not t or t in seen_titles:
            continue
        seen_titles.add(t)
        deduped.append(h)

    deduped.sort(key=lambda h: h["published"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return deduped[:limit]


def get_recent_headlines(yahoo_symbol: str, is_israeli: bool, company_name: str | None = None) -> list[dict]:
    """אוסף כותרות אחרונות (עד MAX_AGE_DAYS ימים) עבור מניה, ממספר מקורות מוסמכים.
    מחזיר רשימת dict: title, source, link, published (עד MAX_HEADLINES פריטים, ללא כפילויות).
    """
    headlines = []
    headlines += _from_yfinance(yahoo_symbol)

    base_symbol = yahoo_symbol.replace(".TA", "")
    if is_israeli:
        headlines += _from_hebrew_general_feed(GLOBES_RSS, company_name, "Globes")
        headlines += _from_hebrew_general_feed(CALCALIST_RSS, company_name, "Calcalist")
    else:
        headlines += _from_symbol_rss(SEEKING_ALPHA_RSS, base_symbol, "Seeking Alpha")
        headlines += _from_symbol_rss(NASDAQ_RSS, base_symbol, "Nasdaq")

    seen_titles = set()
    deduped = []
    for h in headlines:
        t = (h.get("title") or "").strip()
        if not t or t in seen_titles:
            continue
        seen_titles.add(t)
        deduped.append(h)

    deduped.sort(key=lambda h: h["published"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return deduped[:MAX_HEADLINES]
