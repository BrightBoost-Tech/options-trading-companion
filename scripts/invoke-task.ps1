<#
.SYNOPSIS
    Manually trigger any v4-signed task endpoint on the backend.

.DESCRIPTION
    Computes an HMAC-SHA256 signature per the v4 task signing spec and sends
    a POST request with the required X-Task-* headers.

    Uses kid1 from TASK_SIGNING_KEYS (format "kid1:secret1,kid2:secret2").
    Falls back to TASK_SIGNING_SECRET if TASK_SIGNING_KEYS is unset.

    The scope is derived automatically from TaskPath via a lookup table
    that mirrors packages/quantum/security/task_signing_v4.py and
    scripts/run_signed_task.py.

.PARAMETER TaskPath
    The endpoint path, e.g. /tasks/paper/exit-evaluate
    Also accepts the short task name, e.g. paper_exit_evaluate

.PARAMETER UserId
    Optional user UUID to include in the JSON body.

.PARAMETER BaseUrl
    Backend base URL. Defaults to $env:BASE_URL or production Railway URL.

.PARAMETER DryRun
    Print the request details without sending.

.EXAMPLE
    .\scripts\invoke-task.ps1 -TaskPath /tasks/paper/exit-evaluate -UserId 75ee12ad-b119-4f32-aeea-19b4ef55d587
    .\scripts\invoke-task.ps1 -TaskPath paper_exit_evaluate -UserId 75ee12ad-b119-4f32-aeea-19b4ef55d587
    .\scripts\invoke-task.ps1 -TaskPath /internal/tasks/alpaca/order-sync
    .\scripts\invoke-task.ps1 -TaskPath /tasks/paper/exit-evaluate -UserId 75ee12ad-... -DryRun
#>

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$TaskPath,

    [Parameter(Position = 1)]
    [string]$UserId,

    [string]$BaseUrl,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Task registry: path <-> scope mapping ────────────────────────────────────
# Mirrors TASKS dict in scripts/run_signed_task.py.
# Key = endpoint path, Value = scope string.

$TaskRegistry = @{
    # Morning
    "/tasks/suggestions/close"                    = "tasks:suggestions_close"
    "/tasks/suggestions/open"                     = "tasks:suggestions_open"
    # Midday
    "/tasks/paper/auto-execute"                   = "tasks:paper_auto_execute"
    # Afternoon
    "/tasks/paper/exit-evaluate"                  = "tasks:paper_exit_evaluate"
    "/tasks/paper/mark-to-market"                 = "tasks:paper_mark_to_market"
    # EOD
    "/internal/tasks/progression/daily-eval"      = "tasks:daily_progression_eval"
    "/tasks/learning/ingest"                      = "tasks:learning_ingest"
    "/tasks/paper/learning-ingest"                = "tasks:paper_learning_ingest"
    "/tasks/policy-lab/eval"                      = "tasks:policy_lab_eval"
    "/internal/tasks/learning/post-trade"         = "tasks:post_trade_learning"
    # Pre-dawn
    "/internal/tasks/calibration/update"          = "tasks:calibration_update"
    "/internal/tasks/orchestrator/start-day"      = "tasks:day_orchestrator"
    # Frequent
    "/internal/tasks/alpaca/order-sync"           = "tasks:alpaca_order_sync"
    "/internal/tasks/risk/intraday-monitor"       = "tasks:intraday_risk_monitor"
    # Health
    "/tasks/ops/health_check"                     = "tasks:ops_health_check"
    # Paper
    "/tasks/paper/auto-close"                     = "tasks:paper_auto_close"
    "/tasks/paper/process-orders"                 = "tasks:paper_process_orders"
    # Validation
    "/tasks/validation/eval"                      = "tasks:validation_eval"
    "/tasks/validation/shadow-eval"               = "tasks:validation_shadow_eval"
    "/tasks/validation/cohort-eval"               = "tasks:validation_cohort_eval"
    "/tasks/validation/autopromote-cohort"        = "tasks:validation_autopromote_cohort"
    "/tasks/validation/preflight"                 = "tasks:validation_preflight"
    "/tasks/validation/init-window"               = "tasks:validation_init_window"
    # Other
    "/tasks/universe/sync"                        = "tasks:universe_sync"
    "/tasks/morning-brief"                        = "tasks:morning_brief"
    "/tasks/midday-scan"                          = "tasks:midday_scan"
    "/tasks/weekly-report"                        = "tasks:weekly_report"
    "/tasks/strategy/autotune"                    = "tasks:strategy_autotune"
    "/internal/tasks/iv/daily-refresh"            = "tasks:iv_daily_refresh"
    "/internal/tasks/train-learning-v3"           = "tasks:learning_train"
    "/internal/tasks/plaid/backfill-history"       = "tasks:plaid_backfill"
    "/internal/tasks/autotune/walk-forward"       = "tasks:walk_forward_autotune"
    "/internal/tasks/promotion/check"             = "tasks:promotion_check"
}

# Short-name lookup: task_name -> path (for convenience)
$ShortNames = @{}
foreach ($entry in $TaskRegistry.GetEnumerator()) {
    # Derive short name from scope: "tasks:paper_exit_evaluate" -> "paper_exit_evaluate"
    $short = $entry.Value -replace "^tasks:", ""
    $ShortNames[$short] = $entry.Key
}

