param(
  [string]$RepoUrl = "https://github.com/vibeforge1111/vibeship-spark-intelligence.git",
  [string]$TargetDir = (Join-Path (Get-Location) "vibeship-spark-intelligence"),
  [switch]$SkipUp
)

$ErrorActionPreference = "Stop"
$script:MinimumPythonVersion = [Version]"3.10"
$script:BasePythonVersion = $null

function Invoke-External {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter()][string[]]$Arguments = @()
  )

  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    $joined = ($Arguments -join " ")
    throw ("Command failed ({0}): {1} {2}" -f $LASTEXITCODE, $FilePath, $joined)
  }
}

function Get-PythonVersion {
  param([Parameter(Mandatory = $true)][ValidateSet("py", "python")][string]$CommandName)

  try {
    if ($CommandName -eq "py") {
      $version = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
    } else {
      $version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
      return $null
    }
    return [Version]($version.Trim())
  } catch {
    return $null
  }
}

function Resolve-BasePython {
  $candidates = @()
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidates += "py"
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    $candidates += "python"
  }

  foreach ($candidate in $candidates) {
    $resolvedVersion = Get-PythonVersion -CommandName $candidate
    if ($resolvedVersion -and $resolvedVersion -ge $script:MinimumPythonVersion) {
      $script:BasePythonVersion = $resolvedVersion
      return $candidate
    }
  }

  return $null
}

function Install-LatestPython {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/ and re-run this installer."
  }

  Write-Host ("Python {0}+ not found. Installing latest Python 3 via winget..." -f $script:MinimumPythonVersion.ToString(2))

  $candidateIds = @()
  $searchOutput = & winget search --query "Python.Python.3" --source winget 2>$null
  if ($LASTEXITCODE -eq 0 -and $searchOutput) {
    $candidateIds = @(
      $searchOutput |
        Select-String -Pattern "Python\.Python\.3\.\d+" -AllMatches |
        ForEach-Object { $_.Matches.Value } |
        Sort-Object -Unique
    )
  }

  if (-not $candidateIds -or $candidateIds.Count -eq 0) {
    $candidateIds = @(
      "Python.Python.3.14",
      "Python.Python.3.13",
      "Python.Python.3.12",
      "Python.Python.3.11",
      "Python.Python.3.10"
    )
  }

  $installTargets = @(
    $candidateIds |
      Where-Object { [Version](($_ -replace "^Python\.Python\.", "")) -ge $script:MinimumPythonVersion } |
      Sort-Object { [Version](($_ -replace "^Python\.Python\.", "")) } -Descending
  )

  $installed = $false
  foreach ($packageId in $installTargets) {
    Write-Host ("Attempting winget install: {0}" -f $packageId)
    & winget install --id $packageId -e --silent --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
      $installed = $true
      break
    }
  }
  if (-not $installed) {
    throw "winget could not install a compatible Python version automatically. Install Python 3.10+ manually and re-run."
  }

  $launcherDir = Join-Path $env:LocalAppData "Programs\Python\Launcher"
  if (Test-Path (Join-Path $launcherDir "py.exe")) {
    $env:Path = "{0};{1}" -f $launcherDir, $env:Path
  }
}

function Invoke-BasePython {
  param([string[]]$Arguments)
  if ($script:BasePython -eq "py") {
    Invoke-External -FilePath "py" -Arguments (@("-3") + $Arguments)
    return
  }
  Invoke-External -FilePath "python" -Arguments $Arguments
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "Git is required but was not found in PATH."
}

$script:BasePython = Resolve-BasePython
if (-not $script:BasePython) {
  Install-LatestPython
  $script:BasePython = Resolve-BasePython
}
if (-not $script:BasePython) {
  throw ("Unable to locate Python {0}+ after installation attempt." -f $script:MinimumPythonVersion.ToString(2))
}

Write-Host "============================================="
Write-Host "  SPARK - Windows bootstrap"
Write-Host "============================================="
Write-Host ""
Write-Host ("Using Python {0} via '{1}'" -f $script:BasePythonVersion.ToString(3), $script:BasePython)

if (-not (Test-Path $TargetDir)) {
  Write-Host ("Cloning repo into: {0}" -f $TargetDir)
  Invoke-External -FilePath "git" -Arguments @("clone", $RepoUrl, $TargetDir)
} elseif (-not (Test-Path (Join-Path $TargetDir "pyproject.toml"))) {
  throw ("TargetDir exists but does not look like this repo: {0}" -f $TargetDir)
} else {
  Write-Host ("Using existing repo: {0}" -f $TargetDir)
}

Set-Location $TargetDir

Write-Host "Checking Python version..."
Invoke-BasePython -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)")

$venvPython = Join-Path $TargetDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Host "Creating virtual environment..."
  Invoke-BasePython -Arguments @("-m", "venv", ".venv")
}

Write-Host "Installing Spark (services extras)..."
Invoke-External -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-External -FilePath $venvPython -Arguments @("-m", "pip", "install", "-e", ".[services]")

if ($SkipUp) {
  Write-Host ""
  Write-Host "Install complete."
  Write-Host ("Start later with: {0} -m spark.cli onboard --quick --yes" -f $venvPython)
  exit 0
}

Write-Host ""
Invoke-External -FilePath $venvPython -Arguments @("-m", "spark.cli", "onboard", "--quick", "--yes")
