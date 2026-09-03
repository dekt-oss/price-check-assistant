#!/usr/bin/env bash
# Local development setup for Linux/macOS. Mirrors scripts/setup.ps1.
#
# PostgreSQL is optional: tests, lint and the match benchmark all run without it. If Docker is
# unavailable the database step is skipped with a message instead of failing the whole setup.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[1/5] Checking prerequisites..."
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "  $PYTHON_BIN not found. Install Python 3.11+ (or set PYTHON_BIN)." >&2
    exit 1
fi
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"  Python 3.11+ required, found {sys.version.split()[0]}")
PY
echo "  $("$PYTHON_BIN" --version)"

echo "[2/5] Creating virtual environment..."
[ -d .venv ] || "$PYTHON_BIN" -m venv .venv
./.venv/bin/python -m pip install -U pip >/dev/null
./.venv/bin/pip install -e ".[dev]"

echo "[3/5] Preparing environment file..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  .env created from .env.example. Add DATA_GO_KR_SERVICE_KEY only for live G2B calls."
else
    echo "  .env already exists; left untouched."
fi

echo "[4/5] Starting PostgreSQL (optional)..."
DB_READY=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker compose up -d db
    for _ in $(seq 1 30); do
        status="$(docker inspect --format='{{.State.Health.Status}}' purchase-price-postgres 2>/dev/null || true)"
        if [ "$status" = "healthy" ]; then DB_READY=1; break; fi
        sleep 2
    done
    [ "$DB_READY" = "1" ] || echo "  PostgreSQL did not become healthy. See: docker compose logs db"
else
    echo "  Docker is unavailable. Skipping the database."
    echo "  Point DATABASE_URL in .env at a local PostgreSQL 16 if you need the Streamlit demo."
fi

if [ "$DB_READY" = "1" ]; then
    echo "[5/5] Applying database migrations..."
    ./.venv/bin/python -m purchase_price.scripts.init_db
    ./.venv/bin/python -m purchase_price.scripts.seed_demo
else
    echo "[5/5] Skipping migrations because no database is reachable."
fi

echo
./.venv/bin/python -m purchase_price.scripts.doctor
echo
echo "Setup finished. Run checks with ./scripts/test.sh, start the app with ./scripts/run.sh"
