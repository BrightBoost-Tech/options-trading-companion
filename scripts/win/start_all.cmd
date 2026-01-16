@echo off
:: ============================================================================
:: Options Trading Companion - Full Stack Launcher
:: This is a simple wrapper that calls the PowerShell script.
:: For Desktop shortcuts: Target this file to avoid quoting issues.
:: ============================================================================

cd /d "%~dp0"

echo Starting Options Trading Companion...
echo.

:: Call PowerShell script with execution policy bypass
powershell -ExecutionPolicy Bypass -File "%~dp0start_all.ps1"

:: Keep window open if there was an error
if %errorlevel% neq 0 (
    echo.
    echo Startup failed with error code %errorlevel%
    pause
)
