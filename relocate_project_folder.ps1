# מעביר את כל תיקיית הפרויקט מ-Desktop\claude ל-C:\Users\talha\claude, ומתקן
# את כל המקומות שמכילים את הנתיב הישן: 7 משימות מתוזמנות, קיצור הדרך בדסקטופ,
# ושני קבצי .vbs עם נתיב קבוע מוטבע בפנים (run_dashboard_silent.vbs,
# watchdog_dashboard.vbs).
#
# הרצה: קליק כפול על קיצור הדרך "העברת תיקייה" בדסקטופ. קיצור הדרך עצמו
# מסומן "Run as administrator" (בית הדגל ב-.lnk, לא הרצה-עצמית מתוך הסקריפט) -
# UAC יופיע לפני שהסקריפט בכלל מתחיל לרוץ.
#
# לפני שמריצים: לסגור את Claude Code לגמרי (לא רק את החלון - גם ממגש המערכת),
# כי הסשן הזה רץ מתוך התיקייה שהסקריפט מזיז.
#
# 22.9.2026: שני תיקונים לבאג "חלון שחור נסגר אחרי שנייה בלי הודעה":
# (1) הניסיון הראשון (try/catch/Read-Host) לא פתר את זה - כנראה כי
# Start-Process -Verb RunAs לא תמיד זורק חריגה כשה-UAC נדחה/נכשל, אז ה-catch
# פשוט לא הופעל וה-exit קרה מיד בשקט. (2) הפתרון האמיתי: קיצור הדרך עצמו
# מסומן כעת "Run as administrator" ישירות (לא בקשת הרשאה עצמית מתוך
# PowerShell), ו-Relocate_Folder.bat מוסיף "pause" ברמת ה-batch כרשת ביטחון
# נוספת שתמיד תשאיר את החלון פתוח, לא משנה מה קורה בפנים.

# רושם תמיד לקובץ log בנוסף למסך - כי גיליתי בפועל (22.9.2026) שהחלון נסגר
# לפני שהספקתי לקרוא מה כתוב בו, פעמיים. ככה יש תיעוד קבוע של מה שקרה, לא
# תלוי אם החלון נסגר מהר מדי או שמישהו לוחץ Enter בטעות לפני שרואים.
$LogPath = "$env:TEMP\relocate_project_folder_log.txt"
Start-Transcript -Path $LogPath -Append | Out-Null

Write-Host "=== סקריפט העברת תיקיית הפרויקט ==="
Write-Host "(לוג מלא גם נשמר ב-$LogPath)"
Write-Host ""

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "השגיאה: הסקריפט לא רץ בהרשאות מנהל." -ForegroundColor Red
    Write-Host "קיצור הדרך 'העברת תיקייה' בדסקטופ אמור לבקש הרשאות אוטומטית (UAC)." -ForegroundColor Red
    Write-Host "אם הרצת את הקובץ הזה ישירות (לא דרך קיצור הדרך) - קליק ימני -> Run as administrator." -ForegroundColor Red
    Stop-Transcript | Out-Null
    Read-Host "לחץ Enter לסגירה"
    exit
}

