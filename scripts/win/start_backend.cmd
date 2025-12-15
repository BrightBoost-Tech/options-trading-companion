@echo off
setlocal

REM Resolve repo root: two levels up from scripts\win
cd /d "%~dp0\..\.."
set "REPO_ROOT=%cd%"

set "PYTHONPATH=%REPO_ROOT%"
set "BACKEND_VENV=%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe"

if not exist "%BACKEND_VENV%" (
  echo [ERROR] Backend venv python not found:
  echo         "%BACKEND_VENV%"
  echo         Expected venv at: packages\quantum\venv
  pause
  exit /b 1
)

echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] PYTHONPATH: %PYTHONPATH%
echo [INFO] Starting backend (uvicorn packages.quantum.api:app)...

"%BACKEND_VENV%" -m uvicorn packages.quantum.api:app --reload --host 127.0.0.1 --port 8000

endlocal
