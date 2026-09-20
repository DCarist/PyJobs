@echo off
setlocal
title PyJobs Installer ^& Updater
cd /d "%~dp0"

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\install.ps1" %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] PyJobs installation or update exited with error code %ERRORLEVEL%.
    pause
)
