from __future__ import annotations

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_pipeline_state import (
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_TARGET_CODE_COUNT,
    TrackBPipelineState,
)


def _summary(*, complete: bool = False) -> CollectionSummary:
    next_cursor = (
        CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
        if complete
        else CollectionCursor(4000, 1)
    )
    return CollectionSummary(
        status="SUCCESS" if complete else "PARTIAL_SUCCESS",
        started_at="2026-09-16T00:00:00+00:00",
        finished_at="2026-09-16T00:40:00+00:00",
        begin_date="2025-09-12",
        end_date="2026-09-11",
        target_segments=("42", "41", "43", "44", "23", "27", "46", "39"),
        target_code_count=EXPECTED_TARGET_CODE_COUNT,
        target_code_source="SNAPSHOT",
        target_code_snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        start_cursor=CollectionCursor(3196, 1),
        next_cursor=next_cursor,
        request_budget=900,
        dictionary_requests=0,
        track_b_requests=900,
        total_requests=900,
        codes_completed=804,
        pages_stored=900,
        rows_seen=12345,
        r2_objects_created=700,
        r2_objects_reused=200,
        r2_stored_bytes_created=456789,
        first_object_key="raw/v1/op/aa/bb/a.json.gz",
        last_object_key="raw/v1/op/cc/dd/c.json.gz",
        stop_reason="TARGET_COMPLETE" if complete else "REQUEST_BUDGET_EXHAUSTED",
    )


def test_pipeline_state_round_trip_and_manifest_deduplication() -> None:
    state = TrackBPipelineState.bootstrap()
    state.apply_collection(
        _summary(),
        object_keys=["raw/a.json.gz", "raw/a.json.gz", "raw/b.json.gz"],
    )
    restored = TrackBPipelineState.from_payload(state.to_payload())

    assert restored.collection_cursor == CollectionCursor(4000, 1)
    assert restored.pending_object_keys == ["raw/a.json.gz", "raw/b.json.gz"]
    assert restored.backfill_complete is False


def test_pipeline_marks_backfill_complete_only_at_terminal_cursor() -> None:
    state = TrackBPipelineState.bootstrap()
    state.apply_collection(_summary(complete=True), object_keys=[])

    assert state.backfill_complete is True
    assert state.collection_cursor == CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)


def test_db_bootstrap_completion_clears_manifest_covered_by_full_scan() -> None:
    state = TrackBPipelineState.bootstrap()
    state.pending_object_keys = ["raw/a.json.gz", "raw/b.json.gz"]
    state.mark_db_bootstrap_progress(cursor="raw/z.json.gz", complete=True)

    assert state.db_bootstrap_complete is True
    assert state.pending_object_keys == []
