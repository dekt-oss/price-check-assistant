from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from purchase_price.config import Settings
from purchase_price.services.mfds_identity_index import (
    MfdsIdentityLookup,
    lookup_identity,
    lookup_same_product,
)
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError
from purchase_price.storage.r2_mfds_identity_index import (
    MfdsIdentityIndexRef,
    R2MfdsIdentityIndexStore,
)
from purchase_price.storage.r2_state import R2OperationalStateStore
from purchase_price.storage.streaming_gzip import drop_file_cache

MFDS_IDENTITY_POINTER_STATE = "mfds-identity-index-pointer"
MFDS_IDENTITY_POINTER_SCHEMA = "mfds-identity-index-pointer-v1"
_CACHE_DIR = Path(tempfile.gettempdir()) / "price-check-mfds"
_LOCAL_INDEX_CACHE_TTL_SECONDS = 300.0
_LOCAL_INDEX_CACHE_LOCK = Lock()
_VALIDATED_CACHE_FILES: dict[str, tuple[int, int, int, int]] = {}
_LOCAL_INDEX_PATH_CACHE: dict[tuple[str, str], tuple[float, Path, str]] = {}
_LAST_GOOD_PATH: dict[tuple[str, str], Path] = {}
SERVE_STALE_WHILE_REFRESHING = True


def _ref_from_pointer(payload: Mapping[str, Any]) -> MfdsIdentityIndexRef:
    if payload.get("schema") != MFDS_IDENTITY_POINTER_SCHEMA:
        raise R2IntegrityError("MFDS identity pointer schema mismatch")
    key = str(payload.get("key") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip()
    if not key or len(sha256) != 64:
        raise R2IntegrityError("MFDS identity pointer is incomplete")
    return MfdsIdentityIndexRef(
        key=key,
        sha256=sha256,
        stored_bytes=int(payload.get("stored_bytes") or 0),
        uncompressed_bytes=int(payload.get("uncompressed_bytes") or 0),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for index, chunk in enumerate(iter(lambda: handle.read(1024 * 1024), b"")):
            digest.update(chunk)
            if index % 64 == 63:
                drop_file_cache(handle.fileno())  # hashing 2 GB must not fill the page cache
        drop_file_cache(handle.fileno())
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _cache_file_is_valid(path: Path, sha256: str) -> bool:
    fingerprint = _file_fingerprint(path)
    if _VALIDATED_CACHE_FILES.get(sha256) == fingerprint:
        return True
    if _sha256_file(path) != sha256:
        return False
    _VALIDATED_CACHE_FILES[sha256] = fingerprint
    return True


def _remember_validated_cache(path: Path, sha256: str) -> None:
    _VALIDATED_CACHE_FILES[sha256] = _file_fingerprint(path)


def _runtime_cache_key(settings: Settings) -> tuple[str, str]:
    return (
        str(settings.resolved_r2_endpoint_url or ""),
        str(settings.resolved_r2_bucket_name or ""),
    )


def _cached_local_index_path(
    settings: Settings,
    *,
    now: float | None = None,
) -> Path | None:
    current = monotonic() if now is None else now
    key = _runtime_cache_key(settings)
    cached = _LOCAL_INDEX_PATH_CACHE.get(key)
    if cached is None:
        return None

    expires_at, path, sha256 = cached
    if current >= expires_at or not path.exists():
        _LOCAL_INDEX_PATH_CACHE.pop(key, None)
        return None

    try:
        if _VALIDATED_CACHE_FILES.get(sha256) != _file_fingerprint(path):
            _LOCAL_INDEX_PATH_CACHE.pop(key, None)
            return None
    except OSError:
        _LOCAL_INDEX_PATH_CACHE.pop(key, None)
        return None
    return path


def _local_index_path(settings: Settings) -> Path | None:
    # While another thread (usually the start-up prefetch refreshing every 10 minutes) downloads
    # a newer index, answer from the copy already on disk instead of waiting about a minute.
    if not _LOCAL_INDEX_CACHE_LOCK.acquire(blocking=False):
        last_good = _LAST_GOOD_PATH.get(_runtime_cache_key(settings))
        if last_good is not None and last_good.exists():
            return last_good
        _LOCAL_INDEX_CACHE_LOCK.acquire()
    try:
        path = _local_index_path_locked(settings)
    finally:
        _LOCAL_INDEX_CACHE_LOCK.release()
    if path is not None:
        _LAST_GOOD_PATH[_runtime_cache_key(settings)] = path
    return path


def _local_index_path_locked(settings: Settings) -> Path | None:
    current = monotonic()
    cached = _cached_local_index_path(settings, now=current)
    if cached is not None:
        return cached

    state_store = R2OperationalStateStore.from_settings(settings)
    pointer = state_store.read_json(MFDS_IDENTITY_POINTER_STATE)
    if pointer is None:
        return None
    ref = _ref_from_pointer(pointer)
    destination = _CACHE_DIR / f"{ref.sha256}.sqlite"
    if destination.exists():
        if _cache_file_is_valid(destination, ref.sha256):
            _LOCAL_INDEX_PATH_CACHE[_runtime_cache_key(settings)] = (
                current + _LOCAL_INDEX_CACHE_TTL_SECONDS,
                destination,
                ref.sha256,
            )
            return destination
        _VALIDATED_CACHE_FILES.pop(ref.sha256, None)
        destination.unlink(missing_ok=True)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    R2MfdsIdentityIndexStore.from_settings(settings).download_sqlite(ref, destination)
    _remember_validated_cache(destination, ref.sha256)
    _LOCAL_INDEX_PATH_CACHE[_runtime_cache_key(settings)] = (
        current + _LOCAL_INDEX_CACHE_TTL_SECONDS,
        destination,
        ref.sha256,
    )
    for stale in _CACHE_DIR.glob("*.sqlite"):
        if stale != destination:
            stale.unlink(missing_ok=True)
    return destination


def _connect_read_only(path: Path) -> sqlite3.Connection:
    # Read-only: if a refresh removed this copy a moment ago, fail instead of creating an empty file.
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def lookup_mfds_identity_from_r2(
    query: str,
    *,
    settings: Settings | None = None,
) -> MfdsIdentityLookup:
    settings = settings or Settings()
    if not settings.r2_configured:
        return MfdsIdentityLookup("unavailable", query.strip(), None, ())
    try:
        path = _local_index_path(settings)
        if path is None:
            return MfdsIdentityLookup("not_ingested", query.strip(), None, ())
        connection = _connect_read_only(path)
        try:
            return lookup_identity(connection, query)
        finally:
            connection.close()
    except (
        BotoCoreError,
        ClientError,
        OSError,
        sqlite3.Error,
        R2ConfigurationError,
        R2IntegrityError,
        ValueError,
    ):
        return MfdsIdentityLookup("unavailable", query.strip(), None, ())


def lookup_same_mfds_product_from_r2(
    product_name: str,
    *,
    settings: Settings | None = None,
):
    settings = settings or Settings()
    if not settings.r2_configured:
        return ()
    try:
        path = _local_index_path(settings)
        if path is None:
            return ()
        connection = _connect_read_only(path)
        try:
            return lookup_same_product(connection, product_name)
        finally:
            connection.close()
    except (
        BotoCoreError,
        ClientError,
        OSError,
        sqlite3.Error,
        R2ConfigurationError,
        R2IntegrityError,
        ValueError,
    ):
        return ()
