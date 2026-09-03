#!/usr/bin/env bash
# Start the Streamlit app. The database is only needed for pages that read stored observations.
set -euo pipefail

cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/streamlit ]; then
    echo "Environment not initialized. Run ./scripts/setup.sh first." >&2
    exit 1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker compose up -d db
fi

exec ./.venv/bin/streamlit run Home.py
