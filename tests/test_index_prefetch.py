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

    assert sorted(calls) == ["broken", "missing", "ok"]
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
    assert "_search_status(" in page and "_wait_for_index_warmup()" in page
    assert '(track_b_r2_index_service, "_LAST_GOOD_SNAPSHOT")' in page


def test_progress_combines_running_downloads_and_names_what_is_left() -> None:
    from purchase_price.services.index_prefetch import IndexWarmStatus

    with index_prefetch._LOCK:
        index_prefetch._STATUS["mfds_identity"] = IndexWarmStatus(
            "loading", bytes_done=50_000_000, bytes_total=200_000_000
        )
        index_prefetch._STATUS["track_b"] = IndexWarmStatus(
            "ready", bytes_done=100_000_000, bytes_total=100_000_000
        )

    fraction, text = index_prefetch.warmup_progress()

    assert fraction == pytest.approx(0.5)
    assert "50%" in text and "150 / 300 MB" in text
    assert "식약처 제품 자료" in text and "나라장터 거래 자료" not in text


def test_progress_is_complete_when_nothing_is_loading() -> None:
    assert index_prefetch.warmup_progress()[0] == 1.0


def test_download_progress_reaches_the_warm_status(monkeypatch) -> None:
    import io

    from purchase_price.storage.streaming_gzip import write_verified_gzip_body

    seen: list[tuple[int, int | None]] = []

    def warm(_settings):
        import gzip
        import hashlib
        import tempfile

        raw = b"x" * 300_000
        body = io.BytesIO(gzip.compress(raw))
        with tempfile.TemporaryDirectory() as tmp:
            write_verified_gzip_body(
                body,
                Path(tmp) / "a.sqlite",
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                invalid_gzip_message="bad",
                hash_mismatch_prefix="bad",
                chunk_bytes=1024,
                total_bytes=len(body.getvalue()),
            )
        seen.append((index_prefetch._STATUS["a"].bytes_done, index_prefetch._STATUS["a"].bytes_total))
        return True

    index_prefetch.warm_indexes_once(SimpleNamespace(), (("a", warm),))

    done, total = seen[0]
    assert total and done == total
    assert index_prefetch.prefetch_status()["a"].state == "ready"


def test_track_b_search_uses_the_copy_on_disk_while_a_refresh_downloads(monkeypatch, tmp_path) -> None:
    old = tmp_path / "old.sqlite"
    old.write_bytes(b"")
    monkeypatch.setattr(track_b_index, "_LAST_GOOD_SNAPSHOT", (old, {"sha256": "old"}))
    monkeypatch.setattr(
        track_b_index,
        "_local_index_snapshot_locked",
        lambda _settings: pytest.fail("must not wait for the running download"),
    )

    assert track_b_index._LOCAL_INDEX_LOCK.acquire(blocking=False)
    try:
        path, pointer = track_b_index._local_index_snapshot(None)
    finally:
        track_b_index._LOCAL_INDEX_LOCK.release()

    assert path == old and pointer == {"sha256": "old"}


def test_mfds_search_uses_the_copy_on_disk_while_a_refresh_downloads(monkeypatch, tmp_path) -> None:
    from purchase_price.services import mfds_identity_r2

    old = tmp_path / "old.sqlite"
    old.write_bytes(b"")
    settings = SimpleNamespace(resolved_r2_endpoint_url="e", resolved_r2_bucket_name="b")
    monkeypatch.setitem(mfds_identity_r2._LAST_GOOD_PATH, ("e", "b"), old)
    monkeypatch.setattr(
        mfds_identity_r2,
        "_local_index_path_locked",
        lambda _settings: pytest.fail("must not wait for the running download"),
    )

    assert mfds_identity_r2._LOCAL_INDEX_CACHE_LOCK.acquire(blocking=False)
    try:
        assert mfds_identity_r2._local_index_path(settings) == old
    finally:
        mfds_identity_r2._LOCAL_INDEX_CACHE_LOCK.release()


def test_trim_drops_the_cache_of_every_local_index_file(tmp_path, monkeypatch) -> None:
    for name in ("price-check-track-b", "price-check-mfds", "price-check-mfds-item-status"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "abc.sqlite").write_bytes(b"x")
    (tmp_path / "price-check-track-b" / "abc.sqlite.gz.tmp").write_bytes(b"x")
    seen: list[str] = []
    monkeypatch.setattr(
        index_prefetch.streaming_gzip,
        "forget_cached_pages",
        lambda path: seen.append(Path(path).parent.name) or True,
    )

    assert index_prefetch.trim_index_page_cache(tmp_path) == 3
    assert sorted(seen) == ["price-check-mfds", "price-check-mfds-item-status", "price-check-track-b"]


def test_forget_cached_pages_is_a_no_op_without_fadvise(tmp_path, monkeypatch) -> None:
    from purchase_price.storage import streaming_gzip

    target = tmp_path / "a.sqlite"
    target.write_bytes(b"x")
    monkeypatch.delattr(streaming_gzip.os, "posix_fadvise", raising=False)
    assert streaming_gzip.forget_cached_pages(target) is False


def test_run_trims_between_refreshes_and_stops(monkeypatch) -> None:
    warmed: list[int] = []
    trims: list[int] = []
    stop = threading.Event()
    monkeypatch.setattr(index_prefetch, "warm_indexes_once", lambda _settings: warmed.append(1))

    def trim():
        trims.append(1)
        if len(trims) >= 3:
            stop.set()
        return 0

    monkeypatch.setattr(index_prefetch, "trim_index_page_cache", trim)
    index_prefetch._run(SimpleNamespace(), 600.0, stop, trim_seconds=0.01)

    assert warmed == [1]
    assert len(trims) == 3
