"""Download the R2 search indexes in the background as soon as the app process starts.

Each search reads three SQLite indexes that live in R2 (Track B trades ~690 MB, MFDS identity
~2.1 GB, MFDS item status ~30 MB uncompressed). The loaders fetch them lazily, so after every
restart (each deploy) the first person to search waited 1-3 minutes while the files came down,
and every time the collector published a new MFDS identity index the next search paid the
download again. This module calls the same loaders from one daemon thread right after start-up
and then every ``REFRESH_SECONDS``, so a search normally finds the files already on disk.

The loaders keep their own locks and caches; this module only calls them early. Any failure is
recorded and swallowed: the search path still downloads on demand exactly as before.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from purchase_price.config import Settings

PREFETCH_V1 = True
REFRESH_SECONDS = 600.0
DISABLE_ENV = "PRICE_CHECK_INDEX_PREFETCH"

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATUS: dict[str, IndexWarmStatus] = {}


@dataclass(frozen=True)
class IndexWarmStatus:
    state: str  # loading | ready | not_ingested | failed
    seconds: float = 0.0
    error_type: str | None = None


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
    ("mfds_identity", _warm_mfds_identity),
    ("track_b", _warm_track_b),
    ("mfds_item_status", _warm_mfds_item_status),
)


def warm_indexes_once(
    settings: Settings,
    warmers: tuple[tuple[str, Callable[[Settings], bool]], ...] = WARMERS,
) -> dict[str, IndexWarmStatus]:
    """Load every index once, in order. One failure does not stop the others."""

    for name, warm in warmers:
        started = monotonic()
        with _LOCK:
            previous = _STATUS.get(name)
            # Keep "ready" while refreshing so the screen does not announce a warm-up that
            # only re-checks an index that is already on disk.
            if previous is None or previous.state != "ready":
                _STATUS[name] = IndexWarmStatus("loading")
        try:
            state = "ready" if warm(settings) else "not_ingested"
            result = IndexWarmStatus(state, monotonic() - started)
        except Exception as exc:  # never let a warm-up error reach the app
            result = IndexWarmStatus("failed", monotonic() - started, type(exc).__name__)
        with _LOCK:
            _STATUS[name] = result
    return prefetch_status()


def _run(settings: Settings, refresh_seconds: float, stop: threading.Event) -> None:
    while True:
        warm_indexes_once(settings)
        if stop.wait(refresh_seconds):
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


def reset_for_tests() -> None:
    global _THREAD
    with _LOCK:
        _STATUS.clear()
        _THREAD = None
