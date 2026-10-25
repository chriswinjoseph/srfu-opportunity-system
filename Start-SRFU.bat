@echo off
rem Double-click to start the SRFU website and its background scraper service.
rem Safe to run again: anything already running is detected and not started twice.
rem Starting the service lets it run any scrape that an Admin has already queued.
setlocal
cd /d "%~dp0"
echo Starting the SRFU website and background service...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start-demo.ps1" -OpenBrowser
set RC=%ERRORLEVEL%
echo.
if %RC% neq 0 (
    echo START-UP FAILED. Read the message above. More detail is in the logs folder.
) else (
    echo Started. You can close this window; the website and service keep running.
    echo To stop them, double-click Stop-SRFU.bat.
)
pause
exit /b %RC%
