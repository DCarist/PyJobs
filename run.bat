@echo off
setlocal
title PyJobs Launcher
cd /d "%~dp0"

echo ===================================================
echo               Starting PyJobs Engine
echo ===================================================
echo Opening your dashboard in the default browser...
echo Press Ctrl+C in this window to stop the server.
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run python run.py %*
) else (
    python run.py %*
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] PyJobs exited with an error code.
    pause
)
