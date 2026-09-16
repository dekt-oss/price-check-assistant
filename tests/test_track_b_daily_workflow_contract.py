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
    assert "group: track-b-r2-pipeline" in text
    assert "cancel-in-progress: false" in text
    assert "--request-budget \"${{ inputs.request_budget || '900' }}\"" in text
    assert "actions/artifacts/10320004586/zip" in text
    assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in text
    assert "DATABASE_URL" not in text
    assert "sync_g2b_track_b_postgres" not in text
