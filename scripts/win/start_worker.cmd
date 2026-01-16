@echo off
:: ============================================================================
:: Options Trading Companion - Worker Launcher
:: Wrapper for PowerShell script
:: ============================================================================

cd /d "%~dp0"

echo Starting Options Trading Companion Worker...
echo.

:: Use -NoWindow to run in current window (shows output)
powershell -ExecutionPolicy Bypass -File "%~dp0start_worker.ps1" -NoWindow

pause
