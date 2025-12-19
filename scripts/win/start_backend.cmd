@echo off
setlocal

REM Resolve REPO_ROOT from this script location:
REM If script is scripts\win\start_backend.cmd => repo root is two levels up.
cd /d "%~dp0\..\.."
set "REPO_ROOT=%cd%"

REM Prefer .venv then venv
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
echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] Python: %PY_EXE%
echo [INFO] PYTHONPATH: %PYTHONPATH%
echo [INFO] Starting Uvicorn...

pushd "%REPO_ROOT%"
"%PY_EXE%" -m uvicorn packages.quantum.api:app --reload --host 127.0.0.1 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"
popd

echo.
echo [INFO] Backend exited with code %EXIT_CODE%
pause
exit /b %EXIT_CODE%
