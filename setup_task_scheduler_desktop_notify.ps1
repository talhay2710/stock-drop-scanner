# Registers a Windows Task Scheduler job that runs desktop_notify_watcher.py
# every 5 minutes - checks alerts.db (after a safe git pull) for anything new
# since the last run, and shows a Windows toast for each. Replaces the desktop
# notifications that stopped working after scanning moved to cloud-only
# (scanner.py now runs on a Linux GitHub Actions runner - winotify is
# Windows-only, so it silently failed there). 14.9.2026.
#
# pythonw.exe (not python.exe) - so no console window pops up every 5 minutes
# (see setup_task_scheduler_dashboard_watchdog.ps1, same reasoning).
#
# Run once from PowerShell (no admin rights required):
#   powershell -ExecutionPolicy Bypass -File setup_task_scheduler_desktop_notify.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$PythonExe = "C:\Users\talha\AppData\Local\Programs\Python\Python312\pythonw.exe"
$TaskName = "StockDesktopNotifyWatcher"
$ScriptPath = Join-Path $ProjectDir "desktop_notify_watcher.py"

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Checks every 5 min for new alerts/summaries and shows a Windows toast" -Force

Write-Host "Task '$TaskName' registered successfully in Task Scheduler."
Write-Host "View/edit via: taskschd.msc"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
