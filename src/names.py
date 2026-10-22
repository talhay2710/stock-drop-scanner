"""תיקוני תצוגה לשמות חברות בעברית - מקום אחד לכל האתר."""
import re

_FIXES = [(re.compile(r"איביאי|אי בי אי|אי\.בי\.אי"), "אי.בי.אי")]


def fix_name(name):
    """מחזיר את שם החברה בכתיב התצוגה האחיד (למשל "אי.בי.אי"); ערכים שאינם טקסט חוזרים כמו שהם."""
    if not isinstance(name, str):
        return name
    for pat, rep in _FIXES:
        name = pat.sub(rep, name)
    return name


# סקטורים של Yahoo -> עברית (אותה טבלה כמו _SECTOR_LABELS_HE בדשבורד)
SECTOR_LABELS_HE = {
    "Technology": "טכנולוגיה",
    "Financial Services": "פיננסיים",
    "Financials": "פיננסים",
    "Healthcare": "בריאות",
    "Energy": "אנרגיה",
    "Consumer Cyclical": "צריכה מחזורית",
    "Consumer Defensive": "צריכה בסיסית",
    "Industrials": "תעשייה",
    "Basic Materials": "חומרי גלם",
    "Real Estate": 'נדל"ן',
    "Utilities": "תשתיות",
    "Communication Services": "תקשורת",
}


def sector_he(sector):
    """שם סקטור בעברית (או הערך המקורי אם אין תרגום)."""
    return SECTOR_LABELS_HE.get(sector, sector) if isinstance(sector, str) else sector
