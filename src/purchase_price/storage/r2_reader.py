from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import boto3

from purchase_price.config import Settings
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError


@dataclass(frozen=True)
class R2RawObject:
    bucket: str
    key: str
    payload_hash: str
    stored_bytes: int
    last_modified: datetime | None


@dataclass(frozen=True)
class R2RawObjectPage:
    objects: tuple[R2RawObject, ...]
    next_cursor: str | None
    has_more: bool


class R2RawEvidenceReader:
    """Read-only access to content-addressed raw evidence in R2.

    This class intentionally exposes no write/delete method. It is used by normalization and audit
    jobs that must be operationally independent from public-data collection.
    """

    def __init__(self, *, client: Any, bucket: str, raw_prefix: str = "raw/v1") -> None:
        if not bucket.strip():
            raise R2ConfigurationError("R2 bucket name is required")
        self._client = client
        self.bucket = bucket.strip()
        self.raw_prefix = raw_prefix.strip("/") or "raw/v1"

    @classmethod
    def from_settings(cls, settings: Settings) -> R2RawEvidenceReader:
        if not settings.r2_configured:
            raise R2ConfigurationError(
                "R2 is not fully configured; set R2_ACCOUNT_ID or R2_ENDPOINT_URL, "
                "R2_BUCKET_NAME (or R2_BUCKET), R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY"
            )
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
        return cls(client=client, bucket=bucket, raw_prefix=settings.r2_raw_prefix)

    def list_public_json(
        self,
        *,
        source_operation: str | None = None,
        limit: int | None = None,
    ) -> tuple[R2RawObject, ...]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        results: list[R2RawObject] = []
        cursor: str | None = None
        while True:
            page = self.list_public_json_page(
                source_operation=source_operation,
                limit=min(1000, limit - len(results)) if limit else 1000,
                after_key=cursor,
            )
            results.extend(page.objects)
            if limit is not None and len(results) >= limit:
                return tuple(results[:limit])
            if not page.has_more:
                break
            if page.next_cursor == cursor:
                raise R2IntegrityError("R2 listing did not advance its resume key")
            cursor = page.next_cursor
        return tuple(results)

    def list_public_json_page(
        self,
        *,
        source_operation: str | None = None,
        limit: int = 1000,
        after_key: str | None = None,
    ) -> R2RawObjectPage:
        """Read one bounded, lexically ordered page; cursor is the last listed key.

        StartAfter is stable across process restarts, unlike an opaque S3 continuation token.
        Callers must checkpoint only after processing all returned objects successfully.
        """
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        prefix = f"{self.raw_prefix}/"
        if source_operation:
            operation = source_operation.strip("/")
            if not operation or "/" in operation:
                raise ValueError("source_operation must be one object-key segment")
            prefix += f"{operation}/"
        if after_key is not None and not after_key.startswith(prefix):
            raise ValueError("after_key must be inside the selected prefix")
        kwargs: dict[str, object] = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": limit}
        if after_key is not None:
            kwargs["StartAfter"] = after_key
        response = self._client.list_objects_v2(**kwargs)
        contents = response.get("Contents") or []
        if not isinstance(contents, list):
            raise R2IntegrityError("R2 ListObjectsV2 returned invalid Contents")
        if any(not isinstance(item, dict) for item in contents):
            raise R2IntegrityError("R2 ListObjectsV2 returned an invalid object entry")
        keys = [str(item.get("Key") or "") for item in contents]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise R2IntegrityError("R2 ListObjectsV2 keys are not strictly ordered")
        if any(not key.startswith(prefix) or (after_key is not None and key <= after_key) for key in keys):
            raise R2IntegrityError("R2 ListObjectsV2 returned a key outside the requested range")
        objects = tuple(
            R2RawObject(
                bucket=self.bucket,
                key=key,
                payload_hash=self._hash_from_key(key),
                stored_bytes=int(item.get("Size") or 0),
                last_modified=(
                    item.get("LastModified")
                    if isinstance(item.get("LastModified"), datetime)
                    else None
                ),
            )
            for item, key in zip(contents, keys, strict=True)
            if key.endswith(".json.gz")
        )
        has_more = bool(response.get("IsTruncated"))
        if has_more and not keys:
            raise R2IntegrityError("R2 ListObjectsV2 truncated without a resume key")
        return R2RawObjectPage(objects, keys[-1] if keys else None, has_more)

    def get_public_json(self, obj: R2RawObject) -> object:
        if obj.bucket != self.bucket:
            raise R2IntegrityError("R2 object bucket does not match reader bucket")
        expected_hash = self._hash_from_key(obj.key)
        if expected_hash != obj.payload_hash:
            raise R2IntegrityError("R2 object reference hash does not match content-addressed key")
        response = self._client.get_object(Bucket=self.bucket, Key=obj.key)
        metadata = response.get("Metadata") or {}
        operation = obj.key[len(self.raw_prefix) + 1 :].split("/", 1)[0]
        if (
            metadata.get("sha256") != expected_hash
            or metadata.get("schema") != "raw-v1"
            or metadata.get("source-operation") != operation
            or metadata.get("data-classification") != "public-provenance"
        ):
            raise R2IntegrityError(f"R2 object {obj.key} metadata does not match its key")
        body = response["Body"].read()
        try:
            canonical = gzip.decompress(body)
        except (OSError, EOFError) as exc:
            raise R2IntegrityError(f"R2 object {obj.key} is not valid gzip") from exc
        digest = hashlib.sha256(canonical).hexdigest()
        if digest != expected_hash:
            raise R2IntegrityError(
                f"R2 object {obj.key} payload hash mismatch: expected {expected_hash}, got {digest}"
            )
        try:
            return json.loads(canonical.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise R2IntegrityError(f"R2 object {obj.key} is not valid canonical JSON") from exc

    def _hash_from_key(self, key: str) -> str:
        required_prefix = f"{self.raw_prefix}/"
        if not key.startswith(required_prefix):
            raise R2IntegrityError(f"R2 object key is outside raw prefix: {key}")
        parts = key[len(required_prefix) :].split("/")
        if len(parts) != 4 or not all(parts):
            raise R2IntegrityError(f"R2 raw object key has invalid content-addressed layout: {key}")
        _, first_shard, second_shard, filename = parts
        if not filename.endswith(".json.gz"):
            raise R2IntegrityError(f"R2 raw object key has unexpected suffix: {key}")
        digest = filename[: -len(".json.gz")]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise R2IntegrityError(f"R2 raw object key lacks a lowercase SHA-256 digest: {key}")
        if first_shard != digest[:2] or second_shard != digest[2:4]:
            raise R2IntegrityError(f"R2 raw object key shards do not match its SHA-256 digest: {key}")
        return digest
