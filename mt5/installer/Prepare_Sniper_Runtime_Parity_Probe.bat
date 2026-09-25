@echo off
setlocal
color 0B
title Trade Zone - Sniper Runtime Parity Probe
echo ============================================================
echo  Trade Zone - Master Sniper Runtime Parity Probe Installer
echo  NO TRADING - working EAs are NOT replaced
echo ============================================================
echo.
set "PS1=%TEMP%\TradeZone_Prepare_Sniper_Runtime_Probe.ps1"
set "URL=https://raw.githubusercontent.com/Davemafy/icloud/sniper-contract-parity-v1/mt5/installer/Prepare_Sniper_Runtime_Parity_Probe.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%PS1%'"
if errorlevel 1 (
 echo FAILED: Could not download the runtime probe installer.
 pause
 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
del /q "%PS1%" >nul 2>&1
exit /b %RC%
