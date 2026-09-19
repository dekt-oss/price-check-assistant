from types import SimpleNamespace

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor
from purchase_price.services.track_b_supplemental_state import (
    SUPPLEMENTAL_BOOTSTRAP_CURSOR,
    TrackBSupplementalState,
)


def _summary(
    *,
    status: str = "SUCCESS",
    next_cursor: CollectionCursor = CollectionCursor(1, 1),
    target_code_count: int = 1,
    target_segments: tuple[str, ...] = ("45",),
):
    return SimpleNamespace(
        status=status,
        finished_at="2026-09-19T00:00:00+00:00",
        begin_date="2025-09-12",
        end_date="2026-09-11",
        start_cursor=CollectionCursor(0, 1),
        next_cursor=next_cursor,
        target_code_count=target_code_count,
        target_segments=target_segments,
        track_b_requests=1,
        pages_stored=1,
        rows_seen=2,
        stop_reason="TARGET_COMPLETE",
        error_type=None,
        error_message=None,
    )


def test_historical_cycle_completes_without_touching_base_cursor_contract() -> None:
    state = TrackBSupplementalState()
    state.begin_historical(("4511181101",))

    state.apply_collection(
        _summary(),
        object_keys=["raw/v1/getSpcifyPrdlstPrcureInfoList-page/aa/" + "a" * 62 + ".json.gz"],
    )

    assert state.historical_completed_codes == ["4511181101"]
    assert state.active_mode is None
    assert state.active_codes == []
    assert state.cursor == SUPPLEMENTAL_BOOTSTRAP_CURSOR
    assert len(state.pending_object_keys) == 1
    assert state.last_collection is not None
    assert state.last_collection["target_codes"] == ["4511181101"]
    assert state.last_collection["cycle_complete"] is True


def test_partial_cycle_keeps_locked_targets_and_resume_cursor() -> None:
    state = TrackBSupplementalState()
    state.begin_historical(("4511181101",))

    state.apply_collection(
        _summary(
            status="PARTIAL_SUCCESS",
            next_cursor=CollectionCursor(0, 2),
        ),
        object_keys=[],
    )

    assert state.active_mode == "historical"
    assert state.active_codes == ["4511181101"]
    assert state.cursor == CollectionCursor(0, 2)
    assert state.historical_completed_codes == []


def test_new_verified_code_is_backfilled_after_prior_historical_completion() -> None:
    state = TrackBSupplementalState(historical_completed_codes=["4511181101"])

    assert state.missing_historical_codes(("4511181101", "4511181102")) == ("4511181102",)


def test_rolling_completion_advances_independent_coverage() -> None:
    state = TrackBSupplementalState(historical_completed_codes=["4511181101"])
    state.begin_rolling(
        ("4511181101",),
        begin=__import__("datetime").date(2026, 9, 12),
        end=__import__("datetime").date(2026, 9, 18),
    )

    summary = _summary()
    summary.begin_date = "2026-09-12"
    summary.end_date = "2026-09-18"
    state.apply_collection(summary, object_keys=[])

    assert state.active_mode is None
    assert state.rolling_covered_through == "2026-09-18"
    assert state.rolling_cycles_completed == 1


def test_serving_sync_clears_only_acknowledged_pending_keys() -> None:
    first = "raw/v1/getSpcifyPrdlstPrcureInfoList-page/aa/" + "a" * 62 + ".json.gz"
    second = "raw/v1/getSpcifyPrdlstPrcureInfoList-page/bb/" + "b" * 62 + ".json.gz"
    state = TrackBSupplementalState(pending_object_keys=[first, second])

    state.mark_pending_indexed([first], {"inserted": 2})

    assert state.pending_object_keys == [second]
    assert state.last_serving_index_sync == {"inserted": 2}


def test_state_payload_round_trip_preserves_separate_cursor() -> None:
    state = TrackBSupplementalState()
    state.begin_historical(("4511181101",))
    state.cursor = CollectionCursor(0, 3)

    restored = TrackBSupplementalState.from_payload(state.to_payload())

    assert restored.active_mode == "historical"
    assert restored.active_codes == ["4511181101"]
    assert restored.cursor == CollectionCursor(0, 3)