$ErrorActionPreference = "Stop"
try {
    $OldRoot = "C:\Users\talha\Desktop\claude"
    $NewRoot = "C:\Users\talha\claude"
    $OldProjectPath = "$OldRoot\stock-drop-scanner"
    $NewProjectPath = "$NewRoot\stock-drop-scanner"

    $TaskNames = @(
        "StockDropScanner", "StockDailySummary", "StockMorningSummary", "StockWeeklyReport",
        "StockDashboardLauncher", "StockDashboardWatchdog", "StockDesktopNotifyWatcher"
    )

    Write-Host "רץ עם הרשאות מנהל. מתחיל..."
    Write-Host ""

    Write-Host "=== שלב 1: עצירת משימות פעילות (כדי לשחרר נעילות קבצים) ==="
    foreach ($name in $TaskNames) {
        try {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        } catch {}
    }
    # הדשבורד עצמו רץ כתהליך pythonw.exe עצמאי (לא נעצר ע"י Stop-ScheduledTask
    # אם כבר רץ) - סוגרים אותו במפורש כדי שלא יחזיק נעילת קובץ על alerts.db וכו'.
    Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object {
        (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*stock-drop-scanner*"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "  בוצע."

    Write-Host "=== שלב 2: העברת התיקייה ==="
    if (Test-Path $NewRoot) {
        throw "התיקייה $NewRoot כבר קיימת - עוצר כדי לא לדרוס משהו. בדוק ידנית לפני שמריצים שוב."
    }
    if (-not (Test-Path $OldRoot)) {
        throw "התיקייה $OldRoot לא נמצאה - אולי כבר הועברה בעבר?"
    }
    Move-Item -Path $OldRoot -Destination $NewRoot
    Write-Host "  הועבר: $OldRoot -> $NewRoot"

    Write-Host "=== שלב 3: תיקון 7 המשימות המתוזמנות ==="
    foreach ($name in $TaskNames) {
        try {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
            $action = $task.Actions[0]
            $newArgs = $action.Arguments -replace [regex]::Escape($OldProjectPath), $NewProjectPath
            $newWorkDir = $action.WorkingDirectory -replace [regex]::Escape($OldProjectPath), $NewProjectPath
            $newAction = New-ScheduledTaskAction -Execute $action.Execute -Argument $newArgs -WorkingDirectory $newWorkDir
            Set-ScheduledTask -TaskName $name -Action $newAction | Out-Null
            Write-Host "  תוקן: $name"
        } catch {
            Write-Warning "  לא נמצאה/נכשלה: $name ($_)"
        }
    }

    Write-Host "=== שלב 4: תיקון קיצור הדרך בדסקטופ ==="
    $ShortcutPath = "C:\Users\talha\Desktop\סורק.lnk"
    if (Test-Path $ShortcutPath) {
        $wsh = New-Object -ComObject WScript.Shell
        $lnk = $wsh.CreateShortcut($ShortcutPath)
        $lnk.TargetPath = $lnk.TargetPath -replace [regex]::Escape($OldProjectPath), $NewProjectPath
        $lnk.WorkingDirectory = $lnk.WorkingDirectory -replace [regex]::Escape($OldProjectPath), $NewProjectPath
        $lnk.IconLocation = $lnk.IconLocation -replace [regex]::Escape($OldProjectPath), $NewProjectPath
        $lnk.Save()
        Write-Host "  תוקן: $ShortcutPath"
    } else {
        Write-Warning "  קיצור הדרך לא נמצא בנתיב הצפוי: $ShortcutPath"
    }

    Write-Host "=== שלב 5: תיקון נתיב קבוע בתוך קבצי VBS ==="
    foreach ($vbsName in @("run_dashboard_silent.vbs", "watchdog_dashboard.vbs")) {
        $vbsPath = Join-Path $NewProjectPath $vbsName
        if (Test-Path $vbsPath) {
            (Get-Content $vbsPath -Raw) -replace [regex]::Escape($OldProjectPath), $NewProjectPath |
                Set-Content $vbsPath -NoNewline
            Write-Host "  תוקן: $vbsName"
        }
    }

    Write-Host "=== שלב 6: הפעלה מחדש של המשימות ==="
    foreach ($name in $TaskNames) {
        try {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
            if ($task.State -ne "Disabled") {
                Start-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            }
        } catch {}
    }

    Write-Host ""
    Write-Host "=== הצלחה ===" -ForegroundColor Green
    Write-Host "התיקייה עברה ל-$NewRoot, כל המשימות/קיצור הדרך/קבצי ה-VBS תוקנו."
    Write-Host "פתח את Claude Code מחדש, מכוון ל-$NewRoot\.claude"
} catch {
    Write-Host ""
    Write-Host "=== שגיאה - העברה לא הושלמה ===" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host $_.ScriptStackTrace
} finally {
    Write-Host ""
    Stop-Transcript | Out-Null
    Read-Host "לחץ Enter לסגירה"
}
