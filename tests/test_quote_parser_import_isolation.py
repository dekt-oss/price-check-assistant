import ast
import builtins
from pathlib import Path

import pytest

from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_excel_quote,
    extract_legacy_excel_quote,
    extract_pdf_quote,
)

ROOT = Path(__file__).resolve().parents[1]
QUOTE_EXTRACTION = ROOT / "src" / "purchase_price" / "services" / "quote_extraction.py"
PARSER_PACKAGES = {"openpyxl", "xlrd", "pypdf"}


def _block_package_import(monkeypatch: pytest.MonkeyPatch, package: str) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == package or name.startswith(f"{package}."):
            raise ModuleNotFoundError(f"blocked test import: {package}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_quote_extraction_has_no_top_level_runtime_parser_imports() -> None:
    tree = ast.parse(QUOTE_EXTRACTION.read_text(encoding="utf-8"))
    imported: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])

    assert imported.isdisjoint(PARSER_PACKAGES)


def test_missing_pypdf_fails_only_when_pdf_extraction_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _block_package_import(monkeypatch, "pypdf")

    with pytest.raises(QuoteExtractionError, match="pypdf"):
        extract_pdf_quote(tmp_path / "quote.pdf")


def test_missing_openpyxl_fails_only_when_xlsx_extraction_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _block_package_import(monkeypatch, "openpyxl")

    with pytest.raises(QuoteExtractionError, match="openpyxl"):
        extract_excel_quote(tmp_path / "quote.xlsx")


def test_missing_xlrd_fails_only_when_xls_extraction_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _block_package_import(monkeypatch, "xlrd")

    with pytest.raises(QuoteExtractionError, match="xlrd"):
        extract_legacy_excel_quote(tmp_path / "quote.xls")
