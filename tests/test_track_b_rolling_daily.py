from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from purchase_price.scripts import run_g2b_track_b_daily as daily
from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_pipeline_state import (
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_TARGET_CODE_COUNT,
    ROLLING_BOOTSTRAP_CURSOR,
    TrackBPipelineState,
)


class FakeStateStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, object]] = []

    def write_json(self, name: str, payload: object) -> None:
        self.writes.append((name, payload))


def _historical_complete_state() -> TrackBPipelineState:
    state = TrackBPipelineState.bootstrap()
    state.collection_cursor = CollectionCursor(EXPECTED_TARGET_CODE_COUNT, 1)
    state.backfill_complete = True
    return state


def _rolling_summary(
    *,
    start: CollectionCursor,
    next_cursor: CollectionCursor,
    begin_date: str = "2026-09-10",
    end_date: str = "2026-09-16",
) -> CollectionSummary:
    return CollectionSummary(
        status="PARTIAL_SUCCESS",
        started_at="2026-09-16T00:00:00+00:00",
        finished_at="2026-09-16T00:20:00+00:00",
        begin_date=begin_date,
        end_date=end_date,
        target_segments=("42", "41", "43", "44", "23", "27", "46", "39"),
        target_code_count=EXPECTED_TARGET_CODE_COUNT,
        target_code_source="SNAPSHOT",
        target_code_snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        start_cursor=start,
        next_cursor=next_cursor,
        request_budget=900,
        dictionary_requests=0,
        track_b_requests=900,
        total_requests=900,
        codes_completed=800,
        pages_stored=900,
        rows_seen=123,
        r2_objects_created=10,
        r2_objects_reused=890,
        r2_stored_bytes_created=1000,
        first_object_key="raw/a.json.gz",
        last_object_key="raw/z.json.gz",
        stop_reason="REQUEST_BUDGET_EXHAUSTED",
    )


def test_next_rolling_window_uses_recent_overlap_when_it_covers_first_uncovered_day() -> None:
    state = _historical_complete_state()

    assert daily._next_rolling_window(state, today=date(2026, 9, 16)) == (
        date(2026, 9, 10),
        date(2026, 9, 16),
        "recent_overlap",
    )


def test_next_rolling_window_catches_up_from_historical_endpoint_without_gap() -> None:
    state = _historical_complete_state()

    assert daily._next_rolling_window(state, today=date(2026, 9, 20)) == (
        date(2026, 9, 12),
        date(2026, 9, 18),
        "catch_up",
    )


def test_next_rolling_window_continues_catch_up_from_last_completed_cycle() -> None:
    state = _historical_complete_state()
    state.rolling_covered_through = "2026-09-18"

    assert daily._next_rolling_window(state, today=date(2026, 9, 27)) == (
        date(2026, 9, 19),
        date(2026, 9, 25),
        "catch_up",
    )


def test_next_rolling_window_is_noop_when_today_is_already_fully_covered() -> None:
    state = _historical_complete_state()
    state.rolling_covered_through = "2026-09-16"

    assert daily._next_rolling_window(state, today=date(2026, 9, 16)) is None


def test_rolling_runner_opens_kst_window_and_persists_it_before_requests(
    monkeypatch, tmp_path
) -> None:
    state = _historical_complete_state()
    store = FakeStateStore()
    captured: dict[str, object] = {}

    monkeypatch.setattr(daily, "_kst_today", lambda: date(2026, 9, 16))
    monkeypatch.setattr(daily, "_collection_clients", lambda *args, **kwargs: (object(), object()))
    monkeypatch.setattr(
        daily.R2RawEvidenceStore,
        "from_settings",
        classmethod(lambda cls, settings: object()),
    )

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return _rolling_summary(
            start=ROLLING_BOOTSTRAP_CURSOR,
            next_cursor=CollectionCursor(800, 1),
        )

    monkeypatch.setattr(daily, "collect_track_b_batch", fake_collect)
    summary_path = tmp_path / "summary.json"

    rc = daily._run_rolling_collection(
        state=state,
        state_store=store,
        settings=SimpleNamespace(g2b_catalog_base_url=None, g2b_shopping_base_url=None),
        catalog_key="catalog",
        shopping_key="shopping",
        snapshot_path=tmp_path / "snapshot.json",
        request_budget=900,
        summary_path=summary_path,
    )

    assert rc == 0
    assert captured["begin"] == date(2026, 9, 10)
    assert captured["end"] == date(2026, 9, 16)
    assert captured["start_cursor"] == ROLLING_BOOTSTRAP_CURSOR
    assert len(store.writes) == 2
    first_payload = store.writes[0][1]
    assert isinstance(first_payload, dict)
    assert first_payload["rolling_window_begin"] == "2026-09-10"
    assert first_payload["rolling_window_end"] == "2026-09-16"
    assert first_payload["rolling_covered_through"] == "2026-09-11"
    assert state.rolling_cursor == CollectionCursor(800, 1)
    assert state.rolling_covered_through == "2026-09-11"
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report["mode"] == "rolling_incremental"
    assert report["rolling_window_days"] == 7
    assert report["rolling_window_strategy"] == "recent_overlap"


