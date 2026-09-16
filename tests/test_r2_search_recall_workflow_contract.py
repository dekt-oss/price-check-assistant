from pathlib import Path


def test_recall_uat_workflow_is_read_only_and_uploads_evidence() -> None:
    text = Path(".github/workflows/r2-search-recall-uat.yml").read_text()

    assert "R2 Search Recall UAT" in text
    assert "workflow_dispatch:" in text
    assert "Measure Production R2 recall without writes" in text
    assert "measure_r2_search_recall" in text
    assert "r2-search-recall-uat" in text
    assert "sync_g2b_track_b_r2_index" not in text
    assert "run_g2b_track_b_daily" not in text
    assert "write_json" not in text
