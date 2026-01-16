# start_backend.ps1 - Starts the FastAPI backend server
# Usage: .\scripts\win\start_backend.ps1

param(
    [int]$Port = 8000,
    [switch]$NoWindow  # Run in current window instead of new one
)

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$QuantumDir = "$RepoRoot\packages\quantum"
$VenvActivate = "$QuantumDir\venv\Scripts\Activate.ps1"

Write-Host "[BACKEND] Starting FastAPI backend on port $Port..." -ForegroundColor Yellow

# Check venv exists
if (-not (Test-Path $VenvActivate)) {
    Write-Error "Python venv not found at $QuantumDir\venv"
    Write-Host "Run: cd $QuantumDir && python -m venv venv && pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Check if backend already running
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" }
if ($existing) {
    Write-Host "[BACKEND] Port $Port already in use - backend may already be running" -ForegroundColor Green
    exit 0
}

# Build the command
$startScript = @"
Set-Location '$QuantumDir'
. '$VenvActivate'
. '$PSScriptRoot\load_env.ps1' -Quiet
Write-Host '[BACKEND] Starting uvicorn...' -ForegroundColor Green
python -m uvicorn api:app --host 127.0.0.1 --port $Port --reload
"@

if ($NoWindow) {
    # Run in current window
    Set-Location $QuantumDir
    . $VenvActivate
    . "$PSScriptRoot\load_env.ps1" -Quiet
    Write-Host "[BACKEND] Starting uvicorn..." -ForegroundColor Green
    python -m uvicorn api:app --host 127.0.0.1 --port $Port --reload
}
else {
    # Start in new window
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($startScript))
    Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedCommand -WindowStyle Normal
    Write-Host "[BACKEND] Started in new window" -ForegroundColor Green
}
