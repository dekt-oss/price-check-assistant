from pathlib import Path


def test_daily_workflow_keeps_quota_checkpoint_and_db_guards() -> None:
    text = Path(".github/workflows/track-b-daily-backfill-postgres.yml").read_text()

    assert 'cron: "10 18 * * *"' in text
    assert "group: track-b-daily-backfill-postgres" in text
    assert "cancel-in-progress: false" in text
    assert "--request-budget \"${{ inputs.request_budget || '900' }}\"" in text
    assert "actions/artifacts/10320004586/zip" in text
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in text
    assert "alembic upgrade head" in text
    assert "sync_g2b_track_b_postgres" in text
