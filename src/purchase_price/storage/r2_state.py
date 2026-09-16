from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import boto3
from botocore.exceptions import ClientError

from purchase_price.config import Settings
from purchase_price.storage.r2 import R2ConfigurationError, R2IntegrityError, canonical_json_bytes

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
_SAFE_STATE_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")


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

    def _key(self, name: str) -> str:
        cleaned = name.strip().strip("/")
        if not cleaned or ".." in cleaned or not _SAFE_STATE_NAME.fullmatch(cleaned):
            raise ValueError("state name contains unsafe characters")
        return f"{self.prefix}/{cleaned}.json"
