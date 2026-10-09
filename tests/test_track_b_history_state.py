from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.scripts import run_g2b_track_b_history as runner
from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_history_state import (
    HISTORY_STATE_NAME,
    HISTORY_WINDOWS,
    TrackBHistoryState,
    build_tiers,
    history_passes,
)

SNAPSHOT = ("4218190401", "4110449801", "4321150201", "4410310801", "4229000001")
ACTIVE = {"4218190401", "4110449801", "4321150201"}


def _summary(
    state: TrackBHistoryState,
    *,
    next_index: int,
    stop: str = "REQUEST_BUDGET_EXHAUSTED",
    requests: int = 2,
) -> CollectionSummary:
    _tier, begin, end = state.current_pass
    return CollectionSummary(
        status="PARTIAL_SUCCESS" if stop != "TARGET_COMPLETE" else "SUCCESS",
        started_at="2026-10-09T04:10:00+00:00",
        finished_at="2026-10-09T04:20:00+00:00",
        begin_date=begin,
        end_date=end,
        target_segments=("41", "42"),
        target_code_count=len(state.current_codes),
        target_code_source="EXPLICIT_VERIFIED",
        target_code_snapshot_sha256=None,
        start_cursor=state.cursor,
        next_cursor=CollectionCursor(next_index, 1),
        request_budget=requests,
        dictionary_requests=0,
        track_b_requests=requests,
        total_requests=requests,
        codes_completed=next_index,
        pages_stored=requests,
        rows_seen=7,
        r2_objects_created=requests,
        r2_objects_reused=0,
        r2_stored_bytes_created=100,
        first_object_key=None,
        last_object_key=None,
        stop_reason=stop,
    )


def test_hospital_categories_that_traded_come_first_and_quiet_codes_last() -> None:
    tiers = build_tiers(SNAPSHOT, ACTIVE)

    assert tiers == {
        "hospital_active": ("4110449801", "4218190401"),
        "other_active": ("4321150201",),
        "no_recent_trade": ("4229000001", "4410310801"),
    }
    passes = history_passes(tiers)
    # Every window for hospital equipment before any other category.
    assert passes[: len(HISTORY_WINDOWS)] == tuple(
        ("hospital_active", begin, end) for begin, end in HISTORY_WINDOWS
    )
    assert passes[-1] == ("no_recent_trade", "2021-01-01", "2021-09-11")


def test_windows_reach_2021_and_never_exceed_one_year() -> None:
    from datetime import date

    assert HISTORY_WINDOWS[-1][0] == "2021-01-01"
    assert HISTORY_WINDOWS[0][1] == "2025-09-11"  # meets the base backfill (2025-09-12~)
    for begin, end in HISTORY_WINDOWS:
        assert (date.fromisoformat(end) - date.fromisoformat(begin)).days <= 365
    for (_b, older_end), (newer_begin, _e) in zip(HISTORY_WINDOWS[1:], HISTORY_WINDOWS, strict=False):
        assert (date.fromisoformat(newer_begin) - date.fromisoformat(older_end)).days == 1


def test_a_partial_batch_resumes_and_a_finished_pass_moves_on() -> None:
    state = TrackBHistoryState.bootstrap(build_tiers(SNAPSHOT, ACTIVE))

    state.apply_collection(_summary(state, next_index=1), object_keys=["raw/a"])
    assert state.pass_index == 0 and state.cursor == CollectionCursor(1, 1)

    state.apply_collection(
        _summary(state, next_index=2, stop="TARGET_COMPLETE"), object_keys=["raw/b", "raw/a"]
    )
    assert state.pass_index == 1 and state.cursor == CollectionCursor(0, 1)
    assert state.current_pass == ("hospital_active", *HISTORY_WINDOWS[1])
    assert state.pending_object_keys == ["raw/a", "raw/b"]
    assert state.requests_total == 4


def test_a_batch_for_another_window_is_rejected() -> None:
    state = TrackBHistoryState.bootstrap(build_tiers(SNAPSHOT, ACTIVE))
    summary = _summary(state, next_index=1)
    state.pass_index = 1

    with pytest.raises(ValueError, match="date window"):
        state.apply_collection(summary, object_keys=[])


