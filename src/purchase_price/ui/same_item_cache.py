"""Same-품목 models and 같은 품목 시장 per serving-index file, shared by every session.

The dashboard builds them below the conclusion card (~7 s for HeartOn A16-DS's 134 models). The
serving-index file never changes under its SHA-256 name and the rows are public procurement data,
so one result serves every later search of the same inputs until a new index file arrives.

It lives in an imported module on purpose: Streamlit runs a page script afresh on every rerun, so
a dict defined in pages/1_대시보드.py was empty again on the next search (v32 measured two misses).
"""

from __future__ import annotations

from threading import Lock
from typing import Any

LIMIT = 32

_CACHE: dict[tuple[object, ...], tuple[list[dict[str, object]], Any]] = {}
_LOCK = Lock()


def get(key: tuple[object, ...] | None) -> tuple[list[dict[str, object]], Any] | None:
    """(rows, market) for ``key``, rows as copies; marks the entry as newest. None on a miss."""

    if key is None:
        return None
    with _LOCK:
        hit = _CACHE.pop(key, None)
        if hit is None:
            return None
        _CACHE[key] = hit
    return [dict(row) for row in hit[0]], hit[1]


def put(key: tuple[object, ...] | None, rows: list[dict[str, object]], market: Any) -> None:
    """Keep a copy of ``rows`` and ``market`` (immutable) under ``key``; drop the oldest past LIMIT."""

    if key is None:
        return
    with _LOCK:
        _CACHE.pop(key, None)
        _CACHE[key] = ([dict(row) for row in rows], market)
        while len(_CACHE) > LIMIT:
            _CACHE.pop(next(iter(_CACHE)))


def size() -> int:
    with _LOCK:
        return len(_CACHE)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()
