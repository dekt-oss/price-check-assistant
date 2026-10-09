"""Download the R2 search indexes in the background as soon as the app process starts.

Each search reads three SQLite indexes that live in R2 (Track B trades ~690 MB, MFDS identity
~2.1 GB, MFDS item status ~30 MB uncompressed). The loaders fetch them lazily, so after every
restart (each deploy) the first person to search waited 1-3 minutes while the files came down,
and every time the collector published a new MFDS identity index the next search paid the
download again. This module calls the same loaders from one daemon thread right after start-up
and then every ``REFRESH_SECONDS``, so a search normally finds the files already on disk. The
three downloads run side by side (the largest alone takes about a minute) and report how far
they are, so a search that arrives during the warm-up can show a percentage instead of a spinner.

The loaders keep their own locks and caches; this module only calls them early. Any failure is
recorded and swallowed: the search path still downloads on demand exactly as before.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic

from purchase_price.config import Settings
from purchase_price.storage import streaming_gzip

PREFETCH_V1 = True
PROGRESS_V1 = True
REFRESH_SECONDS = 600.0
# The Track B index grew to 2.5 GB with the 2021-2024 history (2026-10-09). Pages that searches
# read stayed cached and held the container at its 3.2 GB limit, the pattern that showed
# Streamlit Cloud's resource-limit page earlier, so the cache of the index files is dropped this often.
TRIM_SECONDS = 120.0
INDEX_CACHE_DIRS = ("price-check-track-b", "price-check-mfds", "price-check-mfds-item-status")
PAGE_CACHE_TRIM_V1 = True
DISABLE_ENV = "PRICE_CHECK_INDEX_PREFETCH"

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATUS: dict[str, IndexWarmStatus] = {}


@dataclass(frozen=True)
class IndexWarmStatus:
    state: str  # loading | ready | not_ingested | failed
    seconds: float = 0.0
    error_type: str | None = None
    bytes_done: int = 0
    bytes_total: int | None = None


def _warm_track_b(settings: Settings) -> bool:
    from purchase_price.services import track_b_r2_quote_index

    return track_b_r2_quote_index._local_index_path(settings) is not None


def _warm_mfds_identity(settings: Settings) -> bool:
    from purchase_price.services import mfds_identity_r2

    return mfds_identity_r2._local_index_path(settings) is not None


def _warm_mfds_item_status(settings: Settings) -> bool:
    from purchase_price.services import mfds_item_status_r2

    path, _verified, _count = mfds_item_status_r2._snapshot(settings)
    return path is not None


# Search order: a text search first resolves the product in the identity index (the "조사할 제품
# 고르기" step), then reads its trades, then the item status.
WARMERS: tuple[tuple[str, Callable[[Settings], bool]], ...] = (
    ("mfds_item_status", _warm_mfds_item_status),
    ("track_b", _warm_track_b),
    ("mfds_identity", _warm_mfds_identity),
)


LABELS = {
    "mfds_identity": "식약처 제품 자료",
    "track_b": "나라장터 거래 자료",
    "mfds_item_status": "식약처 품목 상태",
}


def _record_progress(name: str) -> Callable[[int, int | None], None]:
    def update(done: int, total: int | None) -> None:
        with _LOCK:
            current = _STATUS.get(name)
            if current is not None and current.state == "loading":
                _STATUS[name] = replace(current, bytes_done=done, bytes_total=total)

    return update


def _warm_one(name: str, warm: Callable[[Settings], bool], settings: Settings) -> None:
    started = monotonic()
    with _LOCK:
        previous = _STATUS.get(name)
        # Keep "ready" while refreshing so the screen does not announce a warm-up that
        # only re-checks an index that is already on disk.
        if previous is None or previous.state != "ready":
            _STATUS[name] = IndexWarmStatus("loading")
    try:
        # An older streaming_gzip kept by a hot-reloaded process has no progress hook.
        report = getattr(streaming_gzip, "report_progress_to", None)
        with report(_record_progress(name)) if report else nullcontext():
            state = "ready" if warm(settings) else "not_ingested"
        error_type = None
    except Exception as exc:  # never let a warm-up error reach the app
        state, error_type = "failed", type(exc).__name__
    with _LOCK:
        current = _STATUS.get(name)
        total = current.bytes_total if current is not None else None
        # A finished download counts as fully done in the overall percentage.
        _STATUS[name] = IndexWarmStatus(
            state, monotonic() - started, error_type, bytes_done=total or 0, bytes_total=total
        )


def warm_indexes_once(
    settings: Settings,
    warmers: tuple[tuple[str, Callable[[Settings], bool]], ...] = WARMERS,
) -> dict[str, IndexWarmStatus]:
    """Load every index once, one after another. One failure does not stop the others.

    They used to download side by side; on 2026-10-09 a restart then pushed the Cloud app over its
    resource limit, so they now run one at a time (smallest first) to keep the peak low.
    """

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="index-warm") as pool:
        for future in [pool.submit(_warm_one, name, warm, settings) for name, warm in warmers]:
            future.result()
    return prefetch_status()


def index_files(root: Path | None = None) -> list[Path]:
    base = root or Path(tempfile.gettempdir())
    return [path for name in INDEX_CACHE_DIRS for path in sorted((base / name).glob("*.sqlite"))]


def trim_index_page_cache(root: Path | None = None) -> int:
    """Drop the cached pages of every local index file; returns how many files got the hint."""

    return sum(1 for path in index_files(root) if streaming_gzip.forget_cached_pages(path))


def _run(
    settings: Settings,
    refresh_seconds: float,
    stop: threading.Event,
    trim_seconds: float = TRIM_SECONDS,
) -> None:
    while True:
        warm_indexes_once(settings)
        next_refresh = monotonic() + refresh_seconds
        while True:
            trim_index_page_cache()
            remaining = next_refresh - monotonic()
            if remaining <= 0:
                break
            if stop.wait(min(trim_seconds, remaining)):
                return


def prefetch_disabled() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return str(os.getenv(DISABLE_ENV, "")).strip().casefold() in {"0", "false", "no", "off"}


def start_index_prefetch(
    settings: Settings | None = None,
    *,
    refresh_seconds: float = REFRESH_SECONDS,
    stop: threading.Event | None = None,
) -> bool:
    """Start the warm-up thread once per process. Returns True when a thread is running."""

    global _THREAD
    if prefetch_disabled():
        return False
    settings = settings or Settings()
    if not settings.r2_configured:
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _THREAD = threading.Thread(
            target=_run,
            args=(settings, refresh_seconds, stop or threading.Event()),
            name="price-check-index-prefetch",
            daemon=True,
        )
        _THREAD.start()
    return True


def prefetch_status() -> dict[str, IndexWarmStatus]:
    with _LOCK:
        return dict(_STATUS)


def indexes_warming() -> bool:
    """True while a first download is still running, so a search will have to wait for it."""

    with _LOCK:
        return any(status.state == "loading" for status in _STATUS.values())


def warmup_progress() -> tuple[float, str]:
    """Overall share of the first download already on disk, and a line for the screen."""

    with _LOCK:
        statuses = dict(_STATUS)
    loading = {name: status for name, status in statuses.items() if status.state == "loading"}
    if not loading:
        return 1.0, "가격 자료 준비가 끝났습니다."
    done = sum(min(s.bytes_done, s.bytes_total or 0) for s in statuses.values() if s.bytes_total)
    total = sum(s.bytes_total or 0 for s in statuses.values() if s.bytes_total)
    fraction = done / total if total else 0.0
    waiting = ", ".join(LABELS.get(name, name) for name in loading)
    megabytes = f" ({done / 1_000_000:,.0f} / {total / 1_000_000:,.0f} MB)" if total else ""
    return (
        min(fraction, 0.99),
        f"서버가 막 다시 켜져 가격 자료를 내려받는 중입니다 {fraction:.0%}{megabytes} · 남은 자료: {waiting}",
    )


def reset_for_tests() -> None:
    global _THREAD
    with _LOCK:
        _STATUS.clear()
        _THREAD = None