def test_state_round_trips_and_detects_edited_tiers() -> None:
    state = TrackBHistoryState.bootstrap(build_tiers(SNAPSHOT, ACTIVE))
    state.apply_collection(_summary(state, next_index=1), object_keys=["raw/a"])

    payload = json.loads(json.dumps(state.to_payload()))
    restored = TrackBHistoryState.from_payload(payload)
    assert restored.cursor == state.cursor and restored.pending_object_keys == ["raw/a"]

    payload["tiers"]["hospital_active"].append("4299999999")
    with pytest.raises(ValueError, match="fingerprint"):
        TrackBHistoryState.from_payload(payload)


def test_progress_counts_code_windows_across_passes() -> None:
    state = TrackBHistoryState.bootstrap(build_tiers(SNAPSHOT, ACTIVE))
    total = len(SNAPSHOT) * len(HISTORY_WINDOWS)

    state.apply_collection(_summary(state, next_index=2, stop="TARGET_COMPLETE"), object_keys=[])
    state.apply_collection(_summary(state, next_index=1), object_keys=[])

    progress = state.progress()
    assert progress["code_windows_total"] == total
    assert progress["code_windows_done"] == 3
    assert progress["percent"] == round(3 / total * 100, 1)


def test_indexed_pages_leave_the_pending_list() -> None:
    state = TrackBHistoryState.bootstrap(build_tiers(SNAPSHOT, ACTIVE))
    state.pending_object_keys = ["raw/a", "raw/b"]

    state.mark_pending_indexed(["raw/a"])

    assert state.pending_object_keys == ["raw/b"]


class _MemoryStates:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    def read_json(self, name: str):
        return self.values.get(name)

    def write_json(self, name: str, payload) -> None:
        self.values[name] = json.loads(json.dumps(payload))


def test_runner_freezes_tiers_then_collects_the_first_pass(monkeypatch, tmp_path: Path) -> None:
    states = _MemoryStates()
    calls: list[dict] = []

    def fake_collect(**kwargs):
        calls.append(kwargs)
        state = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
        return _summary(state, next_index=1)

    settings = SimpleNamespace(
        r2_configured=True,
        resolved_g2b_shopping_service_key="key",
        g2b_request_timeout_seconds=5,
        g2b_max_retries=0,
        g2b_shopping_base_url=None,
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner.R2OperationalStateStore, "from_settings", lambda _s: states)
    monkeypatch.setattr(runner, "_restore_snapshot", lambda **_kwargs: tmp_path / "codes.json")
    monkeypatch.setattr(
        runner, "load_target_code_snapshot", lambda *_a, **_k: SimpleNamespace(codes=SNAPSHOT)
    )
    monkeypatch.setattr(runner, "_active_codes_from_serving_index", lambda *_a: ACTIVE)
    monkeypatch.setattr(runner, "PublicDataPortalClient", lambda *_a, **_k: object())
    monkeypatch.setattr(runner.R2RawEvidenceStore, "from_settings", lambda _s: object())
    monkeypatch.setattr(runner, "collect_track_b_batch", fake_collect)

    exit_code = runner.run(request_budget=330, output=tmp_path / "summary.json")

    assert exit_code == 0
    assert calls[0]["explicit_target_codes"] == ("4110449801", "4218190401")
    assert calls[0]["begin"].isoformat() == HISTORY_WINDOWS[0][0]
    saved = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
    assert saved.cursor == CollectionCursor(1, 1)
    report = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert report["batches"][0]["tier"] == "hospital_active" and report["mode"] == "history_backfill"


