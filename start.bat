@echo off
:: ============================================================================
:: Options Trading Companion - Quick Start
:: Delegates to scripts\win\start_all.cmd
:: ============================================================================

:: Get the directory where this script lives
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: Call the full launcher
call "%SCRIPT_DIR%\scripts\win\start_all.cmd"
