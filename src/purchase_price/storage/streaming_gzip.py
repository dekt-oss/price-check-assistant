"""Write a gzip-compressed R2 object to disk without holding it in memory.

The derived SQLite indexes grew past 1.5 GB uncompressed (MFDS identity, 2026-10-07). Reading the
whole body and calling ``gzip.decompress`` kept the compressed and the decompressed copies in RAM
at once, which exceeded the Streamlit Community Cloud memory limit and took Production down on
the first search after a restart. This helper decompresses in fixed-size chunks straight into a
temporary file, hashes as it goes, and only then moves the file into place.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
import threading
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from purchase_price.storage.r2 import R2IntegrityError

CHUNK_BYTES = 1024 * 1024

# The start-up prefetch reads progress of downloads it starts without threading a callback
# through every loader: it registers one for its own thread (see report_progress_to).
_PROGRESS = threading.local()


@contextmanager
def report_progress_to(callback: Callable[[int, int | None], None]) -> Iterator[None]:
    """Send ``callback(compressed_bytes_read, total_bytes)`` for downloads on this thread."""

    previous = getattr(_PROGRESS, "callback", None)
    _PROGRESS.callback = callback
    try:
        yield
    finally:
        _PROGRESS.callback = previous


class _CountingReader:
    def __init__(self, body: Any, total: int | None, callback: Callable[[int, int | None], None]):
        self._body = body
        self._total = total
        self._callback = callback
        self._done = 0

    def read(self, size: int = -1) -> bytes:
        data = self._body.read(size)
        self._done += len(data)
        try:
            self._callback(self._done, self._total)
        except Exception:
            pass
        return data


def write_verified_gzip_body(
    body: Any,
    destination: Path,
    *,
    expected_sha256: str,
    invalid_gzip_message: str,
    hash_mismatch_prefix: str,
    chunk_bytes: int = CHUNK_BYTES,
    total_bytes: int | None = None,
) -> Path:
    """Stream-decompress ``body`` (anything with ``read(n)``) into ``destination``.

    Raises R2IntegrityError when the body is not gzip or the decompressed SHA-256 differs; the
    destination is never replaced by a partial or unverified file.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    callback = getattr(_PROGRESS, "callback", None)
    if callback is not None:
        body = _CountingReader(body, total_bytes, callback)
    digest = hashlib.sha256()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            try:
                with gzip.GzipFile(fileobj=body, mode="rb") as stream:
                    while True:
                        chunk = stream.read(chunk_bytes)
                        if not chunk:
                            break
                        digest.update(chunk)
                        handle.write(chunk)
            except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
                raise R2IntegrityError(invalid_gzip_message) from exc
            # No fsync: forcing 2 GB to disk added seconds to every cold start, and these are
            # rebuildable caches whose SHA-256 the loaders check before first use in a process.
            handle.flush()
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise R2IntegrityError(f"{hash_mismatch_prefix}: expected {expected_sha256}, got {actual}")
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return destination

