# load_env.ps1 - Shared environment loader for Options Trading Companion
# Sources .env files and sets up PYTHONPATH/REDIS_URL
# Usage: . .\scripts\win\load_env.ps1

param(
    [switch]$Quiet
)

# Get repo root (two levels up from this script)
$script:RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path

function Write-Status {
    param([string]$Message)
    if (-not $Quiet) {
        Write-Host "[ENV] $Message" -ForegroundColor Cyan
    }
}

function Load-EnvFile {
    param([string]$FilePath)

    if (-not (Test-Path $FilePath)) {
        return $false
    }

    Write-Status "Loading $FilePath"

    Get-Content $FilePath | Where-Object {
        $_ -and $_ -notmatch '^\s*#' -and $_ -match '='
    } | ForEach-Object {
        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2) {
            $key = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")

            # Only set if not already set (allows overrides via command line)
            if (-not (Get-Item -Path "Env:$key" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:$key" -Value $value
            }
        }
    }

    return $true
}

# Search for env files in priority order (first found wins for each variable)
$envFiles = @(
    "$RepoRoot\.env.local",
    "$RepoRoot\.env",
    "$RepoRoot\packages\quantum\.env.local",
    "$RepoRoot\packages\quantum\.env"
)

$loadedAny = $false
foreach ($envFile in $envFiles) {
    if (Load-EnvFile $envFile) {
        $loadedAny = $true
    }
}

if (-not $loadedAny) {
    Write-Warning "No .env files found. Checked: $($envFiles -join ', ')"
}

# Set fallback aliases (frontend-style -> backend-style)
if (-not $env:NEXT_PUBLIC_SUPABASE_URL -and $env:SUPABASE_URL) {
    $env:NEXT_PUBLIC_SUPABASE_URL = $env:SUPABASE_URL
    Write-Status "Set NEXT_PUBLIC_SUPABASE_URL from SUPABASE_URL"
}

if (-not $env:SUPABASE_URL -and $env:NEXT_PUBLIC_SUPABASE_URL) {
    $env:SUPABASE_URL = $env:NEXT_PUBLIC_SUPABASE_URL
    Write-Status "Set SUPABASE_URL from NEXT_PUBLIC_SUPABASE_URL"
}

if (-not $env:SUPABASE_SERVICE_ROLE_KEY -and $env:SUPABASE_SERVICE_KEY) {
    $env:SUPABASE_SERVICE_ROLE_KEY = $env:SUPABASE_SERVICE_KEY
    Write-Status "Set SUPABASE_SERVICE_ROLE_KEY from SUPABASE_SERVICE_KEY"
}

if (-not $env:NEXT_PUBLIC_SUPABASE_ANON_KEY -and $env:SUPABASE_ANON_KEY) {
    $env:NEXT_PUBLIC_SUPABASE_ANON_KEY = $env:SUPABASE_ANON_KEY
    Write-Status "Set NEXT_PUBLIC_SUPABASE_ANON_KEY from SUPABASE_ANON_KEY"
}

# Set PYTHONPATH for imports
$env:PYTHONPATH = "$RepoRoot;$RepoRoot\packages\quantum"
Write-Status "PYTHONPATH=$env:PYTHONPATH"

# Set REDIS_URL default if not set
if (-not $env:REDIS_URL) {
    $env:REDIS_URL = "redis://127.0.0.1:6379/0"
    Write-Status "REDIS_URL=$env:REDIS_URL (default)"
}

# Export the repo root for other scripts
$global:OTC_REPO_ROOT = $RepoRoot

Write-Status "Environment loaded from $RepoRoot"
