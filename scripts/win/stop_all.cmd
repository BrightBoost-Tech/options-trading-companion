@echo off
:: ============================================================================
:: Options Trading Companion - Stop All Services
:: Wrapper for PowerShell script
:: ============================================================================

cd /d "%~dp0"

echo Stopping Options Trading Companion services...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0stop_all.ps1"

pause
