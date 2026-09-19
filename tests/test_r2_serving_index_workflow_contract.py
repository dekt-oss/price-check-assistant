from pathlib import Path


def test_r2_serving_index_workflow_runs_after_daily_backfill() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert '"Track B Daily Backfill"' in text
    assert "sync_g2b_track_b_r2_index" in text
    assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in text
    assert "DATABASE_URL" not in text
    assert "track-b-r2-pipeline" in text
    assert "track-b-index-pr-{0}" in text
    assert "push:" in text
    assert "branches:" in text
    assert "- main" in text


def test_r2_serving_index_pr_gate_is_read_only_recovery_proof() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert "pull_request:" in text
    assert "recovery-readiness:" in text
    assert "Verify legacy state recovery proof without writing R2" in text
    assert "legacy_bootstrap_proof=" in text
    assert "Read-only transition status audit" in text
    assert "track-b-transition-readonly" in text
    assert "audit_track_b_transition" in text
    assert "state_store.write_json" not in text


def test_r2_serving_index_main_run_checks_flow_c_serving_path() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert "Verify R2 serving lookup with FLOW-C" in text
    assert 'model_name="FLOW-C"' in text
    assert "flow-c-serving-smoke.json" in text
    assert "candidate_count" in text
    assert "reference_count" in text
    assert 'blocked = {"unavailable", "not_ingested"}' in text


def test_serving_index_bootstrap_can_recover_validated_legacy_state() -> None:
    text = Path("src/purchase_price/scripts/sync_g2b_track_b_r2_index.py").read_text()

    assert "BOOTSTRAP_MIN_R2_OBJECTS" in text
    assert "BOOTSTRAP_LAST_OBJECT_KEY" in text
    assert "_load_or_bootstrap_pipeline_state" in text
    assert '"state_recovered"' in text
    assert "validated batch-004 bootstrap proof" in text


def test_home_is_unified_search_and_upload_entrypoint() -> None:
    page_text = Path("pages/1_대시보드.py").read_text()
    transaction_text = Path("src/purchase_price/ui/track_b_transactions.py").read_text()

    assert "무엇을 조사할까요?" in page_text
    assert "상세 검색조건" in page_text
    assert "home_quote_upload" in page_text
    assert 'st.switch_page("pages/2_견적_검토.py")' in page_text
    assert "lookup_track_b_quote_from_r2" in page_text
    assert "나라장터 거래가격" in page_text
    assert "transaction_rows(track_b)" in page_text
    assert "candidate_counts(track_b)" in page_text
    assert '"판매처"' in transaction_text
    assert '"구매처"' in transaction_text
    assert '"거래기록"' in transaction_text
    assert "상세 조사·근거 보기" in page_text
    assert "model_probe_query = model_probe_input.to_product_query()" in page_text
    assert "query = model_probe_query" in page_text


def test_r2_serving_index_run_audits_historical_to_rolling_transition() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text()

    assert "Audit historical to rolling transition" in text
    assert "audit_track_b_transition" in text
    assert "--require-serving-synced" in text
    assert "transition-audit.json" in text
    assert "acceptance_status=" in text
    assert "issue_157_acceptance=" in text
    assert "historical_remaining_codes=" in text
    assert "rolling_cycles_completed=" in text
