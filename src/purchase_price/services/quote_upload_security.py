from __future__ import annotations

import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol


class UploadedQuoteFile(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


@dataclass(frozen=True)
class QuoteUploadSecurityPolicy:
    """Current public-PoC handling contract for uploaded quotation originals."""

    allowed_suffixes: frozenset[str]
    raw_retention: str
    raw_content_logging: bool
    external_ai_transfer: bool
    external_ai_retention: str


CURRENT_QUOTE_UPLOAD_SECURITY_POLICY = QuoteUploadSecurityPolicy(
    allowed_suffixes=frozenset({".pdf", ".xlsx", ".xls"}),
    raw_retention="temporary_file_only_deleted_after_parsing",
    raw_content_logging=False,
    external_ai_transfer=False,
    external_ai_retention="not_applicable",
)

_ALLOWED_SUFFIXES = set(CURRENT_QUOTE_UPLOAD_SECURITY_POLICY.allowed_suffixes)


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