def test_codes_reach_the_collector_sorted_even_from_an_unsorted_frozen_state(tmp_path) -> None:
    """The collector's own check, not a fake: unsorted explicit codes are rejected."""

    from datetime import date

    from purchase_price.scripts.collect_g2b_track_b_r2 import _resolve_target_codes

    state = TrackBHistoryState.bootstrap({"hospital_active": ("4218190401", "4110449801")})
    codes = state.current_codes

    assert codes == ("4110449801", "4218190401")
    resolved = _resolve_target_codes(
        catalog_client=None,
        catalog_base_url="unused",
        segments=("41", "42"),
        page_size=999,
        snapshot_path=None,
        refresh_snapshot=False,
        explicit_target_codes=codes,
    )
    assert tuple(resolved[0]) == codes
    assert date.fromisoformat(state.current_pass[1])


def _wire_runner(monkeypatch, tmp_path: Path, states: _MemoryStates, fake_collect) -> None:
    settings = SimpleNamespace(
        r2_configured=True,
        resolved_g2b_shopping_service_key="key",
        g2b_request_timeout_seconds=5,
        g2b_max_retries=0,
        g2b_shopping_base_url=None,
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner.R2OperationalStateStore, "from_settings", lambda _s: states)
    monkeypatch.setattr(runner, "_restore_snapshot", lambda **_kwargs: tmp_path / "codes.json")
    monkeypatch.setattr(
        runner, "load_target_code_snapshot", lambda *_a, **_k: SimpleNamespace(codes=SNAPSHOT)
    )
    monkeypatch.setattr(runner, "_active_codes_from_serving_index", lambda *_a: ACTIVE)
    monkeypatch.setattr(runner, "PublicDataPortalClient", lambda *_a, **_k: object())
    monkeypatch.setattr(runner.R2RawEvidenceStore, "from_settings", lambda _s: object())
    monkeypatch.setattr(runner, "collect_track_b_batch", fake_collect)


def test_until_done_runs_every_pass_and_retries_a_connection_error(monkeypatch, tmp_path) -> None:
    states = _MemoryStates()
    failures = iter([True])  # the very first batch hits a ConnectTimeout
    pauses: list[float] = []

    def fake_collect(**kwargs):
        state = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
        if next(failures, False):
            return _summary(state, next_index=0, stop="SOURCE_OR_STORAGE_ERROR", requests=1)
        return _summary(state, next_index=len(state.current_codes), stop="TARGET_COMPLETE")

    _wire_runner(monkeypatch, tmp_path, states, fake_collect)
    exit_code = runner.run(
        request_budget=10, output=tmp_path / "s.json", max_minutes=300, pause=pauses.append
    )

    saved = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
    report = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert exit_code == 0 and saved.complete and report["history_complete"] is True
    assert len(report["batches"]) == len(saved.passes) + 1
    assert pauses == [runner.SOURCE_ERROR_PAUSE_SECONDS]


def test_until_done_stops_before_the_job_deadline(monkeypatch, tmp_path) -> None:
    states = _MemoryStates()
    now = [0.0]

    def fake_collect(**kwargs):
        now[0] += 40 * 60  # each batch takes 40 minutes
        state = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
        return _summary(state, next_index=1)

    _wire_runner(monkeypatch, tmp_path, states, fake_collect)
    runner.run(
        request_budget=1000,
        output=tmp_path / "s.json",
        max_minutes=100,
        clock=lambda: now[0],
        pause=lambda _s: None,
    )

    report = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    # 0 -> 40 -> 80 min; a third batch (estimated 1000 x 1.3 s) would pass the 100-minute deadline.
    assert len(report["batches"]) == 2
    assert report["history_complete"] is False


def test_until_done_uses_the_slowest_batch_when_batches_run_slower_than_estimated(
    monkeypatch, tmp_path
) -> None:
    states = _MemoryStates()
    now = [0.0]

    def fake_collect(**kwargs):
        now[0] += 60 * 60  # 2026-10-09: a batch took far longer than 100 x 1.3 s
        state = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
        return _summary(state, next_index=1)

    _wire_runner(monkeypatch, tmp_path, states, fake_collect)
    runner.run(
        request_budget=100,
        output=tmp_path / "s.json",
        max_minutes=140,
        clock=lambda: now[0],
        pause=lambda _s: None,
    )

    report = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    # 0 -> 60 -> 120 min; the estimate alone (130 s) would start a third batch ending at 180 min.
    assert len(report["batches"]) == 2
