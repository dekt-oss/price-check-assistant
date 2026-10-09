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
# Streamlit Cloud counts the page cache of files the app writes against its ~2.7 GB memory limit.
# Writing the ~2.9 GB of indexes after each restart put the app over that limit (2026-10-09), so
# written data is flushed to disk and dropped from the cache every 64 MB.
DROP_CACHE_EVERY_BYTES = 64 * 1024 * 1024


def drop_file_cache(fileno: int) -> None:
    """Write dirty pages out and tell the kernel it may forget this file's cached pages.

    No-op where ``posix_fadvise`` does not exist (Windows, local development).
    """

    advise = getattr(os, "posix_fadvise", None)
    if advise is None:
        return
    try:
        os.fdatasync(fileno)
        advise(fileno, 0, 0, os.POSIX_FADV_DONTNEED)
    except OSError:
        pass


def forget_cached_pages(path: os.PathLike[str] | str) -> bool:
    """Ask the kernel to drop a read-only file's cached pages; True when the hint was given.

    The serving indexes are read through SQLite, and every page a search touches stays in the
    container's page cache, which Streamlit Cloud counts against the app's memory limit. No-op
    where ``posix_fadvise`` does not exist (Windows, local development).
    """

    advise = getattr(os, "posix_fadvise", None)
    if advise is None:
        return False
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        advise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


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
                written_since_drop = 0
                with gzip.GzipFile(fileobj=body, mode="rb") as stream:
                    while True:
                        chunk = stream.read(chunk_bytes)
                        if not chunk:
                            break
                        digest.update(chunk)
                        handle.write(chunk)
                        written_since_drop += len(chunk)
                        if written_since_drop >= DROP_CACHE_EVERY_BYTES:
                            handle.flush()
                            drop_file_cache(handle.fileno())
                            written_since_drop = 0
            except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
                raise R2IntegrityError(invalid_gzip_message) from exc
            handle.flush()
            drop_file_cache(handle.fileno())
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise R2IntegrityError(f"{hash_mismatch_prefix}: expected {expected_sha256}, got {actual}")
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return destination

