@echo off
setlocal EnableDelayedExpansion

:: ============================================================================
:: Options Trading Companion - Full Stack Launcher
:: Starts: Redis (Docker) -> Backend API -> Worker -> Frontend
:: ============================================================================

:: Resolve repo root from this script location (scripts\win\start_all.cmd)
cd /d "%~dp0\..\.."
set "REPO_ROOT=%CD%"

echo.
echo ============================================================
echo   Options Trading Companion - Full Stack Launcher
echo ============================================================
echo   Repo: %REPO_ROOT%
echo ============================================================
echo.

:: --------------------------------------------------------------------------
:: 1. Check Docker is available (required for Redis)
:: --------------------------------------------------------------------------
where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARN] Docker not found in PATH. Redis will not be started.
    echo        Install Docker Desktop or add docker to PATH.
    set "SKIP_REDIS=1"
) else (
    docker info >nul 2>nul
    if %errorlevel% neq 0 (
        echo [WARN] Docker daemon not running. Redis will not be started.
        echo        Start Docker Desktop and try again.
        set "SKIP_REDIS=1"
    )
)

:: --------------------------------------------------------------------------
:: 2. Start Redis via Docker Compose (if not already running)
:: --------------------------------------------------------------------------
if not defined SKIP_REDIS (
    echo [1/4] Checking Redis...

    :: Check if port 6379 is already in use
    netstat -ano 2>nul | findstr ":6379.*LISTENING" >nul
    if !errorlevel! equ 0 (
        echo       Redis already running on port 6379. Skipping.
    ) else (
        echo       Starting Redis via Docker Compose...
        docker compose -f "%REPO_ROOT%\docker-compose.redis.yml" up -d
        if !errorlevel! neq 0 (
            echo [WARN] Failed to start Redis. Continuing without it.
        ) else (
            echo       Redis started successfully.
            :: Give Redis a moment to initialize
            timeout /t 2 /nobreak >nul
        )
    )
) else (
    echo [1/4] Skipping Redis (Docker not available)
)

:: --------------------------------------------------------------------------
:: 3. Start Backend API (if not already running)
:: --------------------------------------------------------------------------
echo.
echo [2/4] Checking Backend API...

netstat -ano 2>nul | findstr ":8000.*LISTENING" >nul
if %errorlevel% equ 0 (
    echo       Backend already running on port 8000. Skipping.
) else (
    echo       Starting Backend API...
    start "OTC Backend" cmd /k "%REPO_ROOT%\scripts\win\start_backend.cmd"
    :: Give backend time to start before worker
    timeout /t 3 /nobreak >nul
)

:: --------------------------------------------------------------------------
:: 4. Start Worker (if script exists)
:: --------------------------------------------------------------------------
echo.
echo [3/4] Checking Worker...

if exist "%REPO_ROOT%\scripts\win\start_worker.cmd" (
    :: Check if worker is already running by looking for python process with worker.py
    :: This is a simple heuristic - not foolproof
    tasklist /fi "imagename eq python.exe" 2>nul | findstr /i "python" >nul
    if %errorlevel% equ 0 (
        echo       Worker process may already be running. Starting anyway...
    )
    echo       Starting Worker...
    start "OTC Worker" cmd /k "%REPO_ROOT%\scripts\win\start_worker.cmd"
) else (
    echo       Worker script not found. Skipping.
    echo       (Create scripts\win\start_worker.cmd if needed)
)

:: --------------------------------------------------------------------------
:: 5. Start Frontend (if not already running)
:: --------------------------------------------------------------------------
echo.
echo [4/4] Checking Frontend...

netstat -ano 2>nul | findstr ":3000.*LISTENING" >nul
if %errorlevel% equ 0 (
    echo       Frontend already running on port 3000. Skipping.
) else (
    echo       Starting Frontend...
    start "OTC Frontend" cmd /k "%REPO_ROOT%\scripts\win\start_frontend.cmd"
)

:: --------------------------------------------------------------------------
:: Done
:: --------------------------------------------------------------------------
echo.
echo ============================================================
echo   All services launched!
echo ============================================================
echo   - Redis:    http://localhost:6379 (Docker)
echo   - Backend:  http://localhost:8000 (API docs: /docs)
echo   - Frontend: http://localhost:3000
echo ============================================================
echo.
echo   To stop all services:
echo   - Close the terminal windows, OR
echo   - Run: scripts\win\stop_all.cmd
echo ============================================================
echo.

endlocal
