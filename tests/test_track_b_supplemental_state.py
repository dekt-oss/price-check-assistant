from datetime import date

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_supplemental_state import (
    SUPPLEMENTAL_ROLLING_CURSOR,
    SupplementalTrackBState,
)


def _summary(*, next_cursor: CollectionCursor, stop_reason: str = "TARGET_COMPLETE"):
    return CollectionSummary(
        status="SUCCESS",
        started_at="2026-09-20T00:00:00+00:00",
        finished_at="2026-09-20T00:01:00+00:00",
        begin_date="2025-09-12",
        end_date="2026-09-11",
        target_segments=("45",),
        target_code_count=1,
        target_code_source="EXPLICIT_VERIFIED",
        target_code_snapshot_sha256="a" * 64,
        start_cursor=CollectionCursor(0, 1),
        next_cursor=next_cursor,
        request_budget=50,
        dictionary_requests=0,
        track_b_requests=1,
        total_requests=1,
        codes_completed=1 if next_cursor.code_index == 1 else 0,
        pages_stored=1,
        rows_seen=2,
        r2_objects_created=1,
        r2_objects_reused=0,
        r2_stored_bytes_created=100,
        first_object_key="raw/key",
        last_object_key="raw/key",
        stop_reason=stop_reason,
    )


def test_historical_completion_keeps_state_isolated_and_tracks_pending() -> None:
    state = SupplementalTrackBState.bootstrap(("4511181101",))
    state.apply_historical(_summary(next_cursor=CollectionCursor(1, 1)), object_keys=["raw/key"])

    assert state.backfill_complete is True
    assert state.collection_cursor == CollectionCursor(1, 1)
    assert state.pending_object_keys == ["raw/key"]


def test_completed_state_can_reconcile_new_verified_target_set_by_rebackfilling() -> None:
    state = SupplementalTrackBState.bootstrap(("4511181101",))
    state.backfill_complete = True
    state.collection_cursor = CollectionCursor(1, 1)

    state.reconcile_targets(("4511181101", "4710000001"))

    assert state.backfill_complete is False
    assert state.collection_cursor == SUPPLEMENTAL_ROLLING_CURSOR
    assert state.target_codes == ("4511181101", "4710000001")


def test_incomplete_state_rejects_target_set_drift() -> None:
    state = SupplementalTrackBState.bootstrap(("4511181101",))

    try:
        state.reconcile_targets(("4511181101", "4710000001"))
    except ValueError as exc:
        assert "incomplete historical backfill" in str(exc)
    else:
        raise AssertionError("in-flight target drift must fail closed")


def test_rolling_completion_advances_covered_through() -> None:
    state = SupplementalTrackBState.bootstrap(("4511181101",))
    state.backfill_complete = True
    state.begin_rolling(begin=date(2026, 9, 12), end=date(2026, 9, 18))
    summary = _summary(next_cursor=CollectionCursor(1, 1))
    summary = CollectionSummary(**{**summary.__dict__, "begin_date": "2026-09-12", "end_date": "2026-09-18"})

    state.apply_rolling(summary, object_keys=["raw/rolling"])

    assert state.rolling_covered_through == "2026-09-18"
    assert state.rolling_cycles_completed == 1
    assert state.rolling_window_begin is None
    assert state.rolling_cursor == SUPPLEMENTAL_ROLLING_CURSOR


def _rolling_state(covered_through: str) -> SupplementalTrackBState:
    state = SupplementalTrackBState.bootstrap(("4511181101",))
    state.apply_historical(_summary(next_cursor=CollectionCursor(1, 1)), object_keys=[])
    state.rolling_covered_through = covered_through
    return state


def test_rolling_window_catches_up_a_missed_week_in_one_run() -> None:
    from purchase_price.scripts.run_g2b_track_b_supplemental import _rolling_window

    state = _rolling_state("2026-10-02")
    assert _rolling_window(state, today=date(2026, 10, 21)) == (
        date(2026, 10, 3),
        date(2026, 10, 21),
    )


def test_rolling_window_replays_the_last_week_when_current() -> None:
    from purchase_price.scripts.run_g2b_track_b_supplemental import _rolling_window

    state = _rolling_state("2026-10-20")
    assert _rolling_window(state, today=date(2026, 10, 21)) == (
        date(2026, 10, 15),
        date(2026, 10, 21),
    )
    assert _rolling_window(state, today=date(2026, 10, 20)) is None


def test_rolling_window_never_exceeds_the_one_year_api_limit() -> None:
    from purchase_price.scripts.run_g2b_track_b_supplemental import _rolling_window

    begin, end = _rolling_window(_rolling_state("2025-01-01"), today=date(2026, 10, 21))
    assert begin == date(2025, 1, 2)
    assert (end - begin).days == 364
