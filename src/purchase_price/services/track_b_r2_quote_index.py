from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from purchase_price.config import Settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.track_b_pipeline_state import SERVING_INDEX_STATE_NAME
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError
from purchase_price.storage.r2_serving_index import R2ServingIndexRef, R2ServingIndexStore
from purchase_price.storage.r2_state import R2OperationalStateStore

POINTER_SCHEMA = "track-b-serving-index-pointer-v1"
_CACHE_DIR = Path(tempfile.gettempdir()) / "price-check-track-b"
_VALIDATED_CACHE_FILES: dict[str, tuple[int, int, int, int]] = {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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


def _local_index_path(settings: Settings) -> Path | None:
    state_store = R2OperationalStateStore.from_settings(settings)
    pointer = state_store.read_json(SERVING_INDEX_STATE_NAME)
    if pointer is None:
        return None
    if pointer.get("schema") != POINTER_SCHEMA:
        raise R2IntegrityError("Track B serving-index pointer schema mismatch")
    key = str(pointer.get("key") or "").strip()
    sha256 = str(pointer.get("sha256") or "").strip()
    if not key or len(sha256) != 64:
        raise R2IntegrityError("Track B serving-index pointer is incomplete")

    destination = _CACHE_DIR / f"{sha256}.sqlite"
    if destination.exists():
        if _cache_file_is_valid(destination, sha256):
            return destination
        _VALIDATED_CACHE_FILES.pop(sha256, None)
        try:
            destination.unlink()
        except OSError as exc:
            raise R2IntegrityError("Corrupt Track B serving-index cache cannot be replaced") from exc

    ref = R2ServingIndexRef(
        key=key,
        sha256=sha256,
        stored_bytes=int(pointer.get("stored_bytes") or 0),
        uncompressed_bytes=int(pointer.get("uncompressed_bytes") or 0),
    )
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    R2ServingIndexStore.from_settings(settings).download_sqlite(ref, destination)
    _remember_validated_cache(destination, sha256)
    for stale in _CACHE_DIR.glob("*.sqlite"):
        if stale != destination:
            try:
                stale.unlink()
            except OSError:
                pass
    return destination


def lookup_track_b_quote_from_r2(query: ProductQuery, *, quote_unit_price):
    # Local imports avoid a module cycle: the DB comparison module calls this function as its
    # preferred production lookup, while compare_track_b_quote remains the shared strict matcher.
    from purchase_price.services.track_b_db_quote_comparison import (
        TrackBQuoteComparison,
        compare_track_b_quote,
    )
    from purchase_price.services.track_b_reference_quality import (
        refine_track_b_reference_quality,
    )

    settings = Settings()
    if not settings.r2_configured:
        return TrackBQuoteComparison("unavailable", (), 0)
    try:
        path = _local_index_path(settings)
        if path is None:
            return TrackBQuoteComparison("not_ingested", (), 0)
        engine = create_engine(
            f"sqlite+pysqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
        session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        try:
            with session_factory() as session:
                result = compare_track_b_quote(
                    session,
                    query,
                    quote_unit_price=quote_unit_price,
                )
                return refine_track_b_reference_quality(session, query, result)
        finally:
            engine.dispose()
    except (
        BotoCoreError,
        ClientError,
        OSError,
        SQLAlchemyError,
        R2ConfigurationError,
        R2IntegrityError,
        ValueError,
    ):
        return TrackBQuoteComparison("unavailable", (), 0)
