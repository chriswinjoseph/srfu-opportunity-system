@echo off
rem Double-click to stop the SRFU website and background service started for this folder.
rem A scrape that is part-way through is kept and continues after the next start.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start-demo.ps1" -Stop
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
