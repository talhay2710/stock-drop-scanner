# Registers TWO Windows Task Scheduler jobs for the local dashboard watchdog:
#
# 1. StockDashboardLauncher - no trigger of its own (only ever started on-demand via
#    `schtasks /run`). Its Action directly launches streamlit. Runs in its OWN job
#    object, independent of whoever triggered it.
# 2. StockDashboardWatchdog - the actual 5-minute timer. Checks port 8501; if it's
#    down, runs `schtasks /run /tn StockDashboardLauncher` and exits.
#
# Why two tasks instead of one that just launches streamlit directly: verified live
# (2026-08-23) that Windows Task Scheduler runs a task's action inside a Job Object,
# and when that action process exits, Windows kills every process it spawned -
# including a "fire and forget" WshShell.Run(..., False) grandchild. A single-task
# version looked like it worked (LastTaskResult 0 every 5 min) but the streamlit
# process it launched never actually survived past the watchdog script's own exit -
# confirmed empirically: killed the dashboard, watched the watchdog fire ~24 times
# over 2 hours with LastTaskResult=0 each time, and the dashboard stayed dead the
# whole time. Splitting into two tasks means the launcher's job is independent of
# the watchdog's job, so the streamlit process it starts survives.
#
# Run this once from PowerShell (no admin rights required):
#   powershell -ExecutionPolicy Bypass -File setup_task_scheduler_dashboard_watchdog.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$PythonExe = "C:\Users\talha\AppData\Local\Programs\Python\Python312\python.exe"
$LauncherTaskName = "StockDashboardLauncher"
$WatchdogTaskName = "StockDashboardWatchdog"
$WatchdogScriptPath = Join-Path $ProjectDir "watchdog_dashboard.vbs"

$LauncherAction = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m streamlit run dashboard.py --server.port 8501 --server.headless true" -WorkingDirectory $ProjectDir
$LauncherSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName $LauncherTaskName -Action $LauncherAction -Settings $LauncherSettings -Description "Launches the dashboard directly - only ever triggered on-demand by StockDashboardWatchdog, never on its own schedule" -Force

$WatchdogAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$WatchdogScriptPath`"" -WorkingDirectory $ProjectDir
$WatchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$WatchdogSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -DontStopOnIdleEnd
Register-ScheduledTask -TaskName $WatchdogTaskName -Action $WatchdogAction -Trigger $WatchdogTrigger -Settings $WatchdogSettings -Description "Local dashboard watchdog - relaunches it if it's not responding" -Force

Write-Host "Tasks '$LauncherTaskName' and '$WatchdogTaskName' registered successfully in Task Scheduler."
Write-Host "View/edit them via: taskschd.msc"
Write-Host "To remove both: Unregister-ScheduledTask -TaskName '$LauncherTaskName','$WatchdogTaskName' -Confirm:`$false"
