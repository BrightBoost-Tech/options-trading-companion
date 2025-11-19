param(
  [Parameter(Mandatory = $true)]
  [string]$Scaffold,                # e.g. .\scaffold.txt
  [string]$Root = ".",              # e.g. .
  [switch]$Overwrite                # replace existing files
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Scaffold)) {
  throw "Scaffold file not found: $Scaffold"
}

# Normalize the Root to an absolute Windows path
$Root = (Resolve-Path -LiteralPath $Root).Path
Write-Host "Using Root: $Root"

# Read entire scaffold and normalize newlines
$text = Get-Content -Raw -Encoding UTF8 -LiteralPath $Scaffold
$text = $text -replace "`r`n", "`n"

# Match blocks of:
#   ---
#   path: <relative/path>
#
#   ```[lang?]
#   <content>
#   ```
$pattern = '(?ms)^---\s*\npath:\s*(.+?)\s*\n\s*\n```[^\n]*\n(.*?)\n```'
$rx = [regex]$pattern
$matches = $rx.Matches($text)

if ($matches.Count -eq 0) {
  throw "No file blocks matched. Make sure scaffold.txt includes lines like: `---` + `path:` and the fenced code content."
}

$created = 0; $updated = 0; $skipped = 0; $errors = 0

foreach ($m in $matches) {
  $relPath = ($m.Groups[1].Value).Trim()
  $content = $m.Groups[2].Value

  # Never write .env from a scaffold
  if ($relPath -match '(^|[\\/])\.env$') {
    Write-Host "SKIP  $relPath (user-managed)"
    $skipped++; continue
  }

  # Guard against .. traversal; normalize slashes
  if ($relPath -like '..*' -or $relPath -like '*..*') {
    Write-Warning "SKIP  $relPath (unsafe relative path)"
    $skipped++; continue
  }
  $relPath = $relPath -replace '/', '\'

  # Build destination **under the provided Root** (FIX #1)
  $dest = Join-Path -Path $Root -ChildPath $relPath
  $destDir = Split-Path -Parent $dest

  try {
    # Ensure parent directory exists (FIX #2)
    if (-not (Test-Path -LiteralPath $destDir)) {
      New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    }

    $exists = Test-Path -LiteralPath $dest
    if ($exists -and -not $Overwrite) {
      Write-Host "SKIP  $relPath (exists; use -Overwrite to replace)"
      $skipped++; continue
    }

    # Write UTF-8 (no BOM)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($dest, $content, $utf8NoBom)

    if ($exists -and $Overwrite) { $updated++ } else { $created++ }
    Write-Host "WROTE $relPath"
  }
  catch {
    $errors++
    Write-Warning "FAILED $relPath : $($_.Exception.Message)"
  }
}

Write-Host "Done. created=$created, updated=$updated, skipped=$skipped, errors=$errors"
if ($errors -gt 0) { exit 1 }
