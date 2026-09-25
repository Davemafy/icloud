@echo off
setlocal
color 0B
title Trade Zone - Sniper Candidate Compiler
echo ============================================================
echo  Trade Zone - Sniper 3.42 / Bridge 1.51 Candidate Compiler
echo  Compile validation only - working EAs are NOT replaced
echo ============================================================
echo.
set "PS1=%TEMP%\TradeZone_Validate_Sniper_Candidates.ps1"
set "URL=https://raw.githubusercontent.com/Davemafy/icloud/sniper-contract-parity-v1/mt5/installer/Validate_Sniper_Parity_Candidates.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%PS1%'"
if errorlevel 1 (
 echo FAILED: Could not download the candidate validator.
 pause
 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"
del /q "%PS1%" >nul 2>&1
exit /b %RC%
