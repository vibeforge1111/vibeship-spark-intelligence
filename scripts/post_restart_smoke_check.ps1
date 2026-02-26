param(
    [int]$HookFreshSeconds = 1800,
    [int]$HeartbeatFreshSeconds = 180,
    [int]$CronFreshMinutes = 180,
    [switch]$RunCanary,
    [string]$CanaryAgent = "spark-speed"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
Set-Location $repoRoot

$homeDir = [Environment]::GetFolderPath("UserProfile")
$openclawConfigPath = Join-Path $homeDir ".openclaw\openclaw.json"
$cronJobsPath = Join-Path $homeDir ".openclaw\cron\jobs.json"
$cronRunsDir = Join-Path $homeDir ".openclaw\cron\runs"
$sparkRoot = Join-Path $homeDir ".spark"
$queuePath = Join-Path $sparkRoot "queue\events.jsonl"
$bridgeHeartbeatPath = Join-Path $sparkRoot "bridge_worker_heartbeat.json"
$schedulerHeartbeatPath = Join-Path $sparkRoot "scheduler_heartbeat.json"

$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [ValidateSet("PASS", "WARN", "FAIL")]
        [string]$Status,
        [string]$Detail
    )
    $checks.Add([PSCustomObject]@{
            Name = $Name
            Status = $Status
            Detail = $Detail
        })
}

