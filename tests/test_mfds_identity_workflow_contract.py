from pathlib import Path


def test_mfds_identity_workflow_uses_checkpointed_stable_backfill_mode() -> None:
    text = Path(".github/workflows/mfds-identity-index.yml").read_text(encoding="utf-8")

    assert 'cron: "23 0 * * *"' in text
    assert 'cron: "23 12 * * *"' in text
    assert 'cron: "23 6 * * *"' in text
    assert 'cron: "23 18 * * *"' in text
    assert 'default: "5"' in text
    assert 'default: "200"' in text
    assert 'default: "100"' in text
    assert 'MFDS_BACKFILL_CHUNKS:' in text
    assert 'MFDS_BACKFILL_PAGES_PER_CHUNK:' in text
    assert 'MFDS_BACKFILL_ROWS_PER_PAGE:' in text
    assert 'plan_mfds_identity_collection' in text
    assert 'collection_mode' in text
    assert 'steps.plan.outputs.chunks' in text
    assert 'for chunk in $(seq 1 "$MFDS_EFFECTIVE_CHUNKS")' in text
    assert '--max-pages "$MFDS_EFFECTIVE_PAGES_PER_CHUNK"' in text
    assert '--rows-per-page "$MFDS_EFFECTIVE_ROWS_PER_PAGE"' in text
    assert 'sync-$chunk.json' in text
    assert 'if [ "$status" != "SUCCESS" ]; then' in text
    assert 'cycle_completed="$(python -c' in text
    assert 'if [ "$cycle_completed" = "true" ]; then' in text
    assert "cancel-in-progress: false" in text
    assert "timeout-minutes: 120" in text


def test_mfds_identity_workflow_reports_aggregate_progress() -> None:
    text = Path(".github/workflows/mfds-identity-index.yml").read_text(encoding="utf-8")

    assert 'collection_mode=' in text
    assert 'planned_chunks=' in text
    assert 'chunks_completed=' in text
    assert 'pages_collected=' in text
    assert 'rows_seen=' in text
    assert 'row_count=' in text
    assert 'next_page=' in text
    assert 'source_total_count=' in text
