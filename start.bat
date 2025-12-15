@echo off
setlocal enabledelayedexpansion

REM Resolve repo root as the directory containing this script
set "REPO_ROOT=%~dp0"
REM Remove trailing backslash if present
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

echo.
echo ============================================
echo Starting Options Trading Companion (FE + BE)
echo Repo: %REPO_ROOT%
echo ============================================
echo.

REM ---- Backend settings ----
set "BACKEND_DIR=%REPO_ROOT%\packages\quantum"
set "BACKEND_VENV_PY=%BACKEND_DIR%\venv\Scripts\python.exe"
set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT=8000"

REM ---- Frontend settings ----
REM NOTE: Update FRONTEND_DIR if your frontend lives elsewhere.
set "FRONTEND_DIR=%REPO_ROOT%\apps\web"
set "FRONTEND_PORT=5173"

REM Validate paths
if not exist "%BACKEND_VENV_PY%" (
  echo [ERROR] Backend venv python not found: "%BACKEND_VENV_PY%"
  echo         Expected venv at: %BACKEND_DIR%\venv
  exit /b 1
)

if not exist "%FRONTEND_DIR%" (
  echo [ERROR] Frontend directory not found: "%FRONTEND_DIR%"
  echo         Update FRONTEND_DIR in start.bat to the correct path.
  exit /b 1
)

REM ---- Start backend in a new terminal ----
echo [INFO] Launching backend...
start "OTC Backend" cmd /k ^
  "cd /d \"%REPO_ROOT%\" && ^
   set PYTHONPATH=%REPO_ROOT% && ^
   \"%BACKEND_VENV_PY%\" -m uvicorn packages.quantum.api:app --reload --host %BACKEND_HOST% --port %BACKEND_PORT%"

REM ---- Start frontend in a new terminal ----
echo [INFO] Launching frontend...
start "OTC Frontend" cmd /k ^
  "cd /d \"%FRONTEND_DIR%\" && ^
   if exist package-lock.json (npm run dev) else (npm run dev)"

echo.
echo [OK] Launch commands issued. Check the two opened terminals.
echo.
endlocal
