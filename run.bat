@echo off
setlocal
title PyJobs Launcher
cd /d "%~dp0"

echo ===================================================
echo               Starting PyJobs Engine
echo ===================================================
echo Opening your dashboard in the default browser once ready...
echo Press Ctrl+C in this window to stop the server.
echo.

REM Only a clean main checkout checks origin/main; development branches skip it.
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run python -m pyjobs.update_check
) else (
    python -m pyjobs.update_check
)
if %ERRORLEVEL% equ 75 goto relaunch

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

goto :eof

:relaunch
call "%~f0" %*
