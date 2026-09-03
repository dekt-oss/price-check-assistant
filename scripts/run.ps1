# Start the Streamlit app. The database is only needed for pages that read stored observations.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Environment not initialized. Run .\scripts\setup.ps1 first."
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        docker compose up -d db
    } else {
        Write-Host "Docker is not running. Starting Streamlit without the local database."
    }
}

& $python -m streamlit run Home.py
