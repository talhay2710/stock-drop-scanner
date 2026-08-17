# Registers a Windows Task Scheduler job that runs run_daily_summary.py once a day
# at 23:30 (after the US market closes), sending one Telegram digest of the day's alerts.
# Run this once from PowerShell (no admin rights required):
#   powershell -ExecutionPolicy Bypass -File setup_task_scheduler_daily_summary.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$KnownPython = "C:\Users\micha\AppData\Local\Programs\Python\Python312\python.exe"
if (Test-Path $KnownPython) {
    $PythonExe = $KnownPython
} else {
    $PythonExe = (Get-Command python).Source
}
$ScriptPath = Join-Path $ProjectDir "run_daily_summary.py"
$TaskName = "StockDailySummary"

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At "23:30"
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock drop scanner - daily Telegram summary at 23:30" -Force

Write-Host "Task '$TaskName' registered successfully in Task Scheduler."
Write-Host "View/edit it via: taskschd.msc"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
