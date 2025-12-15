@echo off
setlocal

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "BACKEND_LAUNCHER=%REPO_ROOT%\scripts\win\start_backend.cmd"
set "FRONTEND_LAUNCHER=%REPO_ROOT%\scripts\win\start_frontend.cmd"

if not exist "%BACKEND_LAUNCHER%" (
  echo [ERROR] Missing backend launcher:
  echo         "%BACKEND_LAUNCHER%"
  pause
  exit /b 1
)

if not exist "%FRONTEND_LAUNCHER%" (
  echo [ERROR] Missing frontend launcher:
  echo         "%FRONTEND_LAUNCHER%"
  pause
  exit /b 1
)

echo ============================================
echo Starting Options Trading Companion (1-click)
echo Repo root: %REPO_ROOT%
echo ============================================

REM Use start "" /D to avoid fragile quoting and Windows title parsing.
start "OTC Backend" /D "%REPO_ROOT%" cmd /k "%BACKEND_LAUNCHER%"
start "OTC Frontend" /D "%REPO_ROOT%" cmd /k "%FRONTEND_LAUNCHER%"

echo [OK] Spawned backend + frontend terminals.
endlocal
