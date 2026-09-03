$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv\Scripts\streamlit.exe")) {
    throw "Environment not initialized. Run .\scripts\setup.ps1 first."
}

docker compose up -d db
& .\.venv\Scripts\streamlit.exe run Home.py
