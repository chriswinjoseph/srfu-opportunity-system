@echo off
rem Double-click to see whether the SRFU website and background service are running.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start-demo.ps1" -Status
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
