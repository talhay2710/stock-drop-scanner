' בודק אם הדשבורד המקומי (פורט 8501) עונה, ואם לא - מפעיל אותו מחדש בשקט.
' בניגוד ל-run_dashboard_silent.vbs (שגם פותח דפדפן בסוף - מיועד ללחיצה
' ידנית על קיצור הדרך), זה לא פותח שום דבר - רץ ברקע כל כמה דקות דרך
' Task Scheduler (ר' setup_task_scheduler_dashboard_watchdog.ps1) כדי
' שהדשבורד "יחזור לחיים" לבד אחרי קריסה, בלי שתצטרך לשים לב ולהפעיל ידנית.
Dim WshShell, Http, isUp

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\talha\Desktop\claude\stock-drop-scanner"

isUp = False
On Error Resume Next
Set Http = CreateObject("WinHttp.WinHttpRequest.5.1")
Http.Open "GET", "http://localhost:8501/_stcore/health", False
Http.SetTimeouts 2000, 2000, 2000, 2000
Http.Send
If Err.Number = 0 And Http.Status = 200 Then
    isUp = True
End If
On Error Goto 0

If Not isUp Then
    WshShell.Run "cmd /c git pull --quiet", 0, True
    WshShell.Run """C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe"" -m streamlit run dashboard.py --server.port 8501 --server.headless true", 0, False
End If
