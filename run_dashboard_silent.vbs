Dim WshShell, Http, isUp, i

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\talha\Desktop\claude\stock-drop-scanner"

isUp = False
On Error Resume Next
Set Http = CreateObject("WinHttp.WinHttpRequest.5.1")
Http.Open "GET", "http://localhost:8501/_stcore/health", False
Http.SetTimeouts 1500, 1500, 1500, 1500
Http.Send
If Err.Number = 0 And Http.Status = 200 Then
    isUp = True
End If
On Error Goto 0

If Not isUp Then
    WshShell.Run """C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe"" -m streamlit run dashboard.py --server.port 8501 --server.headless true", 0, False
    ' ממתינים שהשרת יעלה בפועל לפני שפותחים דפדפן, במקום להניח שזה מיידי -
    ' לפעמים לוקח יותר מ-10 שניות (עומס במחשב), אז 30 שניות למקרה כזה
    For i = 1 To 30
        WScript.Sleep 1000
        On Error Resume Next
        Err.Clear
        Http.Open "GET", "http://localhost:8501/_stcore/health", False
        Http.SetTimeouts 1000, 1000, 1000, 1000
        Http.Send
        If Err.Number = 0 And Http.Status = 200 Then
            isUp = True
        End If
        On Error Goto 0
        If isUp Then Exit For
    Next
End If

WshShell.Run "http://localhost:8501", 1, False
