# Registers a Windows Task Scheduler job that runs run_weekly_report.py once a week
# on Fridays at 15:00 (after TASE's shortened Friday close), sending one Telegram
# digest of win-rate by drop reason over the past week.
# Run this once from PowerShell (no admin rights required):
#   powershell -ExecutionPolicy Bypass -File setup_task_scheduler_weekly_report.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$KnownPython = "C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe"
if (Test-Path $KnownPython) {
    $PythonExe = $KnownPython
} else {
    $PythonExe = (Get-Command python).Source
}
$ScriptPath = Join-Path $ProjectDir "run_weekly_report.py"
$TaskName = "StockWeeklyReport"

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "15:00"
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock drop scanner - weekly strategy report every Friday at 15:00" -Force

Write-Host "Task '$TaskName' registered successfully in Task Scheduler."
Write-Host "View/edit it via: taskschd.msc"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
