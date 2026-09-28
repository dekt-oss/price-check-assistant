from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError

from purchase_price.config import Settings
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError, canonical_json_bytes

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
_SAFE_STATE_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_PRECONDITION_CODES = {"412", "PreconditionFailed"}


class R2LockHeldError(RuntimeError):
    """Raised when a non-expired operational lock is already held."""


class R2OperationalStateStore:
    """Small mutable JSON checkpoints kept outside the immutable raw evidence prefix."""

    def __init__(self, *, client: Any, bucket: str, prefix: str = "state/v1") -> None:
        if not bucket.strip():
            raise R2ConfigurationError("R2 bucket name is required")
        self._client = client
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/") or "state/v1"

    @classmethod
    def from_settings(cls, settings: Settings) -> R2OperationalStateStore:
        if not settings.r2_configured:
            raise R2ConfigurationError("R2 is not fully configured for operational state")
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
        return cls(client=client, bucket=bucket)

    def read_json(self, name: str) -> dict[str, Any] | None:
        key = self._key(name)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _NOT_FOUND_CODES:
                return None
            raise
        metadata = response.get("Metadata") or {}
        if (
            metadata.get("schema") != "operational-state-v1"
            or metadata.get("data-classification") != "public-operational-metadata"
        ):
            raise R2IntegrityError(f"R2 state object {key} metadata is invalid")
        body = response["Body"].read()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise R2IntegrityError(f"R2 state object {key} is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise R2IntegrityError(f"R2 state object {key} must be a JSON object")
        return dict(payload)

    def write_json(self, name: str, payload: Mapping[str, Any]) -> str:
        key = self._key(name)
        body = canonical_json_bytes(dict(payload))
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            Metadata={
                "schema": "operational-state-v1",
                "data-classification": "public-operational-metadata",
            },
            StorageClass="STANDARD",
        )
        return key


    def acquire_lock(
        self,
        name: str,
        *,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if ttl_seconds < 1:
            raise ValueError("lock ttl_seconds must be positive")
        owner = owner.strip()
        if not owner:
            raise ValueError("lock owner is required")

        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        payload = {
            "schema": "operational-lock-v1",
            "owner": owner,
            "acquired_at": current.isoformat(),
            "expires_at": (current + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        key = self._key(name)
        try:
            self._put_lock_if_absent(key, payload)
            return payload
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in _PRECONDITION_CODES:
                raise

        existing = self.read_json(name)
        if existing is None:
            try:
                self._put_lock_if_absent(key, payload)
                return payload
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in _PRECONDITION_CODES:
                    raise
                raise R2LockHeldError(f"R2 operational lock {name} was acquired concurrently") from exc

        expires_at = str(existing.get("expires_at") or "").strip()
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise R2IntegrityError(f"R2 operational lock {name} has invalid expiry") from exc
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)

        if expiry > current:
            raise R2LockHeldError(
                f"R2 operational lock {name} is held by {existing.get('owner') or 'unknown'}"
            )

        self._client.delete_object(Bucket=self.bucket, Key=key)
        try:
            self._put_lock_if_absent(key, payload)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _PRECONDITION_CODES:
                raise R2LockHeldError(
                    f"R2 operational lock {name} was reacquired while clearing a stale lock"
                ) from exc
            raise
        return payload

    def release_lock(self, name: str, *, owner: str) -> bool:
        payload = self.read_json(name)
        if payload is None:
            return False
        if payload.get("schema") != "operational-lock-v1":
            raise R2IntegrityError(f"R2 operational lock {name} schema is invalid")
        if str(payload.get("owner") or "") != owner:
            return False
        self._client.delete_object(Bucket=self.bucket, Key=self._key(name))
        return True

    def _put_lock_if_absent(self, key: str, payload: Mapping[str, Any]) -> None:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=canonical_json_bytes(dict(payload)),
            ContentType="application/json",
            Metadata={
                "schema": "operational-state-v1",
                "data-classification": "public-operational-metadata",
            },
            StorageClass="STANDARD",
            IfNoneMatch="*",
        )

    def _key(self, name: str) -> str:
        cleaned = name.strip().strip("/")
        if not cleaned or ".." in cleaned or not _SAFE_STATE_NAME.fullmatch(cleaned):
            raise ValueError("state name contains unsafe characters")
        return f"{self.prefix}/{cleaned}.json"
