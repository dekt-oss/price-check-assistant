from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from pathlib import Path
from collections.abc import Mapping
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

MFDS_IDENTITY_POINTER_STATE = "mfds-identity-index-pointer"
MFDS_IDENTITY_POINTER_SCHEMA = "mfds-identity-index-pointer-v1"
_CACHE_DIR = Path(tempfile.gettempdir()) / "price-check-mfds"


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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_index_path(settings: Settings) -> Path | None:
    state_store = R2OperationalStateStore.from_settings(settings)
    pointer = state_store.read_json(MFDS_IDENTITY_POINTER_STATE)
    if pointer is None:
        return None
    ref = _ref_from_pointer(pointer)
    destination = _CACHE_DIR / f"{ref.sha256}.sqlite"
    if destination.exists() and _sha256_file(destination) == ref.sha256:
        return destination

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    R2MfdsIdentityIndexStore.from_settings(settings).download_sqlite(ref, destination)
    for stale in _CACHE_DIR.glob("*.sqlite"):
        if stale != destination:
            stale.unlink(missing_ok=True)
    return destination


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
        connection = sqlite3.connect(path)
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
        connection = sqlite3.connect(path)
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
