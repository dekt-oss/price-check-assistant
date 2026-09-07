# ruff: noqa: I001
from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from purchase_price.services import quote_extraction_core as _core
from purchase_price.services.quote_extraction_core import *  # noqa: F403
from purchase_price.services.quote_single_item_ocr_fallback import (
    recover_single_item_scanned_quote,
)


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


@dataclass(frozen=True)
class ExcludedRow:
    """Summary row intentionally excluded from quote items, with reviewable provenance."""

    label: str
    source_sheet: str
    source_row: int
    amount: Decimal | None = None


_EXCLUDED_ROWS: ContextVar[tuple[ExcludedRow, ...]] = ContextVar("quote_excluded_rows", default=())
_VAT_CONFLICT: ContextVar[bool] = ContextVar("quote_vat_conflict", default=False)
_VAT_CONFLICT_WARNING = (
    '문서에 "VAT 포함"과 "VAT 별도/미포함" 표현이 함께 있어 VAT를 확정하지 않았습니다. '
    "원문을 대조해 직접 확인하세요."
)
_SINGLE_ITEM_FOOTER_WARNING = (
    "일반 표 추출은 실패했지만 단일품목 견적의 품명과 하단 TOTAL PRICE/개별단가를 "
    "별도 OCR로 연결해 1건을 복원했습니다. 제품명·가격·VAT·보증·설치조건을 원문과 대조하세요."
)


def _record_excluded_row(item: QuoteItem) -> None:  # noqa: F405
    row = ExcludedRow(
        label=item.product_name or item.model_name or item.specification or "요약행",
        source_sheet=item.source_sheet,
        source_row=item.source_row,
        amount=item.total_amount if item.total_amount is not None else item.unit_price,
    )
    current = _EXCLUDED_ROWS.get()
    if row not in current:
        _EXCLUDED_ROWS.set((*current, row))


def _is_summary_row(item: QuoteItem) -> bool:  # noqa: F405
    """Reject financial summary rows without suppressing real VAT-named products."""
    label = _core._normalize_header(item.product_name)
    has_secondary_identity = bool(
        _core._normalize_header(item.model_name) or _core._normalize_header(item.specification)
    )
    if not label or has_secondary_identity:
        return False
    is_summary = label in _SUMMARY_LABELS or any(
        label.startswith(prefix) for prefix in _SUMMARY_PREFIXES
    )
    if is_summary:
        _record_excluded_row(item)
    return is_summary


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
        _VAT_CONFLICT.set(True)
        return replace(context, vat_status="")
    return context


@dataclass(frozen=True)
class QuoteExtractionResult(_core.QuoteExtractionResult):
    excluded_rows: tuple[ExcludedRow, ...] = ()


def _adapt_result(result: _core.QuoteExtractionResult) -> QuoteExtractionResult:
    warnings = result.warnings
    if _VAT_CONFLICT.get() and _VAT_CONFLICT_WARNING not in warnings:
        warnings = (*warnings, _VAT_CONFLICT_WARNING)
    return QuoteExtractionResult(
        items=result.items,
        warnings=warnings,
        excluded_rows=_EXCLUDED_ROWS.get(),
    )


def _run_with_tracking(extractor, path: Path) -> QuoteExtractionResult:
    excluded_token = _EXCLUDED_ROWS.set(())
    vat_token = _VAT_CONFLICT.set(False)
    try:
        return _adapt_result(extractor(path))
    finally:
        _EXCLUDED_ROWS.reset(excluded_token)
        _VAT_CONFLICT.reset(vat_token)


def _sync_core_test_seams() -> None:
    """Mirror patchable compatibility-module seams into the extracted core."""
    for name in ("run_local_pdf_ocr", "_extract_with_pdfplumber", "_extract_pypdf_text"):
        if name in globals():
            setattr(_core, name, globals()[name])


def extract_pdf_quote(path: Path) -> QuoteExtractionResult:
    _sync_core_test_seams()
    result = _run_with_tracking(_original_extract_pdf_quote, path)
    if result.items:
        return result

    recovered = recover_single_item_scanned_quote(path)
    if recovered is None:
        return result

    warnings = tuple(
        warning
        for warning in result.warnings
        if "의미 있는 품목/가격 행을 식별하지 못했습니다" not in warning
    )
    return QuoteExtractionResult(
        items=(recovered,),
        warnings=(*warnings, _SINGLE_ITEM_FOOTER_WARNING),
        excluded_rows=result.excluded_rows,
    )


def extract_excel_quote(path: Path) -> QuoteExtractionResult:
    return _run_with_tracking(_core.extract_excel_quote, path)


def extract_legacy_excel_quote(path: Path) -> QuoteExtractionResult:
    return _run_with_tracking(_core.extract_legacy_excel_quote, path)


def extract_quote_file(path: Path) -> QuoteExtractionResult:
    suffix = path.suffix.casefold()
    if suffix == ".xlsx":
        return extract_excel_quote(path)
    if suffix == ".xls":
        return extract_legacy_excel_quote(path)
    if suffix == ".pdf":
        return extract_pdf_quote(path)
    raise QuoteExtractionError(  # noqa: F405
        "지원하지 않는 파일 형식입니다. .xlsx/.xls/.pdf만 업로드하세요."
    )


# The extraction pipeline is implemented in quote_extraction_core. Patch its policy
# hooks while keeping the established module import and test seams stable.
_core._is_summary_row = _is_summary_row
_core._extract_pdf_context = _extract_pdf_context
_core.extract_pdf_quote = extract_pdf_quote

parse_quote_decimal = _core.parse_quote_decimal
quote_item_query = _core.quote_item_query
QuoteExtractionError = _core.QuoteExtractionError
QuoteItem = _core.QuoteItem


def __getattr__(name: str):
    """Delegate unchanged private helpers to the extracted core module."""
    return getattr(_core, name)
