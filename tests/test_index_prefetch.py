from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.services import index_prefetch
from purchase_price.services import track_b_r2_quote_index as track_b_index

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset():
    index_prefetch.reset_for_tests()
    yield
    index_prefetch.reset_for_tests()


def test_warm_once_records_each_index_and_survives_a_failure() -> None:
    calls: list[str] = []

    def ok(_settings):
        calls.append("ok")
        return True

    def missing(_settings):
        calls.append("missing")
        return False

    def broken(_settings):
        calls.append("broken")
        raise OSError("disk full")

    status = index_prefetch.warm_indexes_once(
        SimpleNamespace(),
        (("a", broken), ("b", ok), ("c", missing)),
    )

    assert calls == ["broken", "ok", "missing"]
    assert status["a"].state == "failed" and status["a"].error_type == "OSError"
    assert status["b"].state == "ready"
    assert status["c"].state == "not_ingested"
    assert index_prefetch.indexes_warming() is False


def test_warming_is_reported_only_during_a_first_download() -> None:
    seen: list[bool] = []

    def first(_settings):
        seen.append(index_prefetch.indexes_warming())
        return True

    index_prefetch.warm_indexes_once(SimpleNamespace(), (("a", first),))
    # A later refresh of an index already on disk must not announce a warm-up again.
    index_prefetch.warm_indexes_once(SimpleNamespace(), (("a", first),))

    assert seen == [True, False]


def test_start_is_skipped_without_r2_or_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert index_prefetch.start_index_prefetch(SimpleNamespace(r2_configured=False)) is False

    monkeypatch.setenv(index_prefetch.DISABLE_ENV, "0")
    assert index_prefetch.start_index_prefetch(SimpleNamespace(r2_configured=True)) is False


def test_start_runs_one_thread_per_process(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv(index_prefetch.DISABLE_ENV, raising=False)
    warmed = threading.Event()
    calls: list[int] = []

    def fake_warm(_settings, warmers=index_prefetch.WARMERS):
        calls.append(1)
        warmed.set()
        return {}

    monkeypatch.setattr(index_prefetch, "warm_indexes_once", fake_warm)
    stop = threading.Event()
    settings = SimpleNamespace(r2_configured=True)
    try:
        assert index_prefetch.start_index_prefetch(settings, refresh_seconds=60, stop=stop)
        assert warmed.wait(5)
        assert index_prefetch.start_index_prefetch(settings, refresh_seconds=60, stop=stop)
    finally:
        stop.set()
        index_prefetch._THREAD.join(5)
    assert calls == [1]


def test_track_b_loader_downloads_one_at_a_time(monkeypatch) -> None:
    active = 0
    peak = 0
    guard = threading.Lock()

    def slow_locked(_settings):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        threading.Event().wait(0.05)
        with guard:
            active -= 1
        return None, None

    monkeypatch.setattr(track_b_index, "_local_index_snapshot_locked", slow_locked)
    threads = [
        threading.Thread(target=track_b_index._local_index_snapshot, args=(None,))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert peak == 1


def test_app_starts_prefetch_and_explains_the_wait() -> None:
    home = (ROOT / "Home.py").read_text(encoding="utf-8")
    page = (ROOT / "pages" / "1_대시보드.py").read_text(encoding="utf-8")

    assert "start_index_prefetch()" in home
    assert "_search_status_label(" in page
    assert '(track_b_r2_index_service, "_LOCAL_INDEX_LOCK")' in page
