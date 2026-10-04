from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import Any

# The live MFDS FOML_INFO query costs ~6s per search whether or not it finds anything.
# Once a collection cycle has verified full source coverage, the R2 index is authoritative
# and the live fallback is skipped. Newly registered products then appear after the next
# rolling refresh instead of immediately.
VERIFIED_STATUS_TTL_SECONDS = 600.0

_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, bool]] = {}


def mfds_index_verified_complete(status: Any) -> bool:
    """True only when the status proves a coverage-verified collection cycle.

    Streamlit can retain a status object from before ``verified_complete_cycles`` existed,
    where ``first_backfill_complete`` trusted ``complete_cycles`` alone. A missing counter is
    therefore treated as unverified so the live fallback stays on.
    """

    if getattr(status, "status", None) != "available":
        return False
    verified = getattr(status, "verified_complete_cycles", None)
    return isinstance(verified, int) and not isinstance(verified, bool) and verified >= 1


def should_query_live_mfds_identity(
    load_status: Callable[[], Any],
    *,
    now: float | None = None,
) -> bool:
    current = monotonic() if now is None else now
    with _CACHE_LOCK:
        cached = _CACHE.get("verified")
        if cached is not None and current < cached[0]:
            return not cached[1]
        try:
            verified = mfds_index_verified_complete(load_status())
        except Exception:
            verified = False
        _CACHE["verified"] = (current + VERIFIED_STATUS_TTL_SECONDS, verified)
        return not verified


def reset_live_policy_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
