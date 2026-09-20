from pathlib import Path


def test_supplemental_workflow_is_bounded_and_serialized_with_track_b_pipeline() -> None:
    text = Path(".github/workflows/track-b-supplemental.yml").read_text()

    assert "name: Track B Supplemental Collection" in text
    assert 'cron: "40 19 * * *"' in text
    assert "track-b-r2-pipeline" in text
    assert "request_budget" in text
    assert "'50'" in text
    assert "run_g2b_track_b_supplemental" in text
    assert "DATABASE_URL" not in text


def test_serving_index_runs_after_supplemental_collection() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert '"Track B Supplemental Collection"' in text
    assert "track_b_supplemental_state.py" in text


def test_supplemental_runner_keeps_base_snapshot_out_of_scope() -> None:
    text = Path("src/purchase_price/scripts/run_g2b_track_b_supplemental.py").read_text()

    assert "supplemental_verified_codes()" in text
    assert "explicit_target_codes=codes" in text
    assert "SUPPLEMENTAL_STATE_NAME" in text
    assert "EXPECTED_TARGET_CODE_COUNT" not in text
    assert "SNAPSHOT_STATE_NAME" not in text


def test_serving_sync_unions_base_and_supplemental_pending_keys() -> None:
    text = Path("src/purchase_price/scripts/sync_g2b_track_b_r2_index.py").read_text()

    assert "supplemental_pending_keys" in text
    assert "base_pending_keys" in text
    assert "SUPPLEMENTAL_STATE_NAME" in text
    assert "[*base_pending_keys, *supplemental_pending_keys]" in text
