from pathlib import Path

WORKFLOW = Path(".github/workflows/track-b-r2-ground-truth-capture.yml")
SCRIPT = Path("src/purchase_price/scripts/capture_track_b_r2_ground_truth.py")


def test_r2_ground_truth_capture_is_read_only_and_quota_free() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "R2_ACCOUNT_ID" in text
    assert "R2_BUCKET" in text
    assert "R2_ACCESS_KEY_ID" in text
    assert "R2_SECRET_ACCESS_KEY" in text
    assert "G2B_SERVICE_KEY" not in text
    assert "DATA_GO_KR_SERVICE_KEY" not in text
    assert "G2B_RESEARCH_SERVICE_KEY" not in text
    assert "capture_track_b_r2_ground_truth" in text
    assert "track-b-r2-ground-truth-candidates" in text


def test_r2_ground_truth_capture_leaves_human_grade_blank() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '"expected_grade": ""' in text
    assert '"review_note": ""' in text
    assert '"g2b_live_api_requests": 0' in text
    assert '"predicted_grade_written": False' in text
    assert "identity_conflicts_excluded" in text
    assert "superseded_change_orders_excluded" in text
