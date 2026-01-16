# start_redis.ps1 - Starts Redis via Docker
# Usage: .\scripts\win\start_redis.ps1

param(
    [switch]$Wait  # Wait for Redis to be ready
)

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path

Write-Host "[REDIS] Starting Redis container..." -ForegroundColor Yellow

# Check if Docker is available
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Error "Docker is not installed or not in PATH"
    exit 1
}

# Check if container already running
$existing = docker ps --filter "name=otc-redis" --format "{{.Names}}" 2>$null
if ($existing -eq "otc-redis") {
    Write-Host "[REDIS] Container 'otc-redis' already running" -ForegroundColor Green
}
else {
    # Check if container exists but stopped
    $stopped = docker ps -a --filter "name=otc-redis" --format "{{.Names}}" 2>$null
    if ($stopped -eq "otc-redis") {
        Write-Host "[REDIS] Starting existing container 'otc-redis'..." -ForegroundColor Yellow
        docker start otc-redis
    }
    else {
        # Start via docker-compose if available
        $composeFile = "$RepoRoot\docker-compose.redis.yml"
        if (Test-Path $composeFile) {
            Write-Host "[REDIS] Starting via docker-compose..." -ForegroundColor Yellow
            Push-Location $RepoRoot
            docker-compose -f docker-compose.redis.yml up -d
            Pop-Location
        }
        else {
            # Fallback: start Redis directly
            Write-Host "[REDIS] Starting Redis container directly..." -ForegroundColor Yellow
            docker run -d --name otc-redis -p 6379:6379 redis:7-alpine
        }
    }
}

if ($Wait) {
    Write-Host "[REDIS] Waiting for Redis to be ready..." -ForegroundColor Yellow
    $retries = 30
    $ready = $false

    for ($i = 0; $i -lt $retries; $i++) {
        try {
            $result = docker exec otc-redis redis-cli ping 2>$null
            if ($result -eq "PONG") {
                $ready = $true
                break
            }
        }
        catch {}
        Start-Sleep -Milliseconds 500
    }

    if ($ready) {
        Write-Host "[REDIS] Redis is ready!" -ForegroundColor Green
    }
    else {
        Write-Warning "[REDIS] Redis did not respond within timeout"
    }
}
else {
    Write-Host "[REDIS] Redis started (use -Wait to wait for ready)" -ForegroundColor Green
}
