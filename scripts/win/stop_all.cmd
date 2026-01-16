@echo off
setlocal

:: ============================================================================
:: Options Trading Companion - Stop All Services
:: ============================================================================

cd /d "%~dp0\..\.."
set "REPO_ROOT=%CD%"

echo.
echo ============================================================
echo   Stopping Options Trading Companion Services
echo ============================================================
echo.

:: Stop Redis container
echo [1/3] Stopping Redis...
where docker >nul 2>nul
if %errorlevel% equ 0 (
    docker compose -f "%REPO_ROOT%\docker-compose.redis.yml" down 2>nul
    echo       Redis stopped.
) else (
    echo       Docker not available, skipping Redis.
)

:: Kill processes on known ports
echo.
echo [2/3] Stopping Backend (port 8000)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000.*LISTENING"') do (
    echo       Killing PID %%a
    taskkill /F /PID %%a >nul 2>nul
)

echo.
echo [3/3] Stopping Frontend (port 3000)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3000.*LISTENING"') do (
    echo       Killing PID %%a
    taskkill /F /PID %%a >nul 2>nul
)

echo.
echo ============================================================
echo   All services stopped.
echo ============================================================
echo.

endlocal
