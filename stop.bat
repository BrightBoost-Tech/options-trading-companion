@echo off
:: ============================================================================
:: Options Trading Companion - Stop All Services
:: Delegates to scripts\win\stop_all.cmd
:: ============================================================================

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

call "%SCRIPT_DIR%\scripts\win\stop_all.cmd"
pause
