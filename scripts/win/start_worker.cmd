@echo off
setlocal EnableDelayedExpansion

:: ============================================================================
:: Options Trading Companion - Background Worker Launcher
:: ============================================================================

:: Resolve repo root from this script location
cd /d "%~dp0\..\.."
set "REPO_ROOT=%CD%"

echo.
echo ============================================================
echo   Options Trading Companion - Worker
echo ============================================================
echo   Repo: %REPO_ROOT%
echo ============================================================
echo.

:: --------------------------------------------------------------------------
:: Find Python executable
:: --------------------------------------------------------------------------
set "PY_EXE="

:: Prefer .venv in packages/quantum
if exist "%REPO_ROOT%\packages\quantum\.venv\Scripts\python.exe" (
    set "PY_EXE=%REPO_ROOT%\packages\quantum\.venv\Scripts\python.exe"
)

:: Fallback to venv in packages/quantum
if not defined PY_EXE (
    if exist "%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe" (
        set "PY_EXE=%REPO_ROOT%\packages\quantum\venv\Scripts\python.exe"
    )
)

:: Fallback to python on PATH
if not defined PY_EXE (
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where python') do (
            set "PY_EXE=%%i"
            goto :found_python
        )
    )
)

:found_python
if not defined PY_EXE (
    echo [ERROR] Could not find Python executable.
    echo.
    echo   Checked locations:
    echo     - %REPO_ROOT%\packages\quantum\.venv\Scripts\python.exe
    echo     - %REPO_ROOT%\packages\quantum\venv\Scripts\python.exe
    echo     - python on PATH
    echo.
    echo   To fix: Create a virtual environment in packages\quantum:
    echo     cd packages\quantum
    echo     python -m venv .venv
    echo     .venv\Scripts\activate
    echo     pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo [OK] Python: %PY_EXE%

:: --------------------------------------------------------------------------
:: Check for .env files (informational only - Python loads them)
:: --------------------------------------------------------------------------
echo.
echo [INFO] Checking environment files...

set "ENV_FOUND="

if exist "%REPO_ROOT%\.env.local" (
    echo   [OK] Found: .env.local
    set "ENV_FOUND=1"
)

if exist "%REPO_ROOT%\.env" (
    echo   [OK] Found: .env
    set "ENV_FOUND=1"
)

if exist "%REPO_ROOT%\packages\quantum\.env.local" (
    echo   [OK] Found: packages\quantum\.env.local
    set "ENV_FOUND=1"
)

if exist "%REPO_ROOT%\packages\quantum\.env" (
    echo   [OK] Found: packages\quantum\.env
    set "ENV_FOUND=1"
)

if not defined ENV_FOUND (
    echo.
    echo [WARN] No .env files found!
    echo.
    echo   The worker requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
    echo.
    echo   To fix:
    echo     1. Copy .env.example to .env:
    echo          copy .env.example .env
    echo.
    echo     2. Edit .env and fill in your Supabase credentials.
    echo.
    echo     3. For local Supabase, run: supabase start
    echo.
)

:: --------------------------------------------------------------------------
:: Check key env vars (if already set in environment)
:: --------------------------------------------------------------------------
echo.
echo [INFO] Checking environment variables...

set "URL_VAR="
if defined SUPABASE_URL (
    set "URL_VAR=SUPABASE_URL"
) else if defined NEXT_PUBLIC_SUPABASE_URL (
    set "URL_VAR=NEXT_PUBLIC_SUPABASE_URL"
)

set "KEY_VAR="
if defined SUPABASE_SERVICE_ROLE_KEY (
    set "KEY_VAR=SUPABASE_SERVICE_ROLE_KEY"
) else if defined SUPABASE_SERVICE_KEY (
    set "KEY_VAR=SUPABASE_SERVICE_KEY"
)

if defined URL_VAR (
    echo   [OK] %URL_VAR% is set
) else (
    echo   [--] URL not set in environment (will load from .env)
)

if defined KEY_VAR (
    echo   [OK] %KEY_VAR% is set
) else (
    echo   [--] Service key not set in environment (will load from .env)
)

:: --------------------------------------------------------------------------
:: Start Worker
:: --------------------------------------------------------------------------
echo.
echo ============================================================
echo   Starting Worker...
echo ============================================================
echo.

set "PYTHONPATH=%REPO_ROOT%"

pushd "%REPO_ROOT%"
"%PY_EXE%" -m packages.quantum.jobs.worker
set "EXIT_CODE=%ERRORLEVEL%"
popd

echo.
echo ============================================================
if %EXIT_CODE% equ 0 (
    echo   Worker exited normally.
) else (
    echo   Worker exited with code %EXIT_CODE%
    echo.
    echo   Common issues:
    echo     - Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY
    echo     - Supabase not running (run: supabase start)
    echo     - Invalid credentials in .env file
)
echo ============================================================
echo.

pause
exit /b %EXIT_CODE%
