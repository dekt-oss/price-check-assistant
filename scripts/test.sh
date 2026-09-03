#!/usr/bin/env bash
# Run exactly what CI runs, so a local pass means the pull request passes.
set -euo pipefail

cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    echo "Environment not initialized. Run ./scripts/setup.sh first." >&2
    exit 1
fi

./.venv/bin/ruff check .
./.venv/bin/python -m pytest -q
./.venv/bin/python -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch
