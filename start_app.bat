@echo off
start "Quantum API" cmd /k "cd packages\quantum && call run_server.bat"
start "Next.js Web" cmd /k "cd apps\web && npm run dev"
