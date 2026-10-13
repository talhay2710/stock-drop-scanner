"""אימות עתידי עיוור של הניקוד (8.10.2026).

הרעיון: הניקוד והמשקלים הוקפאו ב-FREEZE_DATE. כל התראה מאותו תאריך ואילך היא מדגם בדיקה חדש לגמרי - שום משקל לא
נקבע לפיו. הסקריפט מדפיס דוח (Markdown) עם:
  1. ביצועי הניקוד המוקפא על המדגם העיוור (AUC, הצלחה ותשואה לפי קבוצה, טווחי סמך לפי ימים שלמים, נטו אחרי עמלות),
     בהשוואה לתקופת הפיתוח.
  2. לכל וקטור מועמד (alert_features ועוד): האם הוא משפר את הניקוד *במדגם העיוור*, בכיוון שנמדד בפיתוח, עם טווח סמך.
  3. החלטה: וקטור נכנס לניקוד רק אם הוא עובר את כל הקריטריונים (ר' CRITERIA למטה).
מדי שבוע ב-.github/workflows/strategy_validation.yml (הדוח בסיכום הריצה). הרצה מקומית: python validate_strategy.py
"""
import datetime as dt
import sys

import numpy as np
import pandas as pd

from src import post_alert, store, strategy as st, strategy_stats as ss
from src.config import db_path, load_config
from src.forward_test import FREEZE_DATE, MIN_BLIND_DAYS, load_merged, load_evaluated, position_size
CRITERIA = ("כיוון זהה לפיתוח", "שיפור AUC במדגם העיוור", "טווח סמך (לפי ימים) של ההפרש לא כולל 0")
ISRAELI = ("TA35", "TA125")


def _auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    return float(np.mean(pos[:, None] > neg[None, :]) + 0.5 * np.mean(pos[:, None] == neg[None, :]))


def load(conn, target: float = None) -> pd.DataFrame:
    ev = load_evaluated(conn, target)
    try:
        feats = pd.read_sql_query("SELECT * FROM alert_features", conn)
        ev = ev.merge(feats, left_on="id", right_on="alert_id", how="left", suffixes=("", "_f"))
    except Exception:
        pass
    return ev


def candidates(df: pd.DataFrame) -> dict:
    txt = (df["reason_text"].fillna("") + " " + df["reasons_json"].fillna(""))
    out = {
        "ירידה עודפת מעבר למדד (4%+)": df["residual_drop_pct"] <= -4,
        "יום חלש בשוק (סיבת הירידה)": txt.str.contains("יום חלש בשוק"),
        "לחץ סקטוריאלי (סיבת הירידה)": txt.str.contains("סקטוריאלי"),
        "המחיר עלה מהשפל (12%+)": df["intraday_recovery_pct"] >= 12,
    }
    for col, label, fn in (
        ("dd_5d", "נפילה 5%+ מהשיא של 5 ימים", lambda s: s <= -5),
        ("atr_norm_drop", "ירידה גדולה ביחס לתנודתיות (2+ ATR)", lambda s: s >= 2),
        ("dollar_vol", "נזילות גבוהה (מעל החציון)", lambda s: s >= s.median()),
        ("down_streak", "2+ ימי ירידה רצופים", lambda s: s >= 2),
        ("gap_open_pct", "פער פתיחה שלילי (מתחת ל-1%-)", lambda s: s < -1),
        ("ret_20d", "עלייה של 5%+ ב-20 הימים שלפני", lambda s: s > 5),
    ):
        if col in df.columns:
            series = pd.to_numeric(df[col], errors="coerce")
            out[label] = fn(series) & series.notna()
    return {k: v.fillna(False).astype(int) for k, v in out.items()}


def uplift_log_odds(y, f):
    a, b = y[f == 1], y[f == 0]
    if len(a) < 8 or len(b) < 8:
        return float("nan")
    lo = lambda p: np.log(min(max(p, 0.02), 0.98) / (1 - min(max(p, 0.02), 0.98)))
    return lo((a.sum() + 1) / (len(a) + 2)) - lo((b.sum() + 1) / (len(b) + 2))


def bootstrap_diff(df, fcol, B=1000):
    """טווח 95% (לפי ימים) להפרש AUC בין ניקוד+וקטור לניקוד בלבד."""
    by_day = {k: g for k, g in df.groupby("scan_date")}
    keys = np.array(list(by_day))
    rng = np.random.default_rng(5)
    diffs = []
    for _ in range(B):
        g = pd.concat([by_day[k] for k in rng.choice(keys, size=len(keys), replace=True)])
        diffs.append(_auc(g["y"], g["score"] + g[fcol]) - _auc(g["y"], g["score"]))
    return float(np.nanpercentile(diffs, 2.5)), float(np.nanpercentile(diffs, 97.5))


