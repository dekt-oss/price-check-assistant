from __future__ import annotations

import io
import json

from botocore.exceptions import ClientError

from purchase_price.storage.r2_state import R2OperationalStateStore


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
        del Bucket, kwargs
        self.objects[Key] = (Body, dict(Metadata))
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
