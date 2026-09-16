from __future__ import annotations

import io
from pathlib import Path

from botocore.exceptions import ClientError

from purchase_price.storage.r2_serving_index import R2ServingIndexStore


class FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str], str]] = {}

    def head_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
        body, metadata, _ = self.objects[Key]
        return {"ContentLength": len(body), "Metadata": metadata}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: dict[str, str],
        ContentType: str,
        **kwargs,
    ):  # noqa: N803
        del Bucket, kwargs
        self.objects[Key] = (Body, dict(Metadata), ContentType)
        return {}

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        body, metadata, _ = self.objects[Key]
        return {"Body": io.BytesIO(body), "Metadata": metadata}

    def delete_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        self.objects.pop(Key, None)
        return {}


def test_serving_index_round_trip_and_prune(tmp_path: Path) -> None:
    client = FakeClient()
    store = R2ServingIndexStore(client=client, bucket="bucket")
    source = tmp_path / "index.sqlite"
    source.write_bytes(b"sqlite-public-index")

    ref = store.put_sqlite(source)
    restored = tmp_path / "restored.sqlite"
    store.download_sqlite(ref, restored)

    assert restored.read_bytes() == source.read_bytes()
    assert ref.key.startswith("derived/v1/track-b-serving/")
    assert client.objects[ref.key][2] == "application/x-sqlite3"

    store.delete(ref.key)
    assert ref.key not in client.objects
