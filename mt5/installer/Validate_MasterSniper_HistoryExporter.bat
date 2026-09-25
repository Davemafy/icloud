@echo off
setlocal
color 0B
title Trade Zone - Master Sniper History Exporter Compiler
echo ============================================================
echo  Trade Zone - Master Sniper History Exporter Compiler
echo  Validation only - no live EA is replaced
echo ============================================================
echo.
set "PS1=%TEMP%\TradeZone_Validate_MasterSniper_HistoryExporter.ps1"
set "URL=https://raw.githubusercontent.com/Davemafy/icloud/master-sniper-backtest-v659/mt5/installer/Validate_MasterSniper_HistoryExporter.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%PS1%'"
if errorlevel 1 (
 echo FAILED: Could not download the history exporter validator.
 pause
 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
del /q "%PS1%" >nul 2>&1
exit /b %RC%
