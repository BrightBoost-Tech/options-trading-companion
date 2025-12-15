@echo off
setlocal

REM Resolve repo root (directory of this file)
set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

echo ============================================
echo Starting Options Trading Companion
echo Repo Root: %REPO_ROOT%
echo ============================================

REM ---- Backend paths ----
set "BACKEND_VENV=%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe"

REM ---- Frontend path (CHANGE if needed) ----
set "FRONTEND_DIR=%REPO_ROOT%\apps\web"

REM ---- Validate backend ----
if not exist "%BACKEND_VENV%" (
  echo [ERROR] Backend venv not found:
  echo %BACKEND_VENV%
  pause
  exit /b 1
)

REM ---- Validate frontend ----
if not exist "%FRONTEND_DIR%\package.json" (
  echo [ERROR] Frontend package.json not found in:
  echo %FRONTEND_DIR%
  pause
  exit /b 1
)

REM ---- Start Backend ----
echo [INFO] Starting backend...
start "OTC Backend" cmd /k ^
  "cd /d \"%REPO_ROOT%\" && ^
   set PYTHONPATH=%REPO_ROOT% && ^
   \"%BACKEND_VENV%\" -m uvicorn packages.quantum.api:app --reload --host 127.0.0.1 --port 8000"

REM ---- Start Frontend ----
echo [INFO] Starting frontend...
start "OTC Frontend" cmd /k ^
  "cd /d \"%FRONTEND_DIR%\" && npm run dev"

echo.
echo [OK] Launch commands issued.
echo.
endlocal
