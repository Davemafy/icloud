@echo off
setlocal
color 0B
title Trade Zone - Sniper Parity Validator

echo ============================================================
echo  Trade Zone - Sniper Parity Validator
echo  Validation only - stable EAs will NOT be replaced
echo ============================================================
echo.

set "PS1=%TEMP%\TradeZone_Validate_Sniper_Parity.ps1"
set "URL=https://raw.githubusercontent.com/Davemafy/icloud/sniper-contract-parity-v1/mt5/installer/Validate_Sniper_Parity.ps1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%PS1%'"
if errorlevel 1 (
  echo.
  echo FAILED: Could not download the validator.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
del /q "%PS1%" >nul 2>&1
exit /b %RC%
