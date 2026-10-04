from purchase_price.services.mfds_identity_status import (
    build_mfds_identity_collection_status,
    choose_mfds_collection_plan,
)


def test_collection_status_reports_backfill_progress_from_persisted_cycle_rows() -> None:
    status = build_mfds_identity_collection_status(
        pointer={
            "row_count": 279417,
            "updated_at": "2026-09-27T06:24:45+00:00",
            "stored_bytes": 21758693,
        },
        pipeline={
            "next_page": 2801,
            "cycle": 1,
            "complete_cycles": 0,
            "last_total_count": 2704269,
            "cycle_rows_seen": 280000,
            "rows_per_page": 100,
        },
    )

    assert status.mode == "backfill"
    assert status.first_backfill_complete is False
    assert status.row_count == 279417
    assert status.next_page == 2801
    assert status.progress_percent is not None
    assert 10.3 < status.progress_percent < 10.4


def test_collection_status_reports_completed_backfill_as_rolling_refresh() -> None:
    status = build_mfds_identity_collection_status(
        pointer={"row_count": 2600000},
        pipeline={
            "next_page": 1,
            "cycle": 2,
            "complete_cycles": 1,
            "verified_complete_cycles": 1,
            "last_total_count": 2704269,
            "cycle_rows_seen": 0,
            "rows_per_page": 100,
        },
    )

    assert status.mode == "rolling_refresh"
    assert status.first_backfill_complete is True
    assert status.progress_percent == 100.0


def test_collection_plan_uses_two_daily_slots_only_during_first_backfill() -> None:
    primary = choose_mfds_collection_plan(
        complete_cycles=0,
        event_name="schedule",
        schedule="23 0 * * *",
    )
    secondary = choose_mfds_collection_plan(
        complete_cycles=0,
        event_name="schedule",
        schedule="23 12 * * *",
    )

    assert primary.mode == "backfill"
    assert primary.chunks == 5
    assert secondary.mode == "backfill"
    assert secondary.chunks == 5


def test_collection_plan_auto_throttles_after_first_full_cycle() -> None:
    primary = choose_mfds_collection_plan(
        complete_cycles=1,
        event_name="schedule",
        schedule="23 0 * * *",
    )
    secondary = choose_mfds_collection_plan(
        complete_cycles=1,
        event_name="schedule",
        schedule="23 12 * * *",
    )

    assert primary.mode == "rolling_refresh"
    assert primary.chunks == 1
    assert primary.pages_per_chunk == 200
    assert primary.rows_per_page == 100
    assert secondary.mode == "maintenance_skip"
    assert secondary.chunks == 0


def test_manual_dispatch_keeps_requested_size_after_backfill() -> None:
    plan = choose_mfds_collection_plan(
        complete_cycles=2,
        event_name="workflow_dispatch",
        schedule=None,
        requested_chunks=3,
        requested_pages_per_chunk=150,
        requested_rows_per_page=100,
    )

    assert plan.mode == "manual"
    assert plan.chunks == 3
    assert plan.pages_per_chunk == 150


def test_collection_status_derives_progress_from_legacy_cursor_state() -> None:
    status = build_mfds_identity_collection_status(
        pointer={"row_count": 279417},
        pipeline={
            "next_page": 2801,
            "cycle": 1,
            "complete_cycles": 0,
            "last_total_count": 2704269,
        },
    )

    assert status.rows_per_page == 100
    assert status.cycle_rows_seen == 280000
    assert status.progress_percent is not None
    assert 10.3 < status.progress_percent < 10.4



def test_collection_plan_fails_closed_when_operational_state_is_unavailable() -> None:
    plan = choose_mfds_collection_plan(
        status="unavailable",
        complete_cycles=0,
        event_name="schedule",
        schedule="23 0 * * *",
    )

    assert plan.mode == "state_unknown"
    assert plan.chunks == 0
    assert "fail closed" in plan.reason


def test_falsely_completed_cycle_stays_in_backfill_until_coverage_is_verified() -> None:
    # Production state after an early empty page ended cycle 1 at ~53% coverage.
    status = build_mfds_identity_collection_status(
        pointer={"row_count": 1443124},
        pipeline={
            "next_page": 401,
            "cycle": 2,
            "complete_cycles": 1,
            "last_total_count": 2708719,
            "cycle_rows_seen": 40000,
            "rows_per_page": 100,
        },
    )

    assert status.mode == "backfill"
    assert status.first_backfill_complete is False
    assert status.progress_percent is not None
    assert 53.2 < status.progress_percent < 53.3

    for schedule in ("23 0 * * *", "23 12 * * *"):
        plan = choose_mfds_collection_plan(
            complete_cycles=status.complete_cycles,
            verified_complete_cycles=status.verified_complete_cycles,
            event_name="schedule",
            schedule=schedule,
        )
        assert plan.mode == "backfill"
        assert plan.chunks == 5
