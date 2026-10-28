from __future__ import annotations

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
from purchase_price.storage.streaming_gzip import gzip_file_for_upload, write_verified_gzip_body

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
SERVING_INDEX_SCHEMA = "track-b-serving-sqlite-v3"
LEGACY_SERVING_INDEX_SCHEMAS = {"track-b-serving-sqlite-v1", "track-b-serving-sqlite-v2"}
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
        # Hash and compress through a temporary file, then upload from it: the index never sits
        # in memory whole (review B-02). Same key, metadata and gzip bytes as before.
        with gzip_file_for_upload(path) as upload:
            digest = upload.sha256
            key = f"{self.prefix}/{digest[:2]}/{digest}.sqlite.gz"

            existing = self._head_if_exists(key)
            if existing is not None:
                metadata = existing.get("Metadata") or {}
                if metadata.get("sha256") != digest or metadata.get("schema") != SERVING_INDEX_SCHEMA:
                    raise R2IntegrityError(f"R2 serving index metadata mismatch for {key}")
                return R2ServingIndexRef(
                    key=key,
                    sha256=digest,
                    stored_bytes=int(existing.get("ContentLength") or upload.stored_bytes),
                    uncompressed_bytes=upload.uncompressed_bytes,
                )

            if self._quota_store is not None:
                usage = self._quota_store.quota_status(refresh=True)
                if usage.stored_bytes + upload.stored_bytes > usage.hard_limit_bytes:
                    raise R2QuotaExceededError(
                        "R2 serving index write would exceed the configured zero-cost hard limit"
                    )
            with upload.path.open("rb") as body:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    ContentLength=upload.stored_bytes,
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
                stored_bytes=upload.stored_bytes,
                uncompressed_bytes=upload.uncompressed_bytes,
            )

    def download_sqlite(self, ref: R2ServingIndexRef, destination: Path) -> Path:
        response = self._client.get_object(Bucket=self.bucket, Key=ref.key)
        metadata = response.get("Metadata") or {}
        schema = metadata.get("schema")
        if schema not in SUPPORTED_SERVING_INDEX_SCHEMAS or metadata.get("sha256") != ref.sha256:
            raise R2IntegrityError(f"R2 serving index metadata mismatch for {ref.key}")
        return write_verified_gzip_body(
            response["Body"],
            destination,
            expected_sha256=ref.sha256,
            invalid_gzip_message=f"R2 serving index {ref.key} is not valid gzip",
            hash_mismatch_prefix="R2 serving index hash mismatch",
            total_bytes=_content_length(response),
        )

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


def _content_length(response: dict[str, Any]) -> int | None:
    try:
        return int(response.get("ContentLength") or 0) or None
    except (TypeError, ValueError):
        return None
