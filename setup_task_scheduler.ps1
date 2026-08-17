# Registers a Windows Task Scheduler job that runs one scan pass every 5 minutes,
# 24/7 (the script itself checks market hours and skips when the market is closed).
# Run this once from PowerShell (no admin rights required):
#   powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$KnownPython = "C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe"
if (Test-Path $KnownPython) {
    $PythonExe = $KnownPython
} else {
    $PythonExe = (Get-Command python).Source
}
$ScriptPath = Join-Path $ProjectDir "run_scan_once.py"
$TaskName = "StockDropScanner"

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock drop scanner - runs every 5 minutes" -Force

Write-Host "Task '$TaskName' registered successfully in Task Scheduler."
Write-Host "View/edit it via: taskschd.msc"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
