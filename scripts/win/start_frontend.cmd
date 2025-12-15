@echo off
setlocal

REM Resolve repo root: two levels up from scripts\win
cd /d "%~dp0\..\.."
set "REPO_ROOT=%cd%"

if not exist "%REPO_ROOT%\apps\web\package.json" (
  echo [ERROR] Frontend app not found at:
  echo         "%REPO_ROOT%\apps\web\package.json"
  pause
  exit /b 1
)

REM This repo is a pnpm workspace. Root dev uses pnpm filters.
REM Prefer invoking pnpm from repo root.
where pnpm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] pnpm not found on PATH.
  echo         Install pnpm or enable via corepack:
  echo           corepack enable
  echo           corepack prepare pnpm@latest --activate
  pause
  exit /b 1
)

echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] Starting frontend for apps/web (pnpm filter)...

cd /d "%REPO_ROOT%"
pnpm --filter "@app/web" dev

endlocal
