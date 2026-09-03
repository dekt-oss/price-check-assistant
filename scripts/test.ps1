$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Environment not initialized. Run .\scripts\setup.ps1 first."
}
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\ruff.exe check .