# ── Resolve TaskPath ─────────────────────────────────────────────────────────

if (-not $TaskPath.StartsWith("/")) {
    # Treat as short name
    if ($ShortNames.ContainsKey($TaskPath)) {
        $TaskPath = $ShortNames[$TaskPath]
    }
    else {
        Write-Error "Unknown task name '$TaskPath'. Valid names:`n$($ShortNames.Keys | Sort-Object | ForEach-Object { "  $_" } | Out-String)"
        exit 1
    }
}

if (-not $TaskRegistry.ContainsKey($TaskPath)) {
    Write-Error "Unknown task path '$TaskPath'. Valid paths:`n$($TaskRegistry.Keys | Sort-Object | ForEach-Object { "  $_" } | Out-String)"
    exit 1
}

$scope = $TaskRegistry[$TaskPath]

# ── Resolve signing secret (kid1 from TASK_SIGNING_KEYS) ────────────────────

$signingKeys = $env:TASK_SIGNING_KEYS
$secret = $null
$keyId = $null

if ($signingKeys) {
    # Format: "kid1:secret1,kid2:secret2" — take the first entry
    $firstEntry = ($signingKeys -split ",")[0].Trim()
    if ($firstEntry -match "^([^:]+):(.+)$") {
        $keyId  = $Matches[1]
        $secret = $Matches[2]
    }
    else {
        Write-Error "TASK_SIGNING_KEYS format invalid. Expected 'kid:secret[,kid2:secret2]'"
        exit 1
    }
}
else {
    $secret = $env:TASK_SIGNING_SECRET
}

if (-not $secret) {
    Write-Error "No signing secret found. Set TASK_SIGNING_KEYS or TASK_SIGNING_SECRET."
    exit 1
}

# ── Resolve base URL ─────────────────────────────────────────────────────────

if (-not $BaseUrl) {
    $BaseUrl = $env:BASE_URL
}
if (-not $BaseUrl) {
    $BaseUrl = "https://be-production-48b1.up.railway.app"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

# ── Build body ───────────────────────────────────────────────────────────────

$bodyObj = @{}
if ($UserId) {
    $bodyObj["user_id"] = $UserId
}
$body = $bodyObj | ConvertTo-Json -Compress
$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)

# ── Compute HMAC-SHA256 signature ────────────────────────────────────────────
# Payload: v4:{ts}:{nonce}:{method}:{path}:{body_hash}:{scope}

$method = "POST"
$ts     = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

# Cryptographically random 16-byte nonce as hex
$nonceBytes = New-Object byte[] 16
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($nonceBytes)
$nonce = [BitConverter]::ToString($nonceBytes).Replace("-", "").ToLower()

# SHA-256 of body
$sha256     = [System.Security.Cryptography.SHA256]::Create()
$bodyHash   = [BitConverter]::ToString(
    $sha256.ComputeHash($bodyBytes)
).Replace("-", "").ToLower()

$payload = "v4:${ts}:${nonce}:${method}:${TaskPath}:${bodyHash}:${scope}"

$hmacsha     = New-Object System.Security.Cryptography.HMACSHA256
$hmacsha.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$signature   = [BitConverter]::ToString(
    $hmacsha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($payload))
).Replace("-", "").ToLower()

# ── Build headers ────────────────────────────────────────────────────────────

$headers = @{
    "Content-Type"     = "application/json"
    "X-Task-Ts"        = "$ts"
    "X-Task-Nonce"     = $nonce
    "X-Task-Scope"     = $scope
    "X-Task-Signature" = $signature
}
if ($keyId) {
    $headers["X-Task-Key-Id"] = $keyId
}

$url = "${BaseUrl}${TaskPath}"

# ── Dry run or send ──────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Task:   $scope" -ForegroundColor Cyan
Write-Host "URL:    $url"
Write-Host "Body:   $body"
if ($keyId) {
    Write-Host "Key ID: $keyId"
}
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] Headers:" -ForegroundColor Yellow
    $headers.GetEnumerator() | ForEach-Object {
        $val = if ($_.Key -eq "X-Task-Signature") { $_.Value.Substring(0, 16) + "..." } else { $_.Value }
        Write-Host "  $($_.Key): $val"
    }
    Write-Host ""
    Write-Host "[DRY RUN] Payload string (pre-HMAC):"
    Write-Host "  $payload"
    exit 0
}

try {
    $response = Invoke-WebRequest -Uri $url -Method POST -Body $body -Headers $headers -UseBasicParsing -TimeoutSec 60
    $status = $response.StatusCode

    Write-Host "Status: $status" -ForegroundColor $(if ($status -lt 300) { "Green" } else { "Red" })

    if ($response.Content) {
        try {
            $json = $response.Content | ConvertFrom-Json
            $json | ConvertTo-Json -Depth 5 | Write-Host
        }
        catch {
            Write-Host $response.Content
        }
    }
}
catch {
    $err = $_.Exception
    if ($err.Response) {
        $status = [int]$err.Response.StatusCode
        Write-Host "Status: $status" -ForegroundColor Red

        try {
            $reader = New-Object System.IO.StreamReader($err.Response.GetResponseStream())
            $errBody = $reader.ReadToEnd()
            Write-Host $errBody
        }
        catch {
            Write-Host $err.Message
        }
    }
    else {
        Write-Host "Error: $($err.Message)" -ForegroundColor Red
    }
    exit 1
}
