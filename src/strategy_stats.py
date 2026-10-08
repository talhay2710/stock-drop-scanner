"""סטטיסטיקות ברמת יום עבור הניקוד (8.10.2026) - כי ההתראות באותו יום אינן עצמאיות: ביום של ירידה רחבה בשוק עשרות
התראות הן בעצם אירוע אחד. לכן רווחי הסמך כאן הם cluster bootstrap לפי ימים שלמים (דוגמים ימים עם חזרה, וכל ההתראות
של יום נשארות יחד), ו"נטו" כולל עמלות, דמי ניהול ומס לפי הגדרות המשתמש (src/fees.py).

הקלט: DataFrame עם scan_date, score (הניקוד), y (1=הגיע ליעד), ret (תשואה ברוטו באחוזים, יעד/סגירה ביום 3), pct_change.
"""
import numpy as np
import pandas as pd

from . import fees

BUCKETS = (("4+ לקנות", 4, 99), ("2-3 לחכות", 2, 3), ("0-1 לא לקנות", -99, 1))


def bucket_mask(df: pd.DataFrame, lo: int, hi: int) -> pd.Series:
    return (df["score"] >= lo) & (df["score"] <= hi)


def net_return_pct(gross_pct: float, position: float, fees_cfg: dict, country: str = "IL", holding_days: int = 3) -> float:
    """תשואה נטו באחוזים אחרי עמלות (כולל המינימום לצד), דמי ניהול ומס רווחי הון (מס רק על רווח, בלי קיזוז הפסדים)."""
    res = fees.compute_net_result(
        country_code=country, buy_price=1.0, sell_price=1.0 + gross_pct / 100.0,
        position_size_ccy=position, holding_days=holding_days, fees_cfg=fees_cfg,
    )
    return res.net_pnl / position * 100.0


def _days(df: pd.DataFrame) -> dict:
    return {k: g for k, g in df.groupby("scan_date")}


def day_bootstrap_ci(df: pd.DataFrame, stat, B: int = 1000, seed: int = 11) -> tuple[float, float]:
    """טווח 95% (אחוזונים 2.5 ו-97.5) של stat(df) כשדוגמים *ימים* עם חזרה."""
    by_day = _days(df)
    keys = np.array(list(by_day))
    if len(keys) < 3:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        pick = rng.choice(keys, size=len(keys), replace=True)
        out.append(stat(pd.concat([by_day[k] for k in pick])))
    out = np.array(out, float)
    return float(np.nanpercentile(out, 2.5)), float(np.nanpercentile(out, 97.5))


def bucket_summary(df: pd.DataFrame, fees_cfg: dict | None = None, position: float = 5000.0, B: int = 1000) -> pd.DataFrame:
    """שורה לכל קבוצת ניקוד: כמות התראות וימים, שיעור הצלחה, תשואה ברוטו ונטו - עם טווחי סמך לפי ימים."""
    rows = []
    for label, lo, hi in BUCKETS:
        sub = df[bucket_mask(df, lo, hi)]
        if sub.empty:
            continue

        def _win(g, lo=lo, hi=hi):
            m = bucket_mask(g, lo, hi)
            return g.loc[m, "y"].mean() * 100 if m.any() else np.nan

        def _gross(g, lo=lo, hi=hi):
            m = bucket_mask(g, lo, hi)
            return g.loc[m, "ret"].mean() if m.any() else np.nan

        row = {
            "קבוצה": label, "התראות": len(sub), "ימים": sub["scan_date"].nunique(),
            "הצלחה %": sub["y"].mean() * 100, "הצלחה CI": day_bootstrap_ci(df, _win, B),
            "ברוטו %": sub["ret"].mean(), "ברוטו CI": day_bootstrap_ci(df, _gross, B),
        }
        if fees_cfg:
            net = sub["ret"].map(lambda r: net_return_pct(r, position, fees_cfg))
            row["נטו %"] = float(net.mean())
            sub_net = df.assign(_net=df["ret"].map(lambda r: net_return_pct(r, position, fees_cfg)))

            def _netstat(g, lo=lo, hi=hi):
                m = bucket_mask(g, lo, hi)
                return g.loc[m, "_net"].mean() if m.any() else np.nan

            row["נטו CI"] = day_bootstrap_ci(sub_net, _netstat, B)
        rows.append(row)
    return pd.DataFrame(rows)


def topk_table(df: pd.DataFrame, ks=(1, 3, 5)) -> pd.DataFrame:
    """מה קורה אם ביום קונים רק את K ההתראות הטובות ביותר (לפי ניקוד, ובשוויון - ירידה גדולה יותר).
    לכל K: בלי סינון, ורק התראות עם ניקוד 4+ מתוכן."""
    groups = []
    for _, g in df.groupby("scan_date"):
        groups.append(g.sort_values(["score", "pct_change"], ascending=[False, True]))
    rows = []
    for k in ks:
        top = pd.concat([g.head(k) for g in groups])
        buy = pd.concat([g[g["score"] >= 4].head(k) for g in groups])
        rows.append({
            "K": k, "התראות": len(top), "הצלחה %": top["y"].mean() * 100, "ברוטו %": top["ret"].mean(),
            "רק 4+: התראות": len(buy),
            "רק 4+: הצלחה %": buy["y"].mean() * 100 if len(buy) else np.nan,
            "רק 4+: ברוטו %": buy["ret"].mean() if len(buy) else np.nan,
        })
    return pd.DataFrame(rows)


def per_day_buy_stats(df: pd.DataFrame) -> dict:
    """ימים עם 4+: כמה, ממוצע יומי, כמה ימים חיוביים, והיום הגרוע ביותר."""
    daily = pd.Series({k: g[g["score"] >= 4]["ret"].mean() for k, g in df.groupby("scan_date") if (g["score"] >= 4).any()})
    if daily.empty:
        return {"days_with_buy": 0}
    return {"days_with_buy": int(len(daily)), "total_days": int(df["scan_date"].nunique()),
            "avg_daily_ret": float(daily.mean()), "positive_days": int((daily > 0).sum()), "worst_day": float(daily.min())}
