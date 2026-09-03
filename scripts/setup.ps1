# Local development setup for Windows. Mirrors scripts/setup.sh.
#
# PostgreSQL is optional: tests, lint and the match benchmark all run without it. If Docker
# Desktop is not installed or not running, the database step is skipped with a message instead
# of failing the whole setup.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "[1/5] Checking prerequisites..."
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher (py) not found. Install Python 3.11+ first."
}

Write-Host "[2/5] Creating virtual environment..."
if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -U pip
& .\.venv\Scripts\pip.exe install -e ".[dev]"

Write-Host "[3/5] Preparing environment file..."
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "  .env created from .env.example. Add DATA_GO_KR_SERVICE_KEY only for live G2B calls."
} else {
    Write-Host "  .env already exists; left untouched."
}

Write-Host "[4/5] Starting PostgreSQL (optional)..."
$dbReady = $false
$dockerReady = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info *> $null
    $dockerReady = ($LASTEXITCODE -eq 0)
}

if ($dockerReady) {
    docker compose up -d db
    for ($i = 0; $i -lt 30; $i++) {
        $status = docker inspect --format='{{.State.Health.Status}}' purchase-price-postgres 2>$null
        if ($status -eq "healthy") {
            $dbReady = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $dbReady) {
        Write-Warning "PostgreSQL did not become healthy. See: docker compose logs db"
    }
} else {
    Write-Host "  Docker is unavailable. Skipping the database."
    Write-Host "  Point DATABASE_URL in .env at a local PostgreSQL 16 if you need the Streamlit demo."
}

if ($dbReady) {
    Write-Host "[5/5] Applying database migrations..."
    & .\.venv\Scripts\python.exe -m purchase_price.scripts.init_db
    & .\.venv\Scripts\python.exe -m purchase_price.scripts.seed_demo
} else {
    Write-Host "[5/5] Skipping migrations because no database is reachable."
}

Write-Host ""
& .\.venv\Scripts\python.exe -m purchase_price.scripts.doctor
Write-Host ""
Write-Host "Setup finished. Run checks with .\scripts\test.ps1, start the app with .\scripts\run.ps1"
