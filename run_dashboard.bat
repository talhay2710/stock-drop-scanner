@echo off
cd /d %~dp0
echo בודק עדכונים...
git pull --quiet
echo מפעיל את הדשבורד...
echo אל תסגור את החלון הזה כל עוד אתה רוצה שהאתר יעבוד.
echo.
"C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe" -m streamlit run dashboard.py
pause
