from __future__ import annotations

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.scripts.run_g2b_track_b_supplemental import verified_supplemental_codes
from purchase_price.services.track_b_pipeline_state import BACKFILL_END_DATE
from purchase_price.services.track_b_supplemental_state import TrackBSupplementalState


def _summary(
    *,
    target_count: int,
    next_cursor: CollectionCursor,
    stop_reason: str = "TARGET_COMPLETE",
    begin_date: str = "2025-09-12",
    end_date: str = "2026-09-11",
) -> CollectionSummary:
    return CollectionSummary(
        status="SUCCESS",
        started_at="2026-09-19T00:00:00+00:00",
        finished_at="2026-09-19T00:00:01+00:00",
        begin_date=begin_date,
        end_date=end_date,
        target_segments=("45",),
        target_code_count=target_count,
        target_code_source="EXPLICIT_CODES",
        target_code_snapshot_sha256=None,
        start_cursor=CollectionCursor(0, 1),
        next_cursor=next_cursor,
        request_budget=25,
        dictionary_requests=0,
        track_b_requests=1,
        total_requests=1,
        codes_completed=1,
        pages_stored=1,
        rows_seen=1,
        r2_objects_created=1,
        r2_objects_reused=0,
        r2_stored_bytes_created=100,
        first_object_key="raw/a.json.gz",
        last_object_key="raw/a.json.gz",
        stop_reason=stop_reason,
    )


def test_verified_supplemental_codes_are_only_verified_codes_outside_base_segments() -> None:
    assert verified_supplemental_codes() == ("4511181101",)


def test_supplemental_historical_completion_is_isolated_from_base_state() -> None:
    state = TrackBSupplementalState.bootstrap(("4511181101",))

    state.apply_historical_collection(
        _summary(target_count=1, next_cursor=CollectionCursor(1, 1))
    )

    assert state.historical_complete is True
    assert state.historical_cursor == CollectionCursor(1, 1)
    assert state.rolling_covered_through == BACKFILL_END_DATE


def test_appending_verified_code_reopens_historical_and_resets_supplemental_rolling() -> None:
    state = TrackBSupplementalState.bootstrap(("4511181101",))
    state.apply_historical_collection(
        _summary(target_count=1, next_cursor=CollectionCursor(1, 1))
    )
    state.rolling_covered_through = "2026-09-18"
    state.rolling_cycles_completed = 1

    state.reconcile_target_codes(("4511181101", "4599999999"))

    assert state.target_codes == ("4511181101", "4599999999")
    assert state.historical_complete is False
    assert state.historical_cursor == CollectionCursor(1, 1)
    assert state.rolling_cursor == CollectionCursor(0, 1)
    assert state.rolling_covered_through == BACKFILL_END_DATE
    assert state.rolling_cycles_completed == 0


def test_removing_verified_supplemental_code_fails_closed() -> None:
    state = TrackBSupplementalState.bootstrap(("4511181101", "4599999999"))

    try:
        state.reconcile_target_codes(("4511181101",))
    except ValueError as exc:
        assert "explicit state migration" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("supplemental code removal was silently accepted")


def test_supplemental_rolling_cycle_advances_only_after_all_explicit_codes_complete() -> None:
    state = TrackBSupplementalState.bootstrap(("4511181101",))
    state.apply_historical_collection(
        _summary(target_count=1, next_cursor=CollectionCursor(1, 1))
    )
    state.begin_rolling_cycle(
        begin=__import__("datetime").date(2026, 9, 12),
        end=__import__("datetime").date(2026, 9, 18),
    )

    state.apply_rolling_collection(
        _summary(
            target_count=1,
            next_cursor=CollectionCursor(1, 1),
            begin_date="2026-09-12",
            end_date="2026-09-18",
        )
    )

    assert state.rolling_covered_through == "2026-09-18"
    assert state.rolling_cycles_completed == 1
    assert state.rolling_cursor == CollectionCursor(0, 1)
