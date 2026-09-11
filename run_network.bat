@echo off
setlocal
title PyJobs Network Server (LAN)
cd /d "%~dp0"

echo ===================================================
echo           Starting PyJobs Network Server
echo ===================================================
echo Enabling connections from other machines on your LAN...
echo Opening your dashboard in the default browser...
echo Press Ctrl+C in this window to stop the server.
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run python run.py --network %*
) else (
    python run.py --network %*
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] PyJobs exited with an error code.
    pause
)