def test_delayed_rolling_runner_opens_catch_up_window_from_first_uncovered_date(
    monkeypatch, tmp_path
) -> None:
    state = _historical_complete_state()
    store = FakeStateStore()
    captured: dict[str, object] = {}

    monkeypatch.setattr(daily, "_kst_today", lambda: date(2026, 9, 20))
    monkeypatch.setattr(daily, "_collection_clients", lambda *args, **kwargs: (object(), object()))
    monkeypatch.setattr(
        daily.R2RawEvidenceStore,
        "from_settings",
        classmethod(lambda cls, settings: object()),
    )

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return _rolling_summary(
            start=ROLLING_BOOTSTRAP_CURSOR,
            next_cursor=CollectionCursor(800, 1),
            begin_date="2026-09-12",
            end_date="2026-09-18",
        )

    monkeypatch.setattr(daily, "collect_track_b_batch", fake_collect)
    summary_path = tmp_path / "summary.json"

    rc = daily._run_rolling_collection(
        state=state,
        state_store=store,
        settings=SimpleNamespace(g2b_catalog_base_url=None, g2b_shopping_base_url=None),
        catalog_key="catalog",
        shopping_key="shopping",
        snapshot_path=tmp_path / "snapshot.json",
        request_budget=900,
        summary_path=summary_path,
    )

    assert rc == 0
    assert captured["begin"] == date(2026, 9, 12)
    assert captured["end"] == date(2026, 9, 18)
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report["rolling_window_strategy"] == "catch_up"
    assert report["rolling_covered_through"] == "2026-09-11"


def test_rolling_runner_reuses_locked_window_on_resume(monkeypatch, tmp_path) -> None:
    state = _historical_complete_state()
    state.rolling_cursor = CollectionCursor(800, 2)
    state.rolling_window_begin = "2026-09-10"
    state.rolling_window_end = "2026-09-16"
    store = FakeStateStore()
    captured: dict[str, object] = {}

    monkeypatch.setattr(daily, "_kst_today", lambda: date(2026, 9, 20))
    monkeypatch.setattr(daily, "_collection_clients", lambda *args, **kwargs: (object(), object()))
    monkeypatch.setattr(
        daily.R2RawEvidenceStore,
        "from_settings",
        classmethod(lambda cls, settings: object()),
    )

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return _rolling_summary(
            start=CollectionCursor(800, 2),
            next_cursor=CollectionCursor(1600, 1),
        )

    monkeypatch.setattr(daily, "collect_track_b_batch", fake_collect)

    rc = daily._run_rolling_collection(
        state=state,
        state_store=store,
        settings=SimpleNamespace(g2b_catalog_base_url=None, g2b_shopping_base_url=None),
        catalog_key="catalog",
        shopping_key="shopping",
        snapshot_path=tmp_path / "snapshot.json",
        request_budget=900,
        summary_path=tmp_path / "summary.json",
    )

    assert rc == 0
    assert captured["begin"] == date(2026, 9, 10)
    assert captured["end"] == date(2026, 9, 16)
    assert captured["start_cursor"] == CollectionCursor(800, 2)
    # Existing cycles do not rewrite the state before the request; only the post-batch state is stored.
    assert len(store.writes) == 1


def test_rolling_runner_noops_when_today_is_already_covered(monkeypatch, tmp_path) -> None:
    state = _historical_complete_state()
    state.rolling_covered_through = "2026-09-16"
    store = FakeStateStore()
    monkeypatch.setattr(daily, "_kst_today", lambda: date(2026, 9, 16))

    rc = daily._run_rolling_collection(
        state=state,
        state_store=store,
        settings=SimpleNamespace(g2b_catalog_base_url=None, g2b_shopping_base_url=None),
        catalog_key="catalog",
        shopping_key="shopping",
        snapshot_path=tmp_path / "snapshot.json",
        request_budget=900,
        summary_path=tmp_path / "summary.json",
    )

    assert rc == 0
    assert not store.writes
    report = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert report["stop_reason"] == "ROLLING_UP_TO_DATE"
