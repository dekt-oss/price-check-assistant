from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from purchase_price.config import Settings
from purchase_price.storage.r2 import (
    R2ConfigurationError,
    R2IntegrityError,
    R2QuotaExceededError,
    R2RawEvidenceStore,
)

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
SERVING_INDEX_SCHEMA = "track-b-serving-sqlite-v2"
LEGACY_SERVING_INDEX_SCHEMAS = {"track-b-serving-sqlite-v1"}
SUPPORTED_SERVING_INDEX_SCHEMAS = {SERVING_INDEX_SCHEMA, *LEGACY_SERVING_INDEX_SCHEMAS}


@dataclass(frozen=True)
class R2ServingIndexRef:
    key: str
    sha256: str
    stored_bytes: int
    uncompressed_bytes: int


class R2ServingIndexStore:
    """Versioned SQLite serving-index artifacts persisted in R2.

    R2 remains the durable source of truth. The SQLite file is a rebuildable, read-optimized
    derivative used by Streamlit so quote lookups never scan the full raw object corpus.
    """

    def __init__(
        self,
        *,
        client: Any,
        bucket: str,
        prefix: str = "derived/v1/track-b-serving",
        quota_store: R2RawEvidenceStore | None = None,
    ) -> None:
        if not bucket.strip():
            raise R2ConfigurationError("R2 bucket name is required")
        self._client = client
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/") or "derived/v1/track-b-serving"
        self._quota_store = quota_store

    @classmethod
    def from_settings(cls, settings: Settings) -> R2ServingIndexStore:
        if not settings.r2_configured:
            raise R2ConfigurationError("R2 is not fully configured for the serving index")
        endpoint = settings.resolved_r2_endpoint_url
        bucket = settings.resolved_r2_bucket_name
        assert endpoint is not None
        assert bucket is not None
        assert settings.r2_access_key_id is not None
        assert settings.r2_secret_access_key is not None
        client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        return cls(
            client=client,
            bucket=bucket,
            quota_store=R2RawEvidenceStore.from_settings(settings),
        )

    def put_sqlite(self, path: Path) -> R2ServingIndexRef:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        key = f"{self.prefix}/{digest[:2]}/{digest}.sqlite.gz"
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)

        existing = self._head_if_exists(key)
        if existing is not None:
            metadata = existing.get("Metadata") or {}
            if metadata.get("sha256") != digest or metadata.get("schema") != SERVING_INDEX_SCHEMA:
                raise R2IntegrityError(f"R2 serving index metadata mismatch for {key}")
            return R2ServingIndexRef(
                key=key,
                sha256=digest,
                stored_bytes=int(existing.get("ContentLength") or len(compressed)),
                uncompressed_bytes=len(raw),
            )

        if self._quota_store is not None:
            usage = self._quota_store.quota_status(refresh=True)
            if usage.stored_bytes + len(compressed) > usage.hard_limit_bytes:
                raise R2QuotaExceededError(
                    "R2 serving index write would exceed the configured zero-cost hard limit"
                )
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=compressed,
            ContentType="application/x-sqlite3",
            ContentEncoding="gzip",
            Metadata={
                "sha256": digest,
                "schema": SERVING_INDEX_SCHEMA,
                "data-classification": "public-derived-index",
            },
            StorageClass="STANDARD",
        )
        return R2ServingIndexRef(
            key=key,
            sha256=digest,
            stored_bytes=len(compressed),
            uncompressed_bytes=len(raw),
        )

    def download_sqlite(self, ref: R2ServingIndexRef, destination: Path) -> Path:
        response = self._client.get_object(Bucket=self.bucket, Key=ref.key)
        metadata = response.get("Metadata") or {}
        schema = metadata.get("schema")
        if schema not in SUPPORTED_SERVING_INDEX_SCHEMAS or metadata.get("sha256") != ref.sha256:
            raise R2IntegrityError(f"R2 serving index metadata mismatch for {ref.key}")
        compressed = response["Body"].read()
        try:
            raw = gzip.decompress(compressed)
        except (OSError, EOFError) as exc:
            raise R2IntegrityError(f"R2 serving index {ref.key} is not valid gzip") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if digest != ref.sha256:
            raise R2IntegrityError(
                f"R2 serving index hash mismatch: expected {ref.sha256}, got {digest}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, destination)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return destination

    def delete(self, key: str) -> None:
        if not key.startswith(f"{self.prefix}/"):
            raise ValueError("serving-index delete key is outside the derived prefix")
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def _head_if_exists(self, key: str) -> dict[str, Any] | None:
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _NOT_FOUND_CODES:
                return None
            raise
        return dict(response)