def main() -> int:
    cfg = load_config()
    conn = store.get_conn(db_path(cfg))
    df = load(conn)
    dev, blind = df[df["scan_date"] < FREEZE_DATE], df[df["scan_date"] >= FREEZE_DATE]
    print(f"# אימות עתידי של הניקוד - {dt.date.today().isoformat()}\n")
    print(f"תאריך הקפאה: {FREEZE_DATE}. פיתוח: {len(dev)} התראות ב-{dev['scan_date'].nunique()} ימים. "
          f"מדגם עיוור: {len(blind)} התראות ב-{blind['scan_date'].nunique()} ימים (נדרשים {MIN_BLIND_DAYS} לפחות להחלטה).\n")
    pos = position_size(cfg)
    for name, part in (("תקופת הפיתוח (להשוואה)", dev), ("מדגם עיוור", blind)):
        print(f"## {name}")
        if len(part) < 20 or part["scan_date"].nunique() < 5:
            print("אין עדיין מספיק נתונים.\n")
            continue
        print(f"AUC: {_auc(part['y'], part['score']):.3f}\n")
        t = ss.bucket_summary(part, cfg["fees"], position=pos, B=600)
        print("| קבוצה | התראות | ימים | הצלחה | ברוטו | נטו |\n|---|---|---|---|---|---|")
        for _, r in t.iterrows():
            print(f"| {r['קבוצה']} | {r['התראות']} | {r['ימים']} | {r['הצלחה %']:.0f}% ({r['הצלחה CI'][0]:.0f}-{r['הצלחה CI'][1]:.0f}) | "
                  f"{r['ברוטו %']:+.2f}% ({r['ברוטו CI'][0]:+.2f} עד {r['ברוטו CI'][1]:+.2f}) | "
                  f"{r['נטו %']:+.2f}% ({r['נטו CI'][0]:+.2f} עד {r['נטו CI'][1]:+.2f}) |")
        print()
    # יעדים חלופיים (דוח בלבד - היעד בפרודקשן לא משתנה): האם יעד גבוה יותר מכסה טוב יותר את העמלה הקבועה?
    print("## יעד חלופי, קבוצת 4+ (מדגם עיוור, ברוטו / נטו)")
    print("| יעד | התראות | הצלחה | ברוטו | נטו (פוזיציה בהגדרות) | נטו (10,000) |\n|---|---|---|---|---|---|")
    for T in (3, 3.5, 5, 7):
        evT = load(conn, T)
        evT = evT[evT["scan_date"] >= FREEZE_DATE]
        buy = evT[evT["score"] >= 4]
        if len(buy) < 5:
            print(f"| {T}% | {len(buy)} | מעט נתונים | | | |")
            continue
        n_cfg = buy["ret"].map(lambda r: ss.net_return_pct(r, pos, cfg["fees"]))
        n_10k = buy["ret"].map(lambda r: ss.net_return_pct(r, 10000, cfg["fees"]))
        print(f"| {T}% | {len(buy)} | {buy['y'].mean()*100:.0f}% | {buy['ret'].mean():+.2f}% | {n_cfg.mean():+.2f}% | {n_10k.mean():+.2f}% |")
    print()
    # ירידה יומית מול ירידה מצטברת בלבד (היום עצמו מעל סף הירידה היומי) - הציון לא נבדק על מצטברות (13.10.2026)
    print("## ירידה יומית מול מצטברת בלבד (כל הציונים / 4+)")
    print("| סוג | מדגם | התראות | ימים | הצלחה | ברוטו | 4+: התראות | 4+: הצלחה | 4+: ברוטו |" + chr(10) + "|---|---|---|---|---|---|---|---|---|")
    _thr = abs(cfg["drop_threshold_pct"])
    for _name, _part in (("פיתוח", dev), ("עיוור", blind)):
        for _kind, _mask in (("יומית", _part["pct_change"] <= -_thr), ("מצטברת בלבד", _part["pct_change"] > -_thr)):
            _g = _part[_mask]
            if _g.empty:
                continue
            _b = _g[_g["score"] >= 4]
            _b_txt = (f"{len(_b)} | {_b['y'].mean()*100:.0f}% | {_b['ret'].mean():+.2f}%" if len(_b) >= 5
                      else f"{len(_b)} | - | -")
            print(f"| {_kind} | {_name} | {len(_g)} | {_g['scan_date'].nunique()} | {_g['y'].mean()*100:.0f}% | "
                  f"{_g['ret'].mean():+.2f}% | {_b_txt} |")
    print()
    decide = blind["scan_date"].nunique() >= MIN_BLIND_DAYS
    print("## וקטורים מועמדים (במדגם העיוור)")
    if len(blind) < 20:
        print("אין עדיין מדגם עיוור מספיק.\n")
        return 0
    cand_dev, cand_blind = candidates(dev), candidates(blind)
    print("| וקטור | התראות עם | הצלחה עם/בלי | uplift פיתוח | uplift עיוור | הפרש AUC (טווח) | החלטה |\n|---|---|---|---|---|---|---|")
    for k, f in cand_blind.items():
        if f.sum() < 10:
            continue
        ud, ub = uplift_log_odds(dev["y"].values, cand_dev[k].values), uplift_log_odds(blind["y"].values, f.values)
        b = blind.assign(_f=np.sign(ud if ud == ud else 0) * f.values)
        d_auc = _auc(b["y"], b["score"] + b["_f"]) - _auc(b["y"], b["score"])
        lo, hi = bootstrap_diff(b.rename(columns={"_f": "_f"}), "_f") if blind["scan_date"].nunique() >= 5 else (float("nan"),) * 2
        ok = (ud == ud and ub == ub and np.sign(ud) == np.sign(ub) and d_auc > 0 and lo > 0)
        verdict = ("✅ מועמד לכניסה" if ok else "❌ לא") if decide else "⏳ מוקדם מדי"
        print(f"| {k} | {int(f.sum())} | {blind['y'][f == 1].mean()*100:.0f}% / {blind['y'][f == 0].mean()*100:.0f}% | "
              f"{ud:+.2f} | {ub:+.2f} | {d_auc:+.3f} ({lo:+.3f} עד {hi:+.3f}) | {verdict} |")
    print("\nקריטריונים לכניסה: " + " · ".join(CRITERIA) + f" · ולפחות {MIN_BLIND_DAYS} ימים במדגם העיוור.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
