@echo off
:: ============================================================================
:: Options Trading Companion - Frontend Launcher
:: Wrapper for PowerShell script
:: ============================================================================

cd /d "%~dp0"

echo Starting Options Trading Companion Frontend...
echo.

:: Use -NoWindow to run in current window (shows output)
powershell -ExecutionPolicy Bypass -File "%~dp0start_frontend.ps1" -NoWindow
