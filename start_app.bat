@echo off
start "Quantum API" cmd /k "cd packages\quantum && call run_server.bat"
start "Next.js Web" cmd /k "cd /d %~dp0 && call scripts\win\start_frontend.cmd"
