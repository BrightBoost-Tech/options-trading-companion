@echo off
echo ========================================
echo Starting Options Trading Companion
echo ========================================
echo.

REM Set environment variables if not already set
if "%POLYGON_API_KEY%"=="" set POLYGON_API_KEY=NKZ4W0g_094QVJMEh2rebeIRhluWtabk
if "%PLAID_CLIENT_ID%"=="" set PLAID_CLIENT_ID=6916bee0f7ef350020208272
if "%PLAID_SECRET%"=="" set PLAID_SECRET=0abdbc650e5c27358e4c8f73353473

REM Start Python API
start "Quantum API" cmd /k "cd /d %~dp0packages\quantum && python api.py"

REM Wait for API
timeout /t 5 /nobreak >nul

REM Start Next.js
start "Next.js Web" cmd /k "cd /d %~dp0apps\web && pnpm dev"

echo.
echo Both servers starting!
echo.
timeout /t 3
exit
