# start_frontend.ps1 - Starts the Next.js frontend dev server
# Usage: .\scripts\win\start_frontend.ps1

param(
    [int]$Port = 3000,
    [switch]$NoWindow  # Run in current window instead of new one
)

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path

Write-Host "[FRONTEND] Starting Next.js frontend on port $Port..." -ForegroundColor Yellow

# Check pnpm is available
$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) {
    Write-Error "pnpm is not installed or not in PATH"
    Write-Host "Install: npm install -g pnpm" -ForegroundColor Yellow
    exit 1
}

# Check if frontend already running
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" }
if ($existing) {
    Write-Host "[FRONTEND] Port $Port already in use - frontend may already be running" -ForegroundColor Green
    exit 0
}

# Build the command
$startScript = @"
Set-Location '$RepoRoot'
. '$PSScriptRoot\load_env.ps1' -Quiet
Write-Host '[FRONTEND] Starting pnpm dev...' -ForegroundColor Green
pnpm --filter "./apps/web" dev
"@

if ($NoWindow) {
    # Run in current window
    Set-Location $RepoRoot
    . "$PSScriptRoot\load_env.ps1" -Quiet
    Write-Host "[FRONTEND] Starting pnpm dev..." -ForegroundColor Green
    pnpm --filter "./apps/web" dev
}
else {
    # Start in new window
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($startScript))
    Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedCommand -WindowStyle Normal
    Write-Host "[FRONTEND] Started in new window" -ForegroundColor Green
}
