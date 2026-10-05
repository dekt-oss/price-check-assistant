"""Read the MFDS item-status index (built from the full 형명 dataset) from R2 at search time.

The index answers "국내 정상 / 취소·취하 / 수출용" per item number instantly, instead of the
10-40 s model-info API call. While the first collection cycle is still running only part of
the dataset has been folded in, so callers must treat the answer as fail-closed:

- domestic_active=True is definitive for the item (one active model row was seen);
- an inactive answer is only definitive once a full cycle has been verified, because an
  unseen page may still hold an active model of the same item.

Any R2 or SQLite problem returns status "unavailable"; the search never fails because of it.
Uses its own cache directory: the identity-index loader deletes other *.sqlite files in its
directory.
"""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from time import monotonic

from purchase_price.config import Settings
from purchase_price.services.mfds_item_status_index import (
    MFDS_ITEM_STATUS_PREFIX,
    MFDS_ITEM_STATUS_SCHEMA,
    MfdsItemStatus,
    item_key,
    lookup_item_status,
)
from purchase_price.storage.r2_mfds_identity_index import (
    MfdsIdentityIndexRef,
    R2MfdsIdentityIndexStore,
)
from purchase_price.storage.r2_state import R2OperationalStateStore

ITEM_STATUS_POINTER_STATE = "mfds-item-status-index-pointer"
ITEM_STATUS_POINTER_SCHEMA = "mfds-item-status-index-pointer-v1"
ITEM_STATUS_PIPELINE_STATE = "mfds-item-status-pipeline"
_CACHE_DIR = Path(tempfile.gettempdir()) / "price-check-mfds-item-status"
_CACHE_TTL_SECONDS = 600.0
_LOCK = Lock()
# (expires_at, local path or None, verified_complete_cycles, item_count)
_CACHE: dict[str, tuple[float, Path | None, int, int]] = {}


@dataclass(frozen=True)
class ItemStatusLookup:
    status: str  # success | not_ingested | unavailable
    statuses: Mapping[str, MfdsItemStatus] = field(default_factory=dict)
    cycle_verified: bool = False
    item_count: int = 0

    def get(self, permit_number: object) -> MfdsItemStatus | None:
        return self.statuses.get(item_key(str(permit_number or "")))


def _snapshot(settings: Settings) -> tuple[Path | None, int, int]:
    with _LOCK:
        now = monotonic()
        cached = _CACHE.get("default")
        if cached is not None and now < cached[0] and (cached[1] is None or cached[1].exists()):
            return cached[1], cached[2], cached[3]

        states = R2OperationalStateStore.from_settings(settings)
        pointer = states.read_json(ITEM_STATUS_POINTER_STATE)
        pipeline = states.read_json(ITEM_STATUS_PIPELINE_STATE) or {}
        verified = int(pipeline.get("verified_complete_cycles") or 0)
        if not pointer or pointer.get("schema") != ITEM_STATUS_POINTER_SCHEMA:
            _CACHE["default"] = (now + _CACHE_TTL_SECONDS, None, verified, 0)
            return None, verified, 0
        sha256 = str(pointer.get("sha256") or "")
        ref = MfdsIdentityIndexRef(
            key=str(pointer.get("key") or ""),
            sha256=sha256,
            stored_bytes=int(pointer.get("stored_bytes") or 0),
            uncompressed_bytes=int(pointer.get("uncompressed_bytes") or 0),
        )
        destination = _CACHE_DIR / f"{sha256}.sqlite"
        if not destination.exists():
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            R2MfdsIdentityIndexStore.from_settings(
                settings, prefix=MFDS_ITEM_STATUS_PREFIX, schema=MFDS_ITEM_STATUS_SCHEMA
            ).download_sqlite(ref, destination)
            for stale in _CACHE_DIR.glob("*.sqlite"):
                if stale != destination:
                    stale.unlink(missing_ok=True)
        item_count = int(pointer.get("item_count") or 0)
        _CACHE["default"] = (now + _CACHE_TTL_SECONDS, destination, verified, item_count)
        return destination, verified, item_count


def lookup_item_status_from_r2(
    permit_numbers: Iterable[object],
    *,
    settings: Settings | None = None,
) -> ItemStatusLookup:
    permits = [str(p) for p in permit_numbers if str(p or "").strip()]
    try:
        path, verified, item_count = _snapshot(settings or Settings())
        if path is None:
            return ItemStatusLookup("not_ingested", cycle_verified=verified > 0)
        if not permits:
            return ItemStatusLookup("success", cycle_verified=verified > 0, item_count=item_count)
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            statuses = lookup_item_status(connection, permits)
        finally:
            connection.close()
        return ItemStatusLookup("success", statuses, cycle_verified=verified > 0, item_count=item_count)
    except Exception:  # optional enrichment; never break the search
        return ItemStatusLookup("unavailable")


def item_status_label(status: MfdsItemStatus | None, *, cycle_verified: bool) -> str | None:
    """Fail-closed label: active is shown at once, inactive only after a verified cycle."""

    if status is None:
        return None
    if status.domestic_active:
        return "국내 정상(품목)"
    if not cycle_verified:
        return None
    label = status.status_label
    return f"{label}(품목)" if label != "상태 미확인" else None


def reset_cache_for_tests() -> None:
    _CACHE.clear()