function To-JsonLineObject {
    param([string]$Line)
    if ([string]::IsNullOrWhiteSpace($Line)) { return $null }
    try {
        return ($Line | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

function Age-Seconds {
    param([double]$TsSeconds)
    return [Math]::Round(([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $TsSeconds), 2)
}

if ($RunCanary) {
    try {
        $canaryOut = & openclaw agent --local --agent $CanaryAgent -m "HOOK_SMOKE_CHECK: reply HOOK_SMOKE_OK only" --timeout 120 --json 2>&1
        $canaryText = ($canaryOut | Out-String)
        if ($canaryText -match "HOOK_SMOKE_OK") {
            Add-Check "canary.run" "PASS" "Canary reply observed."
        }
        else {
            Add-Check "canary.run" "WARN" "Canary ran but expected token not found."
        }
    }
    catch {
        Add-Check "canary.run" "FAIL" ("Canary command failed: " + $_.Exception.Message)
    }
}

$openclawCfg = $null
if (-not (Test-Path $openclawConfigPath)) {
    Add-Check "openclaw.config" "FAIL" "Missing openclaw.json"
}
else {
    try {
        $openclawCfg = Get-Content -Path $openclawConfigPath -Raw | ConvertFrom-Json
        Add-Check "openclaw.config" "PASS" $openclawConfigPath
    }
    catch {
        Add-Check "openclaw.config" "FAIL" ("Invalid JSON: " + $_.Exception.Message)
    }
}

$hookSpoolPath = Join-Path $sparkRoot "openclaw_hook_events.jsonl"
if ($openclawCfg) {
    $allow = @()
    if ($openclawCfg.plugins -and $openclawCfg.plugins.allow) {
        $allow = @($openclawCfg.plugins.allow)
    }
    if ($allow -contains "spark-telemetry-hooks") {
        Add-Check "plugin.allowlist" "PASS" "spark-telemetry-hooks included."
    }
    else {
        Add-Check "plugin.allowlist" "FAIL" 'spark-telemetry-hooks missing from plugins.allow. Add "allow": ["spark-telemetry-hooks"] to the plugins section of openclaw.json (see extensions/openclaw-spark-telemetry/README.md).'
    }

    $entry = $null
    if ($openclawCfg.plugins -and $openclawCfg.plugins.entries) {
        $entry = $openclawCfg.plugins.entries."spark-telemetry-hooks"
    }
    if ($entry -and $entry.enabled -ne $false) {
        Add-Check "plugin.entry_enabled" "PASS" "plugins.entries.spark-telemetry-hooks enabled."
    }
    else {
        Add-Check "plugin.entry_enabled" "FAIL" "plugins.entries.spark-telemetry-hooks not enabled."
    }

    if ($entry -and $entry.config -and $entry.config.spoolFile) {
        $hookSpoolPath = [string]$entry.config.spoolFile
    }
    Add-Check "plugin.spool_path" "PASS" $hookSpoolPath
}

try {
    $svcRaw = & python -c "from lib.service_control import service_status; import json; s=service_status(); print(json.dumps({k:s.get(k,{}) for k in ['sparkd','bridge_worker','scheduler','watchdog']}))"
    $svc = $svcRaw | ConvertFrom-Json
    foreach ($name in @("sparkd", "bridge_worker", "scheduler", "watchdog")) {
        $row = $svc.$name
        if ($row -and $row.running -eq $true) {
            $procId = $row.pid
            Add-Check ("core." + $name) "PASS" ("running pid=" + $procId)
        }
        else {
            Add-Check ("core." + $name) "FAIL" "not running"
        }
    }
}
catch {
    Add-Check "core.status" "FAIL" ("Failed to read service status: " + $_.Exception.Message)
}

if (Test-Path $bridgeHeartbeatPath) {
    try {
        $hb = Get-Content -Path $bridgeHeartbeatPath -Raw | ConvertFrom-Json
        $hbTs = [double]($hb.ts)
        $hbAge = Age-Seconds $hbTs
        if ($hbAge -le $HeartbeatFreshSeconds) {
            Add-Check "heartbeat.bridge_worker" "PASS" ("age_sec=" + $hbAge)
        }
        else {
            Add-Check "heartbeat.bridge_worker" "FAIL" ("stale age_sec=" + $hbAge)
        }
    }
    catch {
        Add-Check "heartbeat.bridge_worker" "FAIL" ("Invalid heartbeat JSON: " + $_.Exception.Message)
    }
}
else {
    Add-Check "heartbeat.bridge_worker" "FAIL" "Missing heartbeat file."
}

if (Test-Path $schedulerHeartbeatPath) {
    try {
        $shb = Get-Content -Path $schedulerHeartbeatPath -Raw | ConvertFrom-Json
        $shbTs = [double]($shb.ts)
        $shbAge = Age-Seconds $shbTs
        if ($shbAge -le ($HeartbeatFreshSeconds * 2)) {
            Add-Check "heartbeat.scheduler" "PASS" ("age_sec=" + $shbAge)
        }
        else {
            Add-Check "heartbeat.scheduler" "WARN" ("stale age_sec=" + $shbAge)
        }
    }
    catch {
        Add-Check "heartbeat.scheduler" "WARN" ("Invalid scheduler heartbeat JSON: " + $_.Exception.Message)
    }
}
else {
    Add-Check "heartbeat.scheduler" "WARN" "Missing scheduler heartbeat file."
}

$tailers = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -match "openclaw_tailer.py"
}
if (-not $tailers -or $tailers.Count -eq 0) {
    Add-Check "tailer.process" "FAIL" "openclaw_tailer.py process not found."
}
else {
    $hasHookArg = $false
    $tailerCount = @($tailers).Count
    foreach ($t in $tailers) {
        if ($t.CommandLine -match "--hook-events-file") {
            $hasHookArg = $true
        }
    }
    if ($hasHookArg) {
        Add-Check "tailer.process" "PASS" ("count=" + $tailerCount + " hook arg detected")
    }
    else {
        Add-Check "tailer.process" "WARN" ("count=" + $tailerCount + " running without explicit --hook-events-file")
    }
}

if (-not (Test-Path $hookSpoolPath)) {
    Add-Check "hook_spool.exists" "FAIL" ("Missing spool file: " + $hookSpoolPath)
}
else {
    $spoolLines = Get-Content -Path $hookSpoolPath
    Add-Check "hook_spool.exists" "PASS" ("rows=" + $spoolLines.Count)

    $tailLines = @()
    if ($spoolLines.Count -gt 0) {
        $tailStart = [Math]::Max(0, $spoolLines.Count - 200)
        $tailLines = $spoolLines[$tailStart..($spoolLines.Count - 1)]
    }
    $parsedTail = @()
    foreach ($line in $tailLines) {
        $obj = To-JsonLineObject -Line $line
        if ($obj) { $parsedTail += $obj }
    }

    $hooksSeen = @($parsedTail | ForEach-Object { $_.hook } | Where-Object { $_ } | Select-Object -Unique)
    if (($hooksSeen -contains "llm_input") -and ($hooksSeen -contains "llm_output")) {
        Add-Check "hook_spool.types" "PASS" ("seen=" + ($hooksSeen -join ","))
    }
    else {
        Add-Check "hook_spool.types" "FAIL" ("expected llm_input+llm_output, saw=" + ($hooksSeen -join ","))
    }

    if ($parsedTail.Count -gt 0) {
        $last = $parsedTail[-1]
        $lastTs = [double]($last.ts)
        $lastAge = Age-Seconds $lastTs
        if ($lastAge -le $HookFreshSeconds) {
            Add-Check "hook_spool.freshness" "PASS" ("last_hook=" + $last.hook + " age_sec=" + $lastAge)
        }
        else {
            Add-Check "hook_spool.freshness" "WARN" ("last_hook=" + $last.hook + " stale age_sec=" + $lastAge)
        }
    }
    else {
        Add-Check "hook_spool.freshness" "FAIL" "Spool file has no valid JSON rows."
    }
}

if (-not (Test-Path $queuePath)) {
    Add-Check "queue.exists" "FAIL" ("Missing queue file: " + $queuePath)
}
else {
    $qTail = Get-Content -Path $queuePath -Tail 6000
    $hookRows = @()
    foreach ($line in $qTail) {
        $obj = To-JsonLineObject -Line $line
        if (-not $obj) { continue }
        $payload = $null
        if ($obj.data) { $payload = $obj.data.payload }
        if ($payload -and $payload.type -eq "openclaw_hook") {
            $hookRows += $obj
        }
    }
    if ($hookRows.Count -eq 0) {
        Add-Check "queue.hook_ingest" "FAIL" "No openclaw_hook events in queue tail."
    }
    else {
        $lastQ = $hookRows[-1]
        $qAge = Age-Seconds ([double]$lastQ.timestamp)
        if ($qAge -le $HookFreshSeconds) {
            Add-Check "queue.hook_ingest" "PASS" ("recent rows=" + $hookRows.Count + " last_age_sec=" + $qAge)
        }
        else {
            Add-Check "queue.hook_ingest" "WARN" ("rows=" + $hookRows.Count + " last_age_sec=" + $qAge)
        }
    }
}

if (-not (Test-Path $cronJobsPath)) {
    Add-Check "cron.jobs" "FAIL" "Missing cron jobs file."
}
else {
    try {
        $cron = Get-Content -Path $cronJobsPath -Raw | ConvertFrom-Json
        $jobs = @($cron.jobs)
        $targetNames = @("spark-health-alert-watch", "spark-context-refresh")
        foreach ($jn in $targetNames) {
            $job = $jobs | Where-Object { $_.name -eq $jn } | Select-Object -First 1
            if (-not $job) {
                Add-Check ("cron.job." + $jn) "WARN" "Job not found."
                continue
            }
            if ($job.enabled -eq $true) {
                Add-Check ("cron.job." + $jn) "PASS" "enabled=true"
            }
            else {
                Add-Check ("cron.job." + $jn) "FAIL" "enabled=false"
            }

            $runPath = Join-Path $cronRunsDir ($job.id + ".jsonl")
            if (-not (Test-Path $runPath)) {
                Add-Check ("cron.run." + $jn) "WARN" "No runs file."
                continue
            }
            $runLines = Get-Content -Path $runPath
            if ($runLines.Count -eq 0) {
                Add-Check ("cron.run." + $jn) "WARN" "Runs file empty."
                continue
            }
            $lastRun = To-JsonLineObject -Line $runLines[-1]
            if (-not $lastRun) {
                Add-Check ("cron.run." + $jn) "WARN" "Invalid last run row."
                continue
            }
            $status = [string]$lastRun.status
            $tsMs = [double]($lastRun.ts)
            $ageMin = [Math]::Round((([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $tsMs) / 60000.0), 2)
            if ($status -eq "ok") {
                if ($ageMin -le $CronFreshMinutes) {
                    Add-Check ("cron.run." + $jn) "PASS" ("status=ok age_min=" + $ageMin)
                }
                else {
                    Add-Check ("cron.run." + $jn) "WARN" ("status=ok stale age_min=" + $ageMin)
                }
            }
            else {
                Add-Check ("cron.run." + $jn) "FAIL" ("status=" + $status + " age_min=" + $ageMin)
            }
        }
    }
    catch {
        Add-Check "cron.jobs" "FAIL" ("Cron parse failed: " + $_.Exception.Message)
    }
}

Write-Host ""
Write-Host "Post-Restart Smoke Check" -ForegroundColor Cyan
Write-Host "Repo: $repoRoot" -ForegroundColor DarkGray
Write-Host ""

foreach ($c in $checks) {
    $color = "White"
    if ($c.Status -eq "PASS") { $color = "Green" }
    elseif ($c.Status -eq "WARN") { $color = "Yellow" }
    elseif ($c.Status -eq "FAIL") { $color = "Red" }
    Write-Host ("[{0}] {1} :: {2}" -f $c.Status, $c.Name, $c.Detail) -ForegroundColor $color
}

$passCount = @($checks | Where-Object { $_.Status -eq "PASS" }).Count
$warnCount = @($checks | Where-Object { $_.Status -eq "WARN" }).Count
$failCount = @($checks | Where-Object { $_.Status -eq "FAIL" }).Count

Write-Host ""
Write-Host ("Summary: PASS={0} WARN={1} FAIL={2}" -f $passCount, $warnCount, $failCount) -ForegroundColor Cyan

if ($failCount -gt 0) {
    exit 1
}
exit 0
