# start_all.ps1 - One-button startup for Options Trading Companion
# Starts: Redis, Backend, Worker, Frontend
#
# Usage: .\scripts\win\start_all.ps1
#        .\scripts\win\start_all.ps1 -SkipFrontend
#        .\scripts\win\start_all.ps1 -WorkerOnly

param(
    [switch]$SkipRedis,
    [switch]$SkipBackend,
    [switch]$SkipWorker,
    [switch]$SkipFrontend,
    [switch]$WorkerOnly  # Only start worker (assumes Redis running)
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path "$ScriptDir\..\..").Path

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Options Trading Companion - Startup" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Repository: $RepoRoot" -ForegroundColor Gray
Write-Host ""

# Handle WorkerOnly flag
if ($WorkerOnly) {
    $SkipRedis = $false  # Still ensure Redis is running
    $SkipBackend = $true
    $SkipFrontend = $true
}

# Track what we're starting
$services = @()

# 1. Start Redis
if (-not $SkipRedis) {
    Write-Host "[1/4] Starting Redis..." -ForegroundColor Yellow
    try {
        & "$ScriptDir\start_redis.ps1" -Wait
        $services += "Redis"
    }
    catch {
        Write-Error "Failed to start Redis: $_"
        exit 1
    }
}
else {
    Write-Host "[1/4] Skipping Redis" -ForegroundColor Gray
}

# Small delay to ensure Redis is ready
Start-Sleep -Seconds 1

# 2. Start Backend
if (-not $SkipBackend) {
    Write-Host "[2/4] Starting Backend..." -ForegroundColor Yellow
    try {
        & "$ScriptDir\start_backend.ps1"
        $services += "Backend"
    }
    catch {
        Write-Error "Failed to start Backend: $_"
        exit 1
    }
}
else {
    Write-Host "[2/4] Skipping Backend" -ForegroundColor Gray
}

# Small delay before worker
Start-Sleep -Seconds 2

# 3. Start Worker
if (-not $SkipWorker) {
    Write-Host "[3/4] Starting Worker..." -ForegroundColor Yellow
    try {
        & "$ScriptDir\start_worker.ps1"
        $services += "Worker"
    }
    catch {
        Write-Error "Failed to start Worker: $_"
        exit 1
    }
}
else {
    Write-Host "[3/4] Skipping Worker" -ForegroundColor Gray
}

# 4. Start Frontend
if (-not $SkipFrontend) {
    Write-Host "[4/4] Starting Frontend..." -ForegroundColor Yellow
    try {
        & "$ScriptDir\start_frontend.ps1"
        $services += "Frontend"
    }
    catch {
        Write-Error "Failed to start Frontend: $_"
        exit 1
    }
}
else {
    Write-Host "[4/4] Skipping Frontend" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  Startup Complete!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Services started: $($services -join ', ')" -ForegroundColor Cyan
Write-Host ""
Write-Host "URLs:" -ForegroundColor White
if ($services -contains "Frontend") {
    Write-Host "  Frontend:  http://localhost:3000" -ForegroundColor Gray
}
if ($services -contains "Backend") {
    Write-Host "  Backend:   http://127.0.0.1:8000" -ForegroundColor Gray
    Write-Host "  API Docs:  http://127.0.0.1:8000/docs" -ForegroundColor Gray
}
Write-Host ""
Write-Host "To stop all services: .\scripts\win\stop_all.ps1" -ForegroundColor Yellow
Write-Host ""
