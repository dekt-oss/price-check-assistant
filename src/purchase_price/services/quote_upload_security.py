from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol


class UploadedQuoteFile(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


_ALLOWED_SUFFIXES = {".pdf", ".xlsx", ".xls"}


@contextmanager
def temporary_quote_upload(uploaded_file: UploadedQuoteFile) -> Iterator[Path]:
    """Materialize an upload only for parsing and always delete the raw bytes afterward."""

    suffix = Path(uploaded_file.name).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported quote upload suffix: {suffix or '<none>'}")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(uploaded_file.getvalue())
            temp_path = Path(handle.name)
        yield temp_path
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
