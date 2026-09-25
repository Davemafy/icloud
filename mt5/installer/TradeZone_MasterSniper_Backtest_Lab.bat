@echo off
setlocal
color 0B
title Trade Zone - Master Sniper Backtest Lab
echo ============================================================
echo  Trade Zone - Master Sniper Backtest Lab
echo  Integrated DEMO/PAPER historical replay workflow
echo  Live EAs are NOT replaced
echo ============================================================
echo.
set "PS1=%TEMP%\TradeZone_MasterSniper_Backtest_Lab.ps1"
set "URL=https://raw.githubusercontent.com/Davemafy/icloud/main/mt5/installer/TradeZone_MasterSniper_Backtest_Lab.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%PS1%'"
if errorlevel 1 (
 echo FAILED: Could not download the integrated backtest lab.
 pause
 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
del /q "%PS1%" >nul 2>&1
exit /b %RC%
