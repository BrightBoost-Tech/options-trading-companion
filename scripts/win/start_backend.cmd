@echo off
setlocal

REM Resolve repo root: two levels up from scripts\win
cd /d "%~dp0\..\.."
set "REPO_ROOT=%cd%"

set "PYTHONPATH=%REPO_ROOT%"

REM Check for .venv first (preferred), then fallback to venv
set "VENV_DOT=%REPO_ROOT%\packages\quantum\.venv\Scripts\python.exe"
set "VENV_STD=%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe"

if exist "%VENV_DOT%" (
    set "BACKEND_VENV=%VENV_DOT%"
) else if exist "%VENV_STD%" (
    set "BACKEND_VENV=%VENV_STD%"
) else (
    echo [ERROR] Backend venv python not found.
    echo         Checked paths:
    echo         1) "%VENV_DOT%"
    echo         2) "%VENV_STD%"
    echo.
    echo         Please ensure you have created a virtual environment in packages\quantum.
    pause
    exit /b 1
)

echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] PYTHONPATH: %PYTHONPATH%
echo [INFO] Python used: "%BACKEND_VENV%"

REM Verify python executable path for debugging
"%BACKEND_VENV%" -c "import sys; print(f'[DEBUG] sys.executable: {sys.executable}')"

echo [INFO] Starting backend (uvicorn packages.quantum.api:app)...
"%BACKEND_VENV%" -m uvicorn packages.quantum.api:app --reload --host 127.0.0.1 --port 8000

endlocal
