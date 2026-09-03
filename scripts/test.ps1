# Run exactly what CI runs, so a local pass means the pull request passes.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Environment not initialized. Run .\scripts\setup.ps1 first."
}

& $python -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff found issues" }

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

& $python -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch
if ($LASTEXITCODE -ne 0) { throw "match benchmark disagrees with the human-reviewed ground truth" }
