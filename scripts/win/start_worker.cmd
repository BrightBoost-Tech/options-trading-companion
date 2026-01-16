@echo off
setlocal

:: ============================================================================
:: Options Trading Companion - Background Worker Launcher
:: ============================================================================

:: Resolve repo root from this script location
cd /d "%~dp0\..\.."
set "REPO_ROOT=%CD%"

:: Prefer .venv then venv
set "PY_EXE=%REPO_ROOT%\packages\quantum\.venv\Scripts\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe"

if not exist "%PY_EXE%" (
    echo [ERROR] Could not find backend python executable.
    echo         Checked:
    echo           %REPO_ROOT%\packages\quantum\.venv\Scripts\python.exe
    echo           %REPO_ROOT%\packages\quantum\venv\Scripts\python.exe
    pause
    exit /b 1
)

set "PYTHONPATH=%REPO_ROOT%"

echo [Worker] Repo root: %REPO_ROOT%
echo [Worker] Python: %PY_EXE%
echo [Worker] Starting background job worker...
echo.

pushd "%REPO_ROOT%"
"%PY_EXE%" -m packages.quantum.jobs.worker
set "EXIT_CODE=%ERRORLEVEL%"
popd

echo.
echo [Worker] Exited with code %EXIT_CODE%
pause
exit /b %EXIT_CODE%
