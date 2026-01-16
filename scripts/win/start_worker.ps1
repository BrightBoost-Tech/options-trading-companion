# start_worker.ps1 - Starts the RQ worker for background jobs
# Usage: .\scripts\win\start_worker.ps1
#
# IMPORTANT: Uses rq.exe with SimpleWorker class for Windows compatibility

param(
    [string]$Queue = "otc",
    [switch]$NoWindow  # Run in current window instead of new one
)

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$QuantumDir = "$RepoRoot\packages\quantum"
$VenvActivate = "$QuantumDir\venv\Scripts\Activate.ps1"
$RqExe = "$QuantumDir\venv\Scripts\rq.exe"

Write-Host "[WORKER] Starting RQ worker for queue '$Queue'..." -ForegroundColor Yellow

# Check venv exists
if (-not (Test-Path $VenvActivate)) {
    Write-Error "Python venv not found at $QuantumDir\venv"
    Write-Host "Run: cd $QuantumDir && python -m venv venv && pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Check rq.exe exists
if (-not (Test-Path $RqExe)) {
    Write-Error "rq.exe not found at $RqExe"
    Write-Host "Run: pip install rq" -ForegroundColor Yellow
    exit 1
}

# Build the command
$startScript = @"
Set-Location '$RepoRoot'
. '$VenvActivate'
. '$PSScriptRoot\load_env.ps1'

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  RQ Worker - Queue: $Queue' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host "REDIS_URL: `$env:REDIS_URL" -ForegroundColor Gray
Write-Host "PYTHONPATH: `$env:PYTHONPATH" -ForegroundColor Gray
Write-Host ''

# Use rq.exe with SimpleWorker for Windows compatibility
& '$RqExe' worker $Queue --worker-class rq.worker.SimpleWorker
"@

if ($NoWindow) {
    # Run in current window (matching user's working template exactly)
    Set-Location $RepoRoot
    . $VenvActivate
    . "$PSScriptRoot\load_env.ps1"

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  RQ Worker - Queue: $Queue" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "REDIS_URL: $env:REDIS_URL" -ForegroundColor Gray
    Write-Host "PYTHONPATH: $env:PYTHONPATH" -ForegroundColor Gray
    Write-Host ""

    # Use rq.exe with SimpleWorker for Windows compatibility
    & $RqExe worker $Queue --worker-class rq.worker.SimpleWorker
}
else {
    # Start in new window
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($startScript))
    Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedCommand -WindowStyle Normal
    Write-Host "[WORKER] Started in new window" -ForegroundColor Green
}
