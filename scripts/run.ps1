# Start the Streamlit app. The database is only needed for pages that read stored observations.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv\Scripts\streamlit.exe")) {
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

& .\.venv\Scripts\streamlit.exe run Home.py
