' בודק אם הדשבורד המקומי (פורט 8501) עונה, ואם לא - מפעיל אותו מחדש בשקט.
' בניגוד ל-run_dashboard_silent.vbs (שגם פותח דפדפן בסוף - מיועד ללחיצה
' ידנית על קיצור הדרך), זה לא פותח שום דבר - רץ ברקע כל כמה דקות דרך
' Task Scheduler (ר' setup_task_scheduler_dashboard_watchdog.ps1) כדי
' שהדשבורד "יחזור לחיים" לבד אחרי קריסה, בלי שתצטרך לשים לב ולהפעיל ידנית.
'
' חשוב: לא מפעיל את streamlit ישירות כאן (WshShell.Run עם waitOnReturn=False) -
' נבדק בפועל (23.8.2026) שתהליך-נכד שמופעל ככה מת יחד עם ה-task הזה ברגע
' שהוא מסתיים (Windows Task Scheduler מריץ כל task בתוך Job Object שהורג את
' כל מה שהוא הפעיל כשהתהליך הראשי יוצא) - גם כש-LastTaskResult=0 (הצלחה),
' streamlit פשוט לא שרד בפועל. הפתרון: מפעילים task נפרד (StockDashboardLauncher,
' ללא טריגר עצמאי משלו) שה-Job שלו בלתי-תלוי בזה של ה-watchdog.
Dim WshShell, Http, isUp

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\talha\Desktop\claude\stock-drop-scanner"

isUp = False
On Error Resume Next
Set Http = CreateObject("WinHttp.WinHttpRequest.5.1")
Http.Open "GET", "http://localhost:8501/_stcore/health", False
Http.SetTimeouts 2000, 2000, 2000, 2000
Http.Send
' VBScript לא מקצר-מעגל את And - "Err.Number = 0 And Http.Status = 200" תמיד
' מנסה לקרוא גם את Http.Status, גם כש-Send כבר נכשל (השרת לא זמין). קריאת
' Status אחרי Send כושל זורקת שגיאה נוספת משלה ("הנתונים עוד לא זמינים"),
' ונבדק בפועל (23.8.2026) שזה גורם ל-isUp להיקבע True בטעות - כלומר הבדיקה
' "חשבה" שהדשבורד למעלה בדיוק כשהוא היה למטה, ומעולם לא הגיעה לענף ההפעלה
' מחדש. If מקונן נמנע מהגישה ל-Status כשה-Send כבר נכשל.
If Err.Number = 0 Then
    If Http.Status = 200 Then
        isUp = True
    End If
End If
On Error Goto 0

If Not isUp Then
    WshShell.Run "cmd /c git pull --quiet", 0, True
    WshShell.Run "schtasks /run /tn ""StockDashboardLauncher""", 0, True
End If
