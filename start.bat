@echo off
echo ========================================
echo Starting Options Trading Companion
echo ========================================
echo.

REM Set environment variables
set POLYGON_API_KEY=NKZ4W0g_094QVJMEh2rebeIRhluWtabk
set PLAID_CLIENT_ID=6916bee0f7ef350020208272
set PLAID_SECRET=0abdbc650e5c27358e4c8f73353473
set PLAID_ENV=sandbox

REM Start Python API
start "Quantum API" cmd /k "cd /d %~dp0packages\quantum && set POLYGON_API_KEY=%POLYGON_API_KEY% && set PLAID_CLIENT_ID=%PLAID_CLIENT_ID% && set PLAID_SECRET=%PLAID_SECRET% && set PLAID_ENV=%PLAID_ENV% && python api.py"

REM Wait for API
timeout /t 5 /nobreak >nul

REM Start Next.js
start "Next.js Web" cmd /k "cd /d %~dp0apps\web && pnpm dev"

echo.
echo Both servers starting!
echo.
timeout /t 3
exit
