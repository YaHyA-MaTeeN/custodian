@echo off
REM Starts both halves of Custodian and opens the browser.
REM The web app runs on 3001 because 3000 is used by another project.
REM Close either window to stop that half.

start "Custodian API" cmd /k "cd /d %~dp0poc && python api.py"
start "Custodian Web" cmd /k "cd /d %~dp0web && npm run dev -- -p 3001"

echo Waiting for both to come up...
timeout /t 8 /nobreak >nul
start http://localhost:3001
exit
