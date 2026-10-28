from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path

from botocore.exceptions import ClientError

from purchase_price.storage.r2_serving_index import R2ServingIndexRef, R2ServingIndexStore


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
        body = Body.read() if hasattr(Body, "read") else Body
        self.objects[Key] = (body, dict(Metadata), ContentType)
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


def test_serving_index_download_accepts_legacy_v1_for_zero_downtime_rebuild(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    store = R2ServingIndexStore(client=client, bucket="bucket")
    raw = b"legacy-sqlite-public-index"
    digest = hashlib.sha256(raw).hexdigest()
    key = f"derived/v1/track-b-serving/{digest[:2]}/{digest}.sqlite.gz"
    client.objects[key] = (
        gzip.compress(raw, mtime=0),
        {"sha256": digest, "schema": "track-b-serving-sqlite-v1"},
        "application/x-sqlite3",
    )
    ref = R2ServingIndexRef(
        key=key,
        sha256=digest,
        stored_bytes=len(client.objects[key][0]),
        uncompressed_bytes=len(raw),
    )
    destination = tmp_path / "legacy-restored.sqlite"

    store.download_sqlite(ref, destination)

    assert destination.read_bytes() == raw


def test_put_sqlite_streams_through_a_temp_file(tmp_path: Path) -> None:
    """Review B-02: same gzip bytes as before, no temp file left, memory not proportional to size."""

    import gzip
    import random
    import tracemalloc

    client = FakeClient()
    store = R2ServingIndexStore(client=client, bucket="bucket")
    source = tmp_path / "index.sqlite"
    rng = random.Random(7)
    source.write_bytes(b"".join(rng.randbytes(1024) + bytes(3072) for _ in range(8 * 1024)))  # 32 MiB

    tracemalloc.start()
    ref = store.put_sqlite(source)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    raw = source.read_bytes()
    stored = client.objects[ref.key][0]
    before = gzip.compress(raw, compresslevel=6, mtime=0)
    # Header byte 9 is the OS code, platform-dependent in gzip.compress itself.
    assert stored[:9] == before[:9] and stored[10:] == before[10:]
    assert gzip.decompress(stored) == raw
    assert ref.stored_bytes == len(stored)
    assert ref.uncompressed_bytes == len(raw)
    # The fake client keeps the uploaded body (~8 MiB); before the change the peak was over 64 MiB.
    assert peak < len(stored) + 4 * 1024 * 1024
    assert sorted(p.name for p in tmp_path.iterdir()) == ["index.sqlite"]
