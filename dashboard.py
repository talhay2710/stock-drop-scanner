"""נקודת הכניסה של Streamlit (streamlit run dashboard.py). הקוד האמיתי נמצא ב-dipradar_app.py.

למה קובץ נפרד: Streamlit שומר את הקוד המקומפל של קובץ הכניסה במטמון, ועם fileWatcherType="none" (נדרש בענן - ר' .streamlit/config.toml)
שום דבר לא מנקה אותו, כך שדחיפה חדשה לא התחילה לרוץ בלי Reboot ידני. קובץ הכניסה הזה קטן ויציב (כמעט לא משתנה), ובכל ריצה
הוא קורא מחדש מהדיסק את dipradar_app.py, ומוחק את מודולי src שבזיכרון אם קובץ קוד כלשהו השתנה - כך כל דחיפה נכנסת לתוקף בריצה הבאה.
"""
import hashlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _code_signature() -> str:
    parts = []
    for folder in (_HERE, os.path.join(_HERE, "src")):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if name.endswith((".py", ".yaml", ".csv", ".toml")) and name != "alerts.db":
                path = os.path.join(folder, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                parts.append(f"{name}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:10]


_sig = _code_signature()
if getattr(sys, "_dipradar_code_sig", None) != _sig:
    for _name in [n for n in list(sys.modules) if n == "src" or n.startswith("src.")]:
        del sys.modules[_name]
    sys._dipradar_code_sig = _sig
_DIPRADAR_BUILD = _sig

_APP_PATH = os.path.join(_HERE, "dipradar_app.py")
with open(_APP_PATH, "r", encoding="utf-8") as _f:
    _code = compile(_f.read(), _APP_PATH, "exec")
exec(_code, globals())
