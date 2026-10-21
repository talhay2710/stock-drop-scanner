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
