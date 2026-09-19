from pathlib import Path


def test_supplemental_workflow_is_bounded_and_serialized_with_base_pipeline() -> None:
    text = Path(".github/workflows/track-b-supplemental-collection.yml").read_text()

    assert "name: Track B Supplemental Collection" in text
    assert "Base Track B starts at 03:10 KST and has priority" in text
    assert 'cron: "40 19 * * *"' in text
    assert "'track-b-r2-pipeline'" in text
    assert "--request-budget" in text
    assert "inputs.request_budget || '25'" in text
    assert "MAX_SUPPLEMENTAL_REQUEST_BUDGET = 100" in Path(
        "src/purchase_price/scripts/run_g2b_track_b_supplemental.py"
    ).read_text()
    assert "BASE_HISTORICAL_BACKFILL_IN_PROGRESS" in Path(
        "src/purchase_price/scripts/run_g2b_track_b_supplemental.py"
    ).read_text()


def test_supplemental_uses_explicit_verified_codes_not_base_snapshot_mutation() -> None:
    text = Path("src/purchase_price/scripts/run_g2b_track_b_supplemental.py").read_text()

    assert "supplemental_verified_codes()" in text
    assert "explicit_target_codes=active_codes" in text
    assert "target_code_snapshot_path" not in text
    assert "SNAPSHOT_STATE_NAME" not in text


def test_serving_index_consumes_base_and_supplemental_pending_keys() -> None:
    text = Path("src/purchase_price/scripts/sync_g2b_track_b_r2_index.py").read_text()
    workflow = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert "SUPPLEMENTAL_STATE_NAME" in text
    assert "supplemental_indexed_keys" in text
    assert "[*base_indexed_keys, *supplemental_indexed_keys]" in text
    assert "supplemental.mark_pending_indexed" in text
    assert '"Track B Supplemental Collection"' in workflow


def test_serving_index_has_supplemental_cx30n_acceptance_smoke() -> None:
    workflow = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert "Verify supplemental CX30N serving acceptance" in workflow
    assert 'target_code = "4511181101"' in workflow
    assert 'model_name="CX30N"' in workflow
    assert 'manufacturer="WIDE"' in workflow
    assert '"unavailable", "not_ingested"' in workflow
    assert "cx30n-supplemental-serving-smoke.json" in workflow
