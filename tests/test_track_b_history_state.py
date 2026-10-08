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
        "hospital_active": ("4218190401", "4110449801"),
        "other_active": ("4321150201",),
        "no_recent_trade": ("4410310801", "4229000001"),
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
    assert calls[0]["explicit_target_codes"] == ("4218190401", "4110449801")
    assert calls[0]["begin"].isoformat() == HISTORY_WINDOWS[0][0]
    saved = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
    assert saved.cursor == CollectionCursor(1, 1)
    report = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert report["tier"] == "hospital_active" and report["mode"] == "history_backfill"
