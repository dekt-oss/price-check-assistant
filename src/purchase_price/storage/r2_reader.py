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
        prefix = f"{self.raw_prefix}/"
        if source_operation:
            operation = source_operation.strip("/")
            if not operation or "/" in operation:
                raise ValueError("source_operation must be one object-key segment")
            prefix = f"{prefix}{operation}/"

        results: list[R2RawObject] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": min(1000, limit - len(results)) if limit else 1000,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            contents = response.get("Contents") or []
            if not isinstance(contents, list):
                raise R2IntegrityError("R2 ListObjectsV2 returned invalid Contents")
            for item in contents:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("Key") or "")
                if not key.endswith(".json.gz"):
                    continue
                payload_hash = self._hash_from_key(key)
                last_modified = item.get("LastModified")
                results.append(
                    R2RawObject(
                        bucket=self.bucket,
                        key=key,
                        payload_hash=payload_hash,
                        stored_bytes=int(item.get("Size") or 0),
                        last_modified=last_modified if isinstance(last_modified, datetime) else None,
                    )
                )
                if limit is not None and len(results) >= limit:
                    return tuple(results)
            if not response.get("IsTruncated"):
                break
            continuation_token = str(response.get("NextContinuationToken") or "").strip()
            if not continuation_token:
                raise R2IntegrityError("R2 ListObjectsV2 truncated without continuation token")
        return tuple(results)

    def get_public_json(self, obj: R2RawObject) -> object:
        if obj.bucket != self.bucket:
            raise R2IntegrityError("R2 object bucket does not match reader bucket")
        expected_hash = self._hash_from_key(obj.key)
        if expected_hash != obj.payload_hash:
            raise R2IntegrityError("R2 object reference hash does not match content-addressed key")
        response = self._client.get_object(Bucket=self.bucket, Key=obj.key)
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
        filename = key.rsplit("/", 1)[-1]
        if not filename.endswith(".json.gz"):
            raise R2IntegrityError(f"R2 raw object key has unexpected suffix: {key}")
        digest = filename[: -len(".json.gz")]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise R2IntegrityError(f"R2 raw object key lacks a lowercase SHA-256 digest: {key}")
        return digest
