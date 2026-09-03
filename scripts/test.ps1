# Run exactly what CI runs, so a local pass means the pull request passes.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Environment not initialized. Run .\scripts\setup.ps1 first."
}

& .\.venv\Scripts\ruff.exe check .
if ($LASTEXITCODE -ne 0) { throw "ruff failed" }

& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

& .\.venv\Scripts\python.exe -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch
if ($LASTEXITCODE -ne 0) { throw "match benchmark disagrees with the human-reviewed ground truth" }
