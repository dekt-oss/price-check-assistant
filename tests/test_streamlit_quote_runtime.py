from __future__ import annotations

import sys
from pathlib import Path

import pytest

import purchase_price.services.quote_extraction as quote_extraction
from purchase_price.services.quote_extraction import QuoteExtractionError


def test_quote_extraction_module_does_not_import_xlrd_eagerly() -> None:
    assert "xlrd" not in quote_extraction.__dict__


def test_missing_xlrd_only_blocks_legacy_xls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setitem(sys.modules, "xlrd", None)
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"not-needed-for-missing-module-test")

    with pytest.raises(QuoteExtractionError, match="xlrd"):
        quote_extraction.extract_legacy_excel_quote(path)
