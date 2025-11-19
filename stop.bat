@echo off
echo Stopping all servers...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM node.exe /T 2>nul
echo.
echo All servers stopped!
echo.
pause
