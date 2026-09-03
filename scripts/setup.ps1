$ErrorActionPreference = "Stop"

Write-Host "[1/5] Checking prerequisites..."
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher (py) not found. Install Python 3.11+ first."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker not found. Install/start Docker Desktop first."
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
}

Write-Host "[4/5] Starting PostgreSQL..."
docker compose up -d db

Write-Host "Waiting for PostgreSQL health check..."
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    $status = docker inspect --format='{{.State.Health.Status}}' purchase-price-postgres 2>$null
    if ($status -eq "healthy") {
        $healthy = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    throw "PostgreSQL did not become healthy. Run 'docker compose logs db'."
}

Write-Host "[5/5] Applying database migrations..."
& .\.venv\Scripts\python.exe -m purchase_price.scripts.init_db
& .\.venv\Scripts\python.exe -m purchase_price.scripts.seed_demo

Write-Host "Setup complete. Run: .\scripts\run.ps1"
