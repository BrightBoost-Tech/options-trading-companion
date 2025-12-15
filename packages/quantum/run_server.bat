@echo off
setlocal

REM %~dp0 = directory of this script (packages\quantum)
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Repo root is two levels up from packages\quantum
cd /d "%SCRIPT_DIR%\..\.."
set "REPO_ROOT=%cd%"

set "BACKEND_VENV_PY=%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe"

if not exist "%BACKEND_VENV_PY%" (
  echo [ERROR] Backend venv python not found: "%BACKEND_VENV_PY%"
  exit /b 1
)

set PYTHONPATH=%REPO_ROOT%
echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] PYTHONPATH: %PYTHONPATH%

"%BACKEND_VENV_PY%" -m uvicorn packages.quantum.api:app --reload --host 127.0.0.1 --port 8000

endlocal
