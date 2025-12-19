@echo off
setlocal

:: Resolve repo root
cd /d "%~dp0\..\.."
set "REPO_ROOT=%CD%"

echo [Frontend] Starting Web Client...
echo [Frontend] Repo Root: %REPO_ROOT%

:: Check if pnpm is installed
where pnpm >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] pnpm is not installed or not in PATH.
    echo Please enable pnpm via corepack:
    echo   corepack enable
    echo   corepack prepare pnpm@latest --activate
    pause
    exit /b 1
)

:: Preflight: Verify workspace package.json exists
if not exist "%REPO_ROOT%\apps\web\package.json" (
    echo [ERROR] apps/web/package.json not found.
    echo Ensure the repository is cloned correctly.
    pause
    exit /b 1
)

:: Preflight: Verify critical dependencies exist
set "REQ_PKG_DIR1=%REPO_ROOT%\apps\web\node_modules\@radix-ui\react-tooltip"
set "REQ_PKG_DIR2=%REPO_ROOT%\node_modules\@radix-ui\react-tooltip"
set "REQ_PKG_DIR3=%REPO_ROOT%\apps\web\node_modules\tailwindcss-animate"
set "REQ_PKG_DIR4=%REPO_ROOT%\node_modules\tailwindcss-animate"

set "MISSING_DEPS="
if not exist "%REQ_PKG_DIR1%" if not exist "%REQ_PKG_DIR2%" set "MISSING_DEPS=1"
if not exist "%REQ_PKG_DIR3%" if not exist "%REQ_PKG_DIR4%" set "MISSING_DEPS=1"

if defined MISSING_DEPS (
  echo [WARN] Required dependencies not found in node_modules.
  echo [INFO] Running pnpm install at repo root...
  cd /d "%REPO_ROOT%"
  call pnpm install
  if errorlevel 1 (
    echo [ERROR] pnpm install failed. See logs above.
    pause
    exit /b 1
  )
)

:: Run the dev server
cd /d "%REPO_ROOT%"
echo [Frontend] Running: pnpm --filter @app/web dev
call pnpm --filter @app/web dev

if %errorlevel% neq 0 (
    echo [Frontend] Process exited with error code %errorlevel%.
    pause
)
