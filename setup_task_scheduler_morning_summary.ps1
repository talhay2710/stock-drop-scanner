# Registers a Windows Task Scheduler job that runs run_morning_summary.py once a day
# at 10:30 (~30 minutes after the TA market opens - Yahoo often hasn't published
# fresh intraday data yet in the first ~10-20 minutes), sending one Telegram snapshot of
# your holdings and the day's top movers.
# Run this once from PowerShell (no admin rights required):
#   powershell -ExecutionPolicy Bypass -File setup_task_scheduler_morning_summary.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$KnownPython = "C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe"
if (Test-Path $KnownPython) {
    $PythonExe = $KnownPython
} else {
    $PythonExe = (Get-Command python).Source
}
$ScriptPath = Join-Path $ProjectDir "run_morning_summary.py"
$TaskName = "StockMorningSummary"

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At "10:30"
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock drop scanner - morning Telegram snapshot at 10:30" -Force

Write-Host "Task '$TaskName' registered successfully in Task Scheduler."
Write-Host "View/edit it via: taskschd.msc"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
