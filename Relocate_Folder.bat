@echo off
echo Starting relocation script...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0relocate_project_folder.ps1"
echo.
echo (exit code %ERRORLEVEL%)
pause
