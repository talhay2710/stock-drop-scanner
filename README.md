# סורק ירידות מניות + אסטרטגיית ריבאונד

כלי מקומי (Python) שסורק מדד אחד או כמה בו-זמנית (ת"א 35 / ת"א 125 / NASDAQ-100 / S&P 500),
מאתר מניות שירדו מעבר לסף שהגדרת, ומנתח כל ירידה: סיבה משוערת, חדשות רלוונטיות,
הערכת "תגובת יתר", הצעת שער כניסה/יעד מכירה/סטופ-לוס, ותמונת ברוטו/נטו (עמלות,
מס רווח הון, דמי ניהול) לפי הכללים שהגדרת עבור ישראל/ארה"ב.

**⚠ חשוב:** זהו כלי סינון וניתוח אוטומטי מבוסס היוריסטיקות ונתונים חינמיים
(Yahoo Finance, RSS של גופי חדשות). זה **לא ייעוץ השקעות**, לא תחליף לקריאת
דוחות/חדשות בפועל, ואינו מבטיח דיוק. כל הצעה יש לבדוק בעצמך לפני קבלת החלטה.
נתוני Yahoo Finance עשויים להיות מושהים (15-20 דקות), במיוחד עבור ת"א.

## התקנה

```bash
cd stock-drop-scanner
pip install -r requirements.txt
```

## הגדרת טלגרם (להתראות)

1. פתח שיחה עם [@BotFather](https://t.me/BotFather) בטלגרם, שלח `/newbot` ועקוב אחר ההוראות - תקבל **bot token**.
2. שלח הודעה כלשהי לבוט החדש שיצרת.
3. גלוש לכתובת `https://api.telegram.org/bot<TOKEN>/getUpdates` (הצב את הטוקן שקיבלת) ומצא את `chat.id` בתשובה - זה ה-**chat_id** שלך.
4. פתח את `config.yaml` והכנס את שניהם תחת `telegram.bot_token` ו-`telegram.chat_id`.

## עריכת ההגדרות (config.yaml)

- `indices`: רשימה של אחד או יותר מתוך `SP500` / `NASDAQ100` / `TA35` / `TA125` (כל מדד נבדק בנפרד מול שעות המסחר שלו)
- `drop_threshold_pct`: סף הירידה שמפעיל התראה (למשל 5.0)
- `scan_interval_minutes`: תדירות סריקה בהרצה רציפה
- `position_size`: גודל פוזיציה משוער (בש"ח/בדולר) לצורך חישוב עמלות/מס/נטו
- `fees`: עמלות, מס רווח הון ודמי ניהול - כבר מוגדרים לפי הפרמטרים שנתת

## הרצה - שתי אפשרויות (אפשר גם את שתיהן יחד)

### 1. משימה מתוזמנת (Windows Task Scheduler) - רץ ברקע, לא דורש חלון פתוח

```powershell
powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1
```

זה ירשום משימה שמריצה `run_scan_once.py` כל 5 דקות (הסריקה מדלגת אוטומטית על כל
מדד שהשוק שלו סגור באותו רגע). להסרה:
```powershell
Unregister-ScheduledTask -TaskName "StockDropScanner" -Confirm:$false
```

לחלופין, להרצה רציפה בחלון פתוח (במקום Task Scheduler):
```bash
python run_continuous.py
```

### 2. דשבורד לצפייה חיה

```bash
streamlit run dashboard.py
```

יפתח בדפדפן בכתובת `http://localhost:8501`. מציג את כל ההתראות (היום/היסטוריה),
כולל הסיבה, החדשות, האסטרטגיה, ותמונת ברוטו/נטו. יש גם כפתור "הרץ סריקה עכשיו"
ובחירה מרובה של מדדים + סף ישירות מהממשק (Multiselect בסיידבר).

## מקורות הנתונים (רכיבי המדד)

- **NASDAQ100**: ה-API הרשמי של Nasdaq (`api.nasdaq.com`) - חי, ישירות מהבורסה
- **SP500**: [stockanalysis.com](https://stockanalysis.com/list/sp-500-stocks/) - אתר נתונים פיננסיים, חי (אין מקור חינמי "רשמי" ל-S&P 500 כי ההרכב הוא קניין של S&P Dow Jones Indices)
- **TA35 / TA125**: קובץ מקומי מאומת (`data/ta35_constituents.csv`, `ta125_constituents.csv`). אתר הבורסה הישראלית מוגן ע"י הגנת בוטים (Incapsula) שחוסמת גישה תכנותית - לא עוקפים הגנות כאלה, ולכן נעשה שימוש בקובץ שאומת ידנית מול Yahoo Finance ויש לעדכנו מדי רבעון מול [אתר הבורסה](https://www.tase.co.il)

## מבנה הפרויקט

```
config.yaml              - כל ההגדרות
data/ta35_constituents.csv, ta125_constituents.csv  - רשימות מניות ת"א (יש לעדכן מדי פעם מול אתר הבורסה)
src/constituents.py      - שליפת רכיבי המדד (Nasdaq API / stockanalysis.com / CSV מקומי לת"א)
src/market_data.py       - נתוני מחיר, תנודתיות, RSI (Yahoo Finance)
src/news.py              - חדשות מ-RSS מוסמכים + Yahoo Finance
src/analysis.py          - סיווג סיבת הירידה + הערכת תגובת יתר
src/strategy.py          - הצעת לימיט כניסה / יעדי מכירה / סטופ-לוס
src/fees.py              - חישוב עמלות/מס/דמי ניהול, ברוטו מול נטו
src/notifier.py          - שליחת התראות (טלגרם + Windows toast)
src/store.py             - שמירת התראות ב-SQLite (alerts.db) + דדופ יומי
src/scanner.py           - מחבר הכל לסבב סריקה אחד
src/backtest.py          - בדיקה לאחור: האם המלצות עבר הצליחו בפועל
src/daily_summary.py     - סיכום יומי (הודעת טלגרם אחת עם מצב כל התראות היום)
run_scan_once.py         - סבב בודד (ל-Task Scheduler)
run_continuous.py        - לולאה רציפה
run_daily_summary.py     - שליחת סיכום יומי (ל-Task Scheduler, פעם ביום)
dashboard.py             - דשבורד Streamlit
```

## עדכון רשימת מניות ת"א

`data/ta35_constituents.csv` ו-`data/ta125_constituents.csv` הם קבצי זרע (seed)
שיש לוודא/לעדכן מול [אתר הבורסה לניירות ערך](https://www.tase.co.il) מדי רבעון,
כי הרכב המדדים משתנה. ניתן לערוך את הקובץ ישירות (עמודות: `symbol,name,yahoo_ticker`).

## הרחבות אפשריות בהמשך

- ניתוח סיבת ירידה בעזרת Claude API (LLM קורא את הכותרות וכותב ניתוח וסיכום בשפה חופשית) - נדרש מפתח Anthropic API בתשלום לפי שימוש.
- שדרוג מקורות מחיר לספק בתשלום (Polygon/IEX/Twelve Data) לנתונים בזמן אמת ולא מושהים.
