# Local development setup for Windows. Mirrors scripts/setup.sh.
#
# PostgreSQL is optional: tests, lint and the match benchmark all run without it. If Docker
# Desktop is not installed or not running, the database step is skipped with a message instead
# of failing the whole setup.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

function Get-PythonLauncherArgs {
    # The project supports Python 3.11+, so accept any 3.11 or newer interpreter the launcher
    # knows about instead of requiring exactly 3.11 to be installed.
    foreach ($candidate in @(@("-3.11"), @("-3.12"), @("-3.13"), @("-3"))) {
        $version = $null
        try {
            $version = & py @candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0 -and $version) {
            $parts = "$version".Trim().Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) {
                return $candidate
            }
        }
    }
    return $null
}

Write-Host "[1/5] Checking prerequisites..."
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher (py) not found. Install Python 3.11+ from python.org first."
}
$pythonArgs = Get-PythonLauncherArgs
if ($null -eq $pythonArgs) {
    throw "No Python 3.11+ interpreter found. Run 'py --list' to see what is installed."
}
Write-Host "  using: py $pythonArgs"

Write-Host "[2/5] Creating virtual environment..."
if (-not (Test-Path ".venv")) {
    & py @pythonArgs -m venv .venv
}
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -U pip
& $python -m pip install -e ".[dev]"

Write-Host "[3/5] Preparing environment file..."
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "  .env created from .env.example. Add DATA_GO_KR_SERVICE_KEY only for live G2B calls."
} else {
    Write-Host "  .env already exists; left untouched."
}

Write-Host "[4/5] Starting PostgreSQL (optional)..."
$dockerReady = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info *> $null
    $dockerReady = ($LASTEXITCODE -eq 0)
}

if ($dockerReady) {
    docker compose up -d db
    for ($i = 0; $i -lt 30; $i++) {
        $status = docker inspect --format='{{.State.Health.Status}}' purchase-price-postgres 2>$null
        if ($status -eq "healthy") { break }
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host "  Docker is unavailable. Checking DATABASE_URL for an already-running PostgreSQL."
}

# Decide from a real connection, so a locally installed PostgreSQL counts even without Docker.
& $python -c "import sys; from purchase_price.scripts.doctor import database_error; sys.exit(1 if database_error() else 0)"
if ($LASTEXITCODE -eq 0) {
    Write-Host "[5/5] Applying database migrations..."
    & $python -m purchase_price.scripts.init_db
    & $python -m purchase_price.scripts.seed_demo
} else {
    Write-Host "[5/5] No database reachable at DATABASE_URL. Skipping migrations."
    Write-Host "  Tests, lint and the match benchmark still run. The Streamlit demo pages need a database."
}

Write-Host ""
& $python -m purchase_price.scripts.doctor
Write-Host ""
Write-Host "Setup finished. Run checks with .\scripts\test.ps1, start the app with .\scripts\run.ps1"
