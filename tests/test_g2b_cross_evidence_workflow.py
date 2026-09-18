from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cross_evidence_live_workflow_is_manual_bounded_and_two_source() -> None:
    text = (
        REPO_ROOT / ".github" / "workflows" / "g2b-cross-evidence-live.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "probe_g2b_cross_evidence" in text
    assert "--timeout-seconds 15" in text
    assert "--max-retries 1" in text
    assert "G2B_SHOPPING_SERVICE_KEY" in text
    assert "G2B_RESEARCH_SERVICE_KEY" in text
    assert "DATA_GO_KR_MARKET_SERVICE_KEY" in text
    assert "cross_evidence_rate" in text
    assert "g2b-cross-evidence-live" in text
