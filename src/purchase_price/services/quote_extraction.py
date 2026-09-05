# ruff: noqa: I001
from __future__ import annotations

import re
from dataclasses import replace

from purchase_price.services import quote_extraction_core as _core
from purchase_price.services.quote_extraction_core import *  # noqa: F403


_SUMMARY_LABELS = frozenset(
    {
        "합계",
        "합계금액",
        "총계",
        "총액",
        "소계",
        "공급가액",
        "공급가액합계",
        "공급가총액",
        "부가세",
        "부가가치세",
        "세액",
        "vat",
        "견적금액합계",
    }
)
_SUMMARY_PREFIXES = ("합계", "총계", "소계", "공급가액", "부가세", "부가가치세", "세액", "견적금액")


def _is_summary_row(item: QuoteItem) -> bool:  # noqa: F405
    """Reject financial summary rows without suppressing real VAT-named products."""
    label = _core._normalize_header(item.product_name)
    has_secondary_identity = bool(
        _core._normalize_header(item.model_name) or _core._normalize_header(item.specification)
    )
    if not label or has_secondary_identity:
        return False
    if label in _SUMMARY_LABELS:
        return True
    return any(label.startswith(prefix) for prefix in _SUMMARY_PREFIXES)


_original_extract_pdf_context = _core._extract_pdf_context
_original_extract_pdf_quote = _core.extract_pdf_quote


def _extract_pdf_context(texts):
    """Fail closed when document-level VAT evidence conflicts."""
    text_list = tuple(texts)
    context = _original_extract_pdf_context(text_list)
    document = "\n".join(text for text in text_list if text)
    if not document:
        return context

    vat_anchor = r"(?:V\.?\s*A\.?\s*T\.?|VAT|세액)"
    included = bool(
        re.search(rf"(?is){vat_anchor}[\s:：()\-]{{0,30}}(?:Included?|포함)", document)
    )
    excluded = bool(
        re.search(rf"(?is){vat_anchor}[\s:：()\-]{{0,30}}(?:Excluded?|별도|미포함)", document)
    )
    if included and excluded:
        return replace(context, vat_status="")
    return context


def _sync_core_test_seams() -> None:
    """Mirror patchable compatibility-module seams into the extracted core."""
    for name in ("run_local_pdf_ocr", "_extract_with_pdfplumber", "_extract_pypdf_text"):
        if name in globals():
            setattr(_core, name, globals()[name])


def extract_pdf_quote(path):
    _sync_core_test_seams()
    return _original_extract_pdf_quote(path)


# The extraction pipeline is implemented in quote_extraction_core. Patch its policy
# hooks while keeping the established module import and test seams stable.
_core._is_summary_row = _is_summary_row
_core._extract_pdf_context = _extract_pdf_context
_core.extract_pdf_quote = extract_pdf_quote

parse_quote_decimal = _core.parse_quote_decimal
extract_excel_quote = _core.extract_excel_quote
extract_legacy_excel_quote = _core.extract_legacy_excel_quote
extract_quote_file = _core.extract_quote_file
quote_item_query = _core.quote_item_query
QuoteExtractionError = _core.QuoteExtractionError
QuoteItem = _core.QuoteItem
QuoteExtractionResult = _core.QuoteExtractionResult


def __getattr__(name: str):
    """Delegate unchanged private helpers to the extracted core module."""
    return getattr(_core, name)
