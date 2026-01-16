# stop_all.ps1 - Stop all Options Trading Companion services
# Usage: .\scripts\win\stop_all.ps1

param(
    [switch]$KeepRedis  # Keep Redis running
)

Write-Host ""
Write-Host "=============================================" -ForegroundColor Yellow
Write-Host "  Stopping Options Trading Companion" -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow
Write-Host ""

# Stop Frontend (Node processes on port 3000)
Write-Host "[1/4] Stopping Frontend..." -ForegroundColor Yellow
$frontendPorts = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" }
if ($frontendPorts) {
    foreach ($conn in $frontendPorts) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "       Killing process $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Gray
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "       Frontend stopped" -ForegroundColor Green
}
else {
    Write-Host "       Frontend not running" -ForegroundColor Gray
}

# Stop Worker (rq processes)
Write-Host "[2/4] Stopping Worker..." -ForegroundColor Yellow
$rqProcesses = Get-Process -Name "rq" -ErrorAction SilentlyContinue
$pythonWorkers = Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*rq*worker*" -or $_.CommandLine -like "*SimpleWorker*" }

$stoppedWorker = $false
if ($rqProcesses) {
    foreach ($proc in $rqProcesses) {
        Write-Host "       Killing rq process (PID: $($proc.Id))" -ForegroundColor Gray
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $stoppedWorker = $true
    }
}
if ($pythonWorkers) {
    foreach ($proc in $pythonWorkers) {
        Write-Host "       Killing python worker (PID: $($proc.Id))" -ForegroundColor Gray
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $stoppedWorker = $true
    }
}

if ($stoppedWorker) {
    Write-Host "       Worker stopped" -ForegroundColor Green
}
else {
    Write-Host "       Worker not running" -ForegroundColor Gray
}

# Stop Backend (uvicorn on port 8000)
Write-Host "[3/4] Stopping Backend..." -ForegroundColor Yellow
$backendPorts = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" }
if ($backendPorts) {
    foreach ($conn in $backendPorts) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "       Killing process $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Gray
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "       Backend stopped" -ForegroundColor Green
}
else {
    Write-Host "       Backend not running" -ForegroundColor Gray
}

# Stop Redis (Docker)
Write-Host "[4/4] Stopping Redis..." -ForegroundColor Yellow
if ($KeepRedis) {
    Write-Host "       Keeping Redis running (-KeepRedis specified)" -ForegroundColor Gray
}
else {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        $running = docker ps --filter "name=otc-redis" --format "{{.Names}}" 2>$null
        if ($running -eq "otc-redis") {
            docker stop otc-redis 2>$null | Out-Null
            Write-Host "       Redis stopped" -ForegroundColor Green
        }
        else {
            Write-Host "       Redis not running" -ForegroundColor Gray
        }
    }
    else {
        Write-Host "       Docker not available" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  All services stopped" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
