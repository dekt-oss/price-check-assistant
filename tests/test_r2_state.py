from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError

from purchase_price.storage.r2_state import R2LockHeldError, R2OperationalStateStore


class FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body, metadata = self.objects[Key]
        return {"Body": io.BytesIO(body), "Metadata": metadata}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, Metadata: dict, **kwargs):  # noqa: N803
        del Bucket
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = (Body, dict(Metadata))
        return {}

    def delete_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        self.objects.pop(Key, None)
        return {}


def test_operational_state_round_trip_and_missing() -> None:
    client = FakeClient()
    store = R2OperationalStateStore(client=client, bucket="bucket")

    assert store.read_json("track-b/state") is None
    key = store.write_json("track-b/state", {"cursor": 3196, "ok": True})

    assert key == "state/v1/track-b/state.json"
    assert store.read_json("track-b/state") == {"cursor": 3196, "ok": True}
    raw = json.loads(client.objects[key][0])
    assert raw["cursor"] == 3196



def test_operational_lock_blocks_second_owner_until_expired() -> None:
    client = FakeClient()
    store = R2OperationalStateStore(client=client, bucket="bucket")
    now = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    first = store.acquire_lock(
        "mfds/lock",
        owner="run-1",
        ttl_seconds=120,
        now=now,
    )
    assert first["owner"] == "run-1"

    with pytest.raises(R2LockHeldError):
        store.acquire_lock(
            "mfds/lock",
            owner="run-2",
            ttl_seconds=120,
            now=now + timedelta(seconds=60),
        )

    second = store.acquire_lock(
        "mfds/lock",
        owner="run-2",
        ttl_seconds=120,
        now=now + timedelta(seconds=121),
    )
    assert second["owner"] == "run-2"


def test_operational_lock_release_requires_same_owner() -> None:
    client = FakeClient()
    store = R2OperationalStateStore(client=client, bucket="bucket")
    now = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    store.acquire_lock("mfds/lock", owner="run-1", ttl_seconds=120, now=now)

    assert store.release_lock("mfds/lock", owner="other") is False
    assert store.read_json("mfds/lock") is not None
    assert store.release_lock("mfds/lock", owner="run-1") is True
    assert store.read_json("mfds/lock") is None
