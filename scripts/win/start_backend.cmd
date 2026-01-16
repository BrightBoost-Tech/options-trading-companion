@echo off
:: ============================================================================
:: Options Trading Companion - Backend Launcher
:: Wrapper for PowerShell script
:: ============================================================================

cd /d "%~dp0"

echo Starting Options Trading Companion Backend...
echo.

:: Use -NoWindow to run in current window (shows output)
powershell -ExecutionPolicy Bypass -File "%~dp0start_backend.ps1" -NoWindow
