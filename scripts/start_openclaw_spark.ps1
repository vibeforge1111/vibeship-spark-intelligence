# start_openclaw_spark.ps1 - Start OpenClaw bridge-layer services without owning core Spark by default.
param(
    [switch]$WithCore
)

$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
if (-not (Test-Path "$RepoRoot\sparkd.py")) { $RepoRoot = (Get-Location).Path }
$pidFile = Join-Path $RepoRoot "scripts\.spark_openclaw_pids.json"

function Get-ProcessByPattern {
    param([string]$Pattern)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match $Pattern
    } | Select-Object -First 1
}

function Set-DefaultEnv {
    param([string]$Name, [string]$Value)
    $current = (Get-Item -Path ("Env:" + $Name) -ErrorAction SilentlyContinue).Value
    if (-not $current -or [string]::IsNullOrWhiteSpace($current)) {
        Set-Item -Path ("Env:" + $Name) -Value $Value
    }
}

# Keep runtime behavior in tuneables/config_authority; only set alpha safety contract defaults here.
Set-DefaultEnv "SPARK_ADVISORY_ROUTE" "alpha"
Set-DefaultEnv "SPARK_ADVISORY_ALPHA_ENABLED" "1"
Set-DefaultEnv "SPARK_MEMORY_SPINE_CANONICAL" "1"
Set-DefaultEnv "SPARK_VALIDATE_AND_STORE" "1"
Set-DefaultEnv "SPARK_BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED" "0"
Set-DefaultEnv "SPARK_BRIDGE_LLM_EIDOS_SIDECAR_ENABLED" "0"
Set-DefaultEnv "SPARK_EMBED_BACKEND" "auto"

Write-Host "=== Spark x OpenClaw - Starting ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host "Mode: $(if ($WithCore) { 'with-core (starts missing core services)' } else { 'integration-only (tailer only)' })"

$ownedSparkd = $false
$ownedBridge = $false
$sparkd = $null
$bridge = $null

if ($WithCore) {
    # 1) sparkd (only if not already running)
    $sparkdProc = Get-ProcessByPattern "sparkd.py|-m sparkd"
    if ($sparkdProc) {
        Write-Host "`n[1/3] sparkd already running (PID $($sparkdProc.ProcessId))" -ForegroundColor DarkGray
    } else {
        Write-Host "`n[1/3] Starting sparkd..." -ForegroundColor Yellow
        $sparkd = Start-Process -FilePath python -ArgumentList "$RepoRoot\sparkd.py" `
            -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
        $ownedSparkd = $true
        Write-Host "  PID: $($sparkd.Id)"
        Start-Sleep -Seconds 2
    }

    # 2) bridge_worker (only if not already running)
    $bridgeProc = Get-ProcessByPattern "bridge_worker.py|-m bridge_worker"
    if ($bridgeProc) {
        Write-Host "[2/3] bridge_worker already running (PID $($bridgeProc.ProcessId))" -ForegroundColor DarkGray
    } else {
        Write-Host "[2/3] Starting bridge_worker..." -ForegroundColor Yellow
        $bridge = Start-Process -FilePath python -ArgumentList "$RepoRoot\bridge_worker.py" `
            -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
        $ownedBridge = $true
        Write-Host "  PID: $($bridge.Id)"
    }
} else {
    Write-Host "`n[1/3] Core services left untouched (integration-only mode)." -ForegroundColor DarkGray
    Write-Host "[2/3] Core services left untouched (integration-only mode)." -ForegroundColor DarkGray
}

# 3) openclaw_tailer (always owned by this script)
$existingTailer = Get-ProcessByPattern "openclaw_tailer.py"
$hookSpool = Join-Path $env:USERPROFILE ".spark\openclaw_hook_events.jsonl"
if ($existingTailer) {
    Write-Host "[3/3] openclaw_tailer already running (PID $($existingTailer.ProcessId)); reusing." -ForegroundColor DarkGray
    $tailerPid = [int]$existingTailer.ProcessId
} else {
    Write-Host "[3/3] Starting openclaw_tailer (with subagents)..." -ForegroundColor Yellow
    $tailer = Start-Process -FilePath python -ArgumentList `
        "$RepoRoot\adapters\openclaw_tailer.py","--include-subagents","--hook-events-file",$hookSpool `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
    $tailerPid = [int]$tailer.Id
    Write-Host "  PID: $tailerPid"
}

# Save OpenClaw-managed PIDs in an isolated file (never shared with spark.ps1).
@{
    owner        = "openclaw_bridge_layer"
    sparkd       = if ($sparkd) { $sparkd.Id } else { $null }
    bridge       = if ($bridge) { $bridge.Id } else { $null }
    tailer       = $tailerPid
    owns_sparkd  = $ownedSparkd
    owns_bridge  = $ownedBridge
    with_core    = [bool]$WithCore
    started      = (Get-Date -Format o)
} | ConvertTo-Json | Set-Content $pidFile -Encoding UTF8

Write-Host "`n=== All services started ===" -ForegroundColor Green
Write-Host "PID file: $pidFile"
