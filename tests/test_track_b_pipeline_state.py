from __future__ import annotations

from datetime import date

import pytest

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_pipeline_state import (
    BACKFILL_END_DATE,
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_TARGET_CODE_COUNT,
    ROLLING_BOOTSTRAP_CURSOR,
    TrackBPipelineState,
)


def _summary(
    *,
    complete: bool = False,
    begin_date: str = "2025-09-12",
    end_date: str = "2026-09-11",
    start_cursor: CollectionCursor = CollectionCursor(3196, 1),
    next_cursor: CollectionCursor | None = None,
) -> CollectionSummary:
    resolved_next = next_cursor or (
        CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
        if complete
        else CollectionCursor(4000, 1)
    )
    return CollectionSummary(
        status="SUCCESS" if complete else "PARTIAL_SUCCESS",
        started_at="2026-09-16T00:00:00+00:00",
        finished_at="2026-09-16T00:40:00+00:00",
        begin_date=begin_date,
        end_date=end_date,
        target_segments=("42", "41", "43", "44", "23", "27", "46", "39"),
        target_code_count=EXPECTED_TARGET_CODE_COUNT,
        target_code_source="SNAPSHOT",
        target_code_snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        start_cursor=start_cursor,
        next_cursor=resolved_next,
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
    assert restored.rolling_cursor == ROLLING_BOOTSTRAP_CURSOR
    assert restored.rolling_covered_through == BACKFILL_END_DATE


def test_pipeline_marks_backfill_complete_only_at_terminal_cursor() -> None:
    state = TrackBPipelineState.bootstrap()
    state.apply_collection(_summary(complete=True), object_keys=[])

    assert state.backfill_complete is True
    assert state.collection_cursor == CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    assert state.rolling_covered_through == BACKFILL_END_DATE


def test_legacy_payload_without_rolling_fields_remains_compatible() -> None:
    state = TrackBPipelineState.bootstrap()
    payload = state.to_payload()
    for key in (
        "rolling_cursor",
        "rolling_window_begin",
        "rolling_window_end",
        "rolling_covered_through",
        "rolling_cycles_completed",
        "last_rolling_collection",
    ):
        payload.pop(key)

    restored = TrackBPipelineState.from_payload(payload)

    assert restored.rolling_cursor == ROLLING_BOOTSTRAP_CURSOR
    assert restored.rolling_window_begin is None
    assert restored.rolling_window_end is None
    assert restored.rolling_covered_through == BACKFILL_END_DATE
    assert restored.rolling_cycles_completed == 0


def test_rolling_cycle_locks_window_and_advances_cursor_without_resetting_backfill() -> None:
    state = TrackBPipelineState.bootstrap()
    state.apply_collection(_summary(complete=True), object_keys=[])
    state.begin_rolling_cycle(begin=date(2026, 9, 10), end=date(2026, 9, 16))
    rolling_summary = _summary(
        begin_date="2026-09-10",
        end_date="2026-09-16",
        start_cursor=ROLLING_BOOTSTRAP_CURSOR,
        next_cursor=CollectionCursor(850, 1),
    )

    state.apply_rolling_collection(
        rolling_summary,
        object_keys=["raw/new.json.gz", "raw/new.json.gz"],
    )

    assert state.backfill_complete is True
    assert state.collection_cursor == CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    assert state.rolling_cursor == CollectionCursor(850, 1)
    assert state.rolling_window_begin == "2026-09-10"
    assert state.rolling_window_end == "2026-09-16"
    assert state.rolling_covered_through == BACKFILL_END_DATE
    assert state.pending_object_keys == ["raw/new.json.gz"]
    assert state.rolling_cycles_completed == 0


def test_rolling_cycle_advances_coverage_only_after_full_target_completion() -> None:
    state = TrackBPipelineState.bootstrap()
    state.apply_collection(_summary(complete=True), object_keys=[])
    state.begin_rolling_cycle(begin=date(2026, 9, 10), end=date(2026, 9, 16))
    rolling_summary = _summary(
        complete=True,
        begin_date="2026-09-10",
        end_date="2026-09-16",
        start_cursor=CollectionCursor(5000, 1),
    )

    state.apply_rolling_collection(rolling_summary, object_keys=[])

    assert state.rolling_cursor == ROLLING_BOOTSTRAP_CURSOR
    assert state.rolling_window_begin is None
    assert state.rolling_window_end is None
    assert state.rolling_covered_through == "2026-09-16"
    assert state.rolling_cycles_completed == 1
    assert state.last_rolling_collection is not None
    assert state.last_rolling_collection["cycle_complete"] is True
    assert state.last_rolling_collection["covered_through"] == "2026-09-16"


def test_rolling_collection_rejects_date_window_drift() -> None:
    state = TrackBPipelineState.bootstrap()
    state.apply_collection(_summary(complete=True), object_keys=[])
    state.begin_rolling_cycle(begin=date(2026, 9, 10), end=date(2026, 9, 16))

    with pytest.raises(ValueError, match="changed the active date window"):
        state.apply_rolling_collection(
            _summary(
                begin_date="2026-09-11",
                end_date="2026-09-17",
                start_cursor=ROLLING_BOOTSTRAP_CURSOR,
                next_cursor=CollectionCursor(850, 1),
            ),
            object_keys=[],
        )


def test_db_bootstrap_completion_clears_manifest_covered_by_full_scan() -> None:
    state = TrackBPipelineState.bootstrap()
    state.pending_object_keys = ["raw/a.json.gz", "raw/b.json.gz"]
    state.mark_db_bootstrap_progress(cursor="raw/z.json.gz", complete=True)

    assert state.db_bootstrap_complete is True
    assert state.pending_object_keys == []
