from __future__ import annotations

from datetime import date

from purchase_price.scripts.audit_track_b_transition import audit_transition
from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor
from purchase_price.services.track_b_pipeline_state import (
    EXPECTED_TARGET_CODE_COUNT,
    TrackBPipelineState,
)
from purchase_price.services.track_b_supplemental_state import SupplementalTrackBState


def _pointer(
    code_index: int,
    page_no: int = 1,
    row_count: int = 100,
    supplemental_target_count: int = 0,
) -> dict:
    return {
        "collection_cursor": {"code_index": code_index, "page_no": page_no},
        "row_count": row_count,
        "supplemental_target_count": supplemental_target_count,
    }


def test_historical_progress_is_valid_but_not_accepted() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(4180, 1)
    state.pending_object_keys = []

    report = audit_transition(
        state,
        serving_pointer=_pointer(4180),
        today=date(2026, 9, 18),
        require_serving_synced=True,
    )

    assert report["status"] == "pass"
    assert report["phase"] == "historical_progress"
    assert report["acceptance_status"] == "HISTORICAL_IN_PROGRESS"
    assert report["issue_157_acceptance"] is False
    assert report["historical"]["remaining_codes"] == 1028


def test_completed_historical_waits_for_first_rolling_cycle() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    state.backfill_complete = True

    report = audit_transition(
        state,
        serving_pointer=_pointer(EXPECTED_TARGET_CODE_COUNT),
        today=date(2026, 9, 18),
        require_serving_synced=True,
    )

    assert report["status"] == "pass"
    assert report["phase"] == "historical_complete_waiting_rolling"
    assert report["acceptance_status"] == "HISTORICAL_COMPLETE_WAITING_FIRST_ROLLING"
    assert report["historical"]["remaining_codes"] == 0
    assert report["issue_157_acceptance"] is False


def test_active_rolling_window_marks_transition_started_not_accepted() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    state.backfill_complete = True
    state.rolling_window_begin = "2026-09-12"
    state.rolling_window_end = "2026-09-18"
    state.rolling_cursor = CollectionCursor(900, 1)

    report = audit_transition(
        state,
        serving_pointer=_pointer(EXPECTED_TARGET_CODE_COUNT),
        today=date(2026, 9, 18),
        require_serving_synced=True,
    )

    assert report["status"] == "pass"
    assert report["phase"] == "rolling_in_progress"
    assert report["acceptance_status"] == "ROLLING_STARTED"
    assert report["rolling"]["active_window"] is True
    assert report["issue_157_acceptance"] is False


def test_completed_rolling_cycle_is_final_acceptance() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    state.backfill_complete = True
    state.rolling_cycles_completed = 1
    state.rolling_covered_through = "2026-09-18"
    state.last_rolling_collection = {
        "cycle_complete": True,
        "stop_reason": "TARGET_COMPLETE",
        "finished_at": "2026-09-18T03:00:00+00:00",
    }

    report = audit_transition(
        state,
        serving_pointer=_pointer(EXPECTED_TARGET_CODE_COUNT),
        today=date(2026, 9, 18),
        require_serving_synced=True,
    )

    assert report["status"] == "pass"
    assert report["phase"] == "rolling_operational"
    assert report["acceptance_status"] == "ROLLING_ACCEPTED"
    assert report["issue_157_acceptance"] is True
    assert report["rolling"]["lag_days"] == 0


def test_completion_flag_cursor_mismatch_fails_closed() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    state.backfill_complete = False

    report = audit_transition(
        state,
        serving_pointer=_pointer(EXPECTED_TARGET_CODE_COUNT),
        today=date(2026, 9, 18),
    )

    assert report["status"] == "fail"
    assert any("completion flag" in error for error in report["errors"])


def test_serving_sync_requirement_fails_on_pointer_lag_or_pending_objects() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(4180, 1)
    state.pending_object_keys = ["raw/v1/test.json.gz"]

    report = audit_transition(
        state,
        serving_pointer=_pointer(3280),
        today=date(2026, 9, 18),
        require_serving_synced=True,
    )

    assert report["status"] == "fail"
    assert report["serving_index"]["historical_cursor_matches_pointer"] is False
    assert report["serving_index"]["pending_object_count"] == 1
    assert any("behind" in error for error in report["errors"])
    assert any("pending raw objects" in error for error in report["errors"])


def test_pending_objects_are_warning_before_serving_sync() -> None:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(4180, 1)
    state.pending_object_keys = ["raw/v1/test.json.gz"]

    report = audit_transition(
        state,
        serving_pointer=_pointer(3280),
        today=date(2026, 9, 18),
        require_serving_synced=False,
    )

    assert report["status"] == "pass"
    assert report["warnings"]


def _accepted_base_state() -> TrackBPipelineState:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    state.backfill_complete = True
    state.rolling_cycles_completed = 1
    state.rolling_covered_through = "2026-09-18"
    state.last_rolling_collection = {
        "cycle_complete": True,
        "stop_reason": "TARGET_COMPLETE",
        "finished_at": "2026-09-18T03:00:00+00:00",
    }
    return state


def _completed_supplemental_state() -> SupplementalTrackBState:
    state = SupplementalTrackBState.bootstrap(("4511181101",))
    state.collection_cursor = CollectionCursor(1, 1)
    state.backfill_complete = True
    return state


def test_operational_acceptance_waits_for_supplemental_lane() -> None:
    report = audit_transition(
        _accepted_base_state(),
        serving_pointer=_pointer(EXPECTED_TARGET_CODE_COUNT),
        today=date(2026, 9, 18),
        require_serving_synced=True,
    )

    assert report["status"] == "pass"
    assert report["issue_157_acceptance"] is True
    assert report["operational_acceptance"] is False
    assert report["supplemental"]["phase"] == "not_started"


def test_operational_acceptance_requires_supplemental_serving_sync() -> None:
    supplemental = _completed_supplemental_state()
    supplemental.pending_object_keys = ["raw/v1/supplemental.json.gz"]

    report = audit_transition(
        _accepted_base_state(),
        serving_pointer=_pointer(
            EXPECTED_TARGET_CODE_COUNT,
            supplemental_target_count=1,
        ),
        today=date(2026, 9, 18),
        require_serving_synced=True,
        supplemental_state=supplemental,
    )

    assert report["status"] == "fail"
    assert report["operational_acceptance"] is False
    assert report["supplemental"]["pending_object_count"] == 1
    assert any("supplemental pending raw objects" in error for error in report["errors"])


def test_operational_acceptance_passes_after_supplemental_index_sync() -> None:
    supplemental = _completed_supplemental_state()

    report = audit_transition(
        _accepted_base_state(),
        serving_pointer=_pointer(
            EXPECTED_TARGET_CODE_COUNT,
            supplemental_target_count=1,
        ),
        today=date(2026, 9, 18),
        require_serving_synced=True,
        supplemental_state=supplemental,
    )

    assert report["status"] == "pass"
    assert report["issue_157_acceptance"] is True
    assert report["operational_acceptance"] is True
    assert report["supplemental"]["backfill_complete"] is True
    assert report["supplemental"]["serving_ready"] is True


def test_supplemental_pointer_target_count_mismatch_fails_closed() -> None:
    report = audit_transition(
        _accepted_base_state(),
        serving_pointer=_pointer(
            EXPECTED_TARGET_CODE_COUNT,
            supplemental_target_count=0,
        ),
        today=date(2026, 9, 18),
        require_serving_synced=True,
        supplemental_state=_completed_supplemental_state(),
    )

    assert report["status"] == "fail"
    assert report["operational_acceptance"] is False
    assert any("supplemental target count" in error for error in report["errors"])
