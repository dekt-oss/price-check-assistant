from __future__ import annotations

from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from purchase_price.config import Settings
from purchase_price.storage.r2 import (
    R2IntegrityError,
    R2RawEvidenceStore,
    build_raw_object_key,
    payload_sha256,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.put_count = 0

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        stored = self.objects.get((Bucket, Key))
        if stored is None:
            raise ClientError(
                {
                    "Error": {"Code": "404", "Message": "Not Found"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadObject",
            )
        body = stored["Body"]
        assert isinstance(body, bytes)
        return {
            "Metadata": stored["Metadata"],
            "ContentLength": len(body),
        }

    def put_object(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        metadata = kwargs["Metadata"]
        assert isinstance(metadata, dict)
        self.objects[(bucket, key)] = {"Body": body, "Metadata": metadata}
        self.put_count += 1
        return {"ETag": '"fake"'}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        stored = self.objects[(Bucket, Key)]
        body = stored["Body"]
        assert isinstance(body, bytes)
        return {"Body": BytesIO(body)}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs.get("Prefix") or "")
        count = sum(1 for b, key in self.objects if b == bucket and key.startswith(prefix))
        return {"KeyCount": min(count, int(kwargs.get("MaxKeys") or 1000))}


def test_settings_derive_r2_endpoint_and_require_complete_credentials() -> None:
    incomplete = Settings(r2_account_id="abc123", r2_bucket_name="raw")
    assert incomplete.resolved_r2_endpoint_url == "https://abc123.r2.cloudflarestorage.com"
    assert incomplete.r2_configured is False

    configured = Settings(
        r2_account_id="abc123",
        r2_bucket_name="raw",
        r2_access_key_id="access",
        r2_secret_access_key="secret",
    )
    assert configured.r2_configured is True
    assert configured.resolved_r2_bucket_name == "raw"


def test_settings_accept_existing_r2_bucket_alias() -> None:
    configured = Settings(
        r2_account_id="abc123",
        r2_bucket="price-check-raw",
        r2_access_key_id="access",
        r2_secret_access_key="secret",
    )

    assert configured.r2_configured is True
    assert configured.resolved_r2_bucket_name == "price-check-raw"


def test_content_addressed_write_is_deterministic_and_idempotent() -> None:
    client = FakeS3Client()
    store = R2RawEvidenceStore(client=client, bucket="price-check-raw")
    payload = {"b": 2, "a": 1, "nested": {"name": "인공호흡기"}}

    first = store.put_public_json(source_operation="getSpcifyPrdlstPrcureInfoList", payload=payload)
    second = store.put_public_json(
        source_operation="getSpcifyPrdlstPrcureInfoList",
        payload={"nested": {"name": "인공호흡기"}, "a": 1, "b": 2},
    )

    assert first.key == second.key
    assert first.payload_hash == second.payload_hash
    assert first.created is True
    assert second.created is False
    assert client.put_count == 1
    assert first.stored_bytes > 0
    assert first.uncompressed_bytes > 0

    stored = client.objects[(first.bucket, first.key)]
    metadata = stored["Metadata"]
    assert isinstance(metadata, dict)
    assert metadata["sha256"] == first.payload_hash
    assert metadata["data-classification"] == "public-provenance"


def test_roundtrip_verifies_payload_hash_and_smokes_permissions() -> None:
    client = FakeS3Client()
    store = R2RawEvidenceStore(client=client, bucket="price-check-raw")
    payload = {"prdctUprc": "97500000", "qty": 2}

    ref = store.put_public_json(source_operation="track-b", payload=payload)

    assert store.get_public_json(ref) == payload
    assert store.probe_read_access()["status"] == "SUCCESS"
    assert store.probe_write_access()["status"] == "SUCCESS"
    assert all(not key.startswith("smoke/") for _, key in client.objects)


def test_existing_object_with_wrong_hash_metadata_fails_closed() -> None:
    client = FakeS3Client()
    store = R2RawEvidenceStore(client=client, bucket="price-check-raw")
    payload = {"record": 1}
    digest, _ = payload_sha256(payload)
    key = build_raw_object_key(prefix="raw/v1", source_operation="track-b", payload_hash=digest)
    client.objects[("price-check-raw", key)] = {
        "Body": b"not-used",
        "Metadata": {"sha256": "0" * 64},
    }

    with pytest.raises(R2IntegrityError):
        store.put_public_json(source_operation="track-b", payload=payload)
