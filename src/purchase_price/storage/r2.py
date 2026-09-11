from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from purchase_price.config import Settings

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class R2ConfigurationError(RuntimeError):
    """Raised when the R2 storage contract is incomplete."""


class R2IntegrityError(RuntimeError):
    """Raised when an existing object does not match its content-addressed key."""


@dataclass(frozen=True)
class RawObjectRef:
    bucket: str
    key: str
    payload_hash: str
    uncompressed_bytes: int
    stored_bytes: int
    created: bool


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def payload_sha256(payload: object) -> tuple[str, bytes]:
    canonical = canonical_json_bytes(payload)
    return hashlib.sha256(canonical).hexdigest(), canonical


def _safe_segment(value: str) -> str:
    normalized = _SAFE_SEGMENT_RE.sub("-", value.strip()).strip("-._")
    if not normalized:
        raise ValueError("Object-key segment must contain at least one safe character")
    return normalized


def build_raw_object_key(*, prefix: str, source_operation: str, payload_hash: str) -> str:
    safe_prefix = prefix.strip("/") or "raw/v1"
    safe_operation = _safe_segment(source_operation)
    if len(payload_hash) != 64 or any(ch not in "0123456789abcdef" for ch in payload_hash):
        raise ValueError("payload_hash must be a lowercase SHA-256 hex digest")
    return (
        f"{safe_prefix}/{safe_operation}/{payload_hash[:2]}/{payload_hash[2:4]}/"
        f"{payload_hash}.json.gz"
    )


class R2RawEvidenceStore:
    """Content-addressed R2 storage for public raw procurement evidence.

    The object key is derived from canonical JSON SHA-256. Re-fetching identical source payloads
    therefore resolves to the same object. PostgreSQL should store only the returned object key,
    hash, byte sizes and normalized serving data; private hospital purchasing data must not be
    passed to this store in the public PoC.
    """

    def __init__(self, *, client: Any, bucket: str, raw_prefix: str = "raw/v1") -> None:
        if not bucket.strip():
            raise R2ConfigurationError("R2 bucket name is required")
        self._client = client
        self.bucket = bucket.strip()
        self.raw_prefix = raw_prefix.strip("/") or "raw/v1"

    @classmethod
    def from_settings(cls, settings: Settings) -> R2RawEvidenceStore:
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
        return cls(
            client=client,
            bucket=bucket,
            raw_prefix=settings.r2_raw_prefix,
        )

    def put_public_json(self, *, source_operation: str, payload: object) -> RawObjectRef:
        digest, canonical = payload_sha256(payload)
        key = build_raw_object_key(
            prefix=self.raw_prefix,
            source_operation=source_operation,
            payload_hash=digest,
        )
        compressed = gzip.compress(canonical, compresslevel=6, mtime=0)

        existing = self._head_if_exists(key)
        if existing is not None:
            metadata = existing.get("Metadata") or {}
            stored_hash = metadata.get("sha256")
            if stored_hash != digest:
                raise R2IntegrityError(
                    f"R2 object {key} exists but sha256 metadata does not match its key"
                )
            return RawObjectRef(
                bucket=self.bucket,
                key=key,
                payload_hash=digest,
                uncompressed_bytes=len(canonical),
                stored_bytes=int(existing.get("ContentLength") or len(compressed)),
                created=False,
            )

        safe_operation = _safe_segment(source_operation)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=compressed,
            ContentType="application/json",
            ContentEncoding="gzip",
            Metadata={
                "sha256": digest,
                "schema": "raw-v1",
                "source-operation": safe_operation,
                "data-classification": "public-provenance",
            },
            StorageClass="STANDARD",
        )
        return RawObjectRef(
            bucket=self.bucket,
            key=key,
            payload_hash=digest,
            uncompressed_bytes=len(canonical),
            stored_bytes=len(compressed),
            created=True,
        )

    def get_public_json(self, ref: RawObjectRef) -> object:
        response = self._client.get_object(Bucket=ref.bucket, Key=ref.key)
        body = response["Body"].read()
        canonical = gzip.decompress(body)
        digest = hashlib.sha256(canonical).hexdigest()
        if digest != ref.payload_hash:
            raise R2IntegrityError(
                f"R2 object {ref.key} payload hash mismatch: expected {ref.payload_hash}, got {digest}"
            )
        return json.loads(canonical.decode("utf-8"))

    def probe_read_access(self) -> dict[str, object]:
        response = self._client.list_objects_v2(
            Bucket=self.bucket,
            Prefix=f"{self.raw_prefix}/",
            MaxKeys=1,
        )
        return {
            "bucket": self.bucket,
            "raw_prefix": self.raw_prefix,
            "key_count": int(response.get("KeyCount") or 0),
            "status": "SUCCESS",
        }

    def probe_write_access(self) -> dict[str, object]:
        """Verify write/head/delete permissions outside the locked raw prefix."""

        key = f"smoke/v1/{uuid4().hex}.txt"
        body = b"price-check-assistant-r2-smoke"
        wrote = False
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="text/plain",
                Metadata={"purpose": "connection-smoke"},
                StorageClass="STANDARD",
            )
            wrote = True
            head = self._client.head_object(Bucket=self.bucket, Key=key)
            return {
                "bucket": self.bucket,
                "key": key,
                "stored_bytes": int(head.get("ContentLength") or 0),
                "status": "SUCCESS",
            }
        finally:
            if wrote:
                self._client.delete_object(Bucket=self.bucket, Key=key)

    def _head_if_exists(self, key: str) -> dict[str, Any] | None:
        try:
            return self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            error = exc.response.get("Error") or {}
            code = str(error.get("Code") or "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in _NOT_FOUND_CODES or status == 404:
                return None
            raise
