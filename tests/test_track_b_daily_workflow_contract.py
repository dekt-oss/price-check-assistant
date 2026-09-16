from pathlib import Path


def test_daily_workflow_keeps_quota_checkpoint_and_db_guards() -> None:
    text = Path(".github/workflows/track-b-daily-backfill-postgres.yml").read_text()

    assert "pull_request:" in text
    assert "production secret readiness" in text
    assert "github.event_name == 'pull_request'" in text
    assert "github.event_name != 'pull_request'" in text
    assert "production_secret_contract=READY_" in text
    assert "READY_NO_DATABASE" not in text  # status is composed at runtime, not hard-coded.
    assert "DATABASE_URL_MISSING" in text
    assert "SKIP_POSTGRES_SYNC=1" in text
    assert "collection_continues" in text
    assert "env.SKIP_POSTGRES_SYNC != '1'" in text
    assert 'cron: "10 18 * * *"' in text
    assert "group: track-b-daily-backfill-postgres" in text
    assert "cancel-in-progress: false" in text
    assert "--request-budget \"${{ inputs.request_budget || '900' }}\"" in text
    assert "actions/artifacts/10320004586/zip" in text
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in text
    assert "alembic upgrade head" in text
    assert "sync_g2b_track_b_postgres" in text
