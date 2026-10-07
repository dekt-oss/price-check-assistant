from __future__ import annotations

import gzip
import hashlib
import io
import os
from pathlib import Path

import pytest

from purchase_price.storage.r2 import R2IntegrityError
from purchase_price.storage.streaming_gzip import write_verified_gzip_body


class _RecordingBody:
    """Like botocore's StreamingBody: read(n) only, and it records every request size."""

    def __init__(self, payload: bytes) -> None:
        self._buffer = io.BytesIO(payload)
        self.requests: list[int | None] = []

    def read(self, amount: int | None = None) -> bytes:
        self.requests.append(amount)
        return self._buffer.read(amount) if amount is not None else self._buffer.read()


def _write(body, destination: Path, sha256: str) -> Path:
    return write_verified_gzip_body(
        body,
        destination,
        expected_sha256=sha256,
        invalid_gzip_message="index is not valid gzip",
        hash_mismatch_prefix="index hash mismatch",
        chunk_bytes=64 * 1024,
    )


def test_streams_large_body_in_bounded_reads(tmp_path: Path) -> None:
    raw = os.urandom(3 * 1024 * 1024) + b"sqlite" * 200_000
    body = _RecordingBody(gzip.compress(raw, compresslevel=1))
    destination = tmp_path / "cache" / "index.sqlite"

    _write(body, destination, hashlib.sha256(raw).hexdigest())

    assert destination.read_bytes() == raw
    # Never one unbounded read of the whole object (that is what ran Production out of memory).
    assert None not in body.requests
    assert max(request for request in body.requests if request is not None) <= 1024 * 1024
    assert len(body.requests) > 3
    assert list(destination.parent.glob("*.tmp")) == []


def test_hash_mismatch_keeps_the_previous_file(tmp_path: Path) -> None:
    destination = tmp_path / "index.sqlite"
    destination.write_bytes(b"previous")

    with pytest.raises(R2IntegrityError, match="index hash mismatch: expected"):
        _write(io.BytesIO(gzip.compress(b"new data")), destination, "0" * 64)

    assert destination.read_bytes() == b"previous"
    assert list(tmp_path.glob("*.tmp")) == []


def test_invalid_gzip_raises_integrity_error(tmp_path: Path) -> None:
    with pytest.raises(R2IntegrityError, match="index is not valid gzip"):
        _write(io.BytesIO(b"not gzip at all"), tmp_path / "index.sqlite", "0" * 64)
    assert list(tmp_path.iterdir()) == []


def test_truncated_gzip_raises_integrity_error(tmp_path: Path) -> None:
    payload = gzip.compress(os.urandom(200_000))
    with pytest.raises(R2IntegrityError, match="index is not valid gzip"):
        _write(io.BytesIO(payload[: len(payload) // 2]), tmp_path / "index.sqlite", "0" * 64)
    assert list(tmp_path.iterdir()) == []


def test_index_stores_use_the_streaming_writer() -> None:
    for path in (
        "src/purchase_price/storage/r2_mfds_identity_index.py",
        "src/purchase_price/storage/r2_serving_index.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        download = source[source.index("def download_sqlite") :]
        download = download[: download.index("\n    def ", 1)]
        assert "write_verified_gzip_body(" in download
        assert ".read()" not in download
        assert "gzip.decompress" not in download
