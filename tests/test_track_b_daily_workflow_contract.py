from pathlib import Path


def test_daily_workflow_keeps_quota_and_r2_guards() -> None:
    text = Path(".github/workflows/track-b-daily-backfill.yml").read_text()

    assert "name: Track B Daily Backfill" in text
    assert "pull_request:" in text
    assert "R2 and G2B secret readiness" in text
    assert "github.event_name == 'pull_request'" in text
    assert "github.event_name != 'pull_request'" in text
    assert "production_collection_contract=READY_R2" in text
    assert 'cron: "10 18 * * *"' in text
    assert "track-b-r2-pipeline" in text
    assert "track-b-daily-pr-{0}" in text
    assert "cancel-in-progress: false" in text
    assert "--request-budget \"${{ inputs.request_budget || '900' }}\"" in text
    assert "actions/artifacts/10320004586/zip" in text
    assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in text
    assert "DATABASE_URL" not in text
    assert "sync_g2b_track_b_postgres" not in text


def test_completed_backfill_switches_to_gap_safe_locked_rolling_window() -> None:
    text = Path("src/purchase_price/scripts/run_g2b_track_b_daily.py").read_text()
    state_text = Path("src/purchase_price/services/track_b_pipeline_state.py").read_text()

    assert '"ALREADY_COMPLETE"' not in text
    assert "ROLLING_WINDOW_DAYS = 7" in text
    assert 'ZoneInfo("Asia/Seoul")' in text
    assert "_next_rolling_window" in text
    assert '"catch_up"' in text
    assert '"recent_overlap"' in text
    assert "_run_rolling_collection" in text
    assert '"mode": "rolling_incremental"' in text
    assert "state.begin_rolling_cycle" in text
    assert "start_cursor=state.rolling_cursor" in text
    assert "apply_rolling_collection" in text
    assert "rolling_window_begin" in state_text
    assert "rolling_window_end" in state_text
    assert "rolling_covered_through" in state_text
    assert "rolling_cycles_completed" in state_text
