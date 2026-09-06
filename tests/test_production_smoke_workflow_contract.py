from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "production-streamlit-smoke.yml"


def test_production_smoke_targets_public_streamlit_with_bounded_retry() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "https://bp-price-research.streamlit.app" in text
    assert "/_stcore/health" in text
    assert 'max_attempts=20' in text
    assert 'sleep_seconds=15' in text
    assert 'timeout-minutes: 8' in text
    assert 'health_code\" = \"200' in text
    assert 'root_code\" = \"200' in text


def test_production_smoke_does_not_claim_functional_market_validation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "deployment availability only" in text
    assert "does not validate live market-search results" in text
    assert "G2B_SERVICE_KEY" not in text
    assert "MFDS_SERVICE_KEY" not in text
