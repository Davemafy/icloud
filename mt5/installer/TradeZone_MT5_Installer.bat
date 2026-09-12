@echo off
setlocal EnableExtensions
color 0B
title Trade Zone - ONE MT5 Installer

echo ============================================================
echo  Trade Zone - ONE MT5 Installer
echo  Downloads the approved EA build from GitHub and compiles it
echo ============================================================
echo.

set "INSTALLER_URL=https://raw.githubusercontent.com/Davemafy/icloud/main/mt5/installer/Install_TradeZone_MT5.ps1"
set "TMP_PS=%TEMP%\TradeZone_MT5_GitHub_Installer.ps1"

echo Downloading current installer logic from GitHub...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%INSTALLER_URL%' -OutFile '%TMP_PS%' -TimeoutSec 45"
if errorlevel 1 (
  echo.
  echo ERROR: Could not download the installer from GitHub.
  echo Check internet access to github.com/raw.githubusercontent.com and try again.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TMP_PS%"
set "RC=%ERRORLEVEL%"
del /q "%TMP_PS%" >nul 2>&1
exit /b %RC%
