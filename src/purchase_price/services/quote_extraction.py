# ruff: noqa: I001
from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from purchase_price.services import quote_extraction_core as _core
from purchase_price.services.quote_extraction_core import *  # noqa: F403
from purchase_price.services.image_ocr import ImageOcrUnavailableError, run_local_image_ocr
from purchase_price.services.quote_image_ruled_table import recover_sparse_ruled_table_image_quote
from purchase_price.services.quote_ruled_table_ocr import (
    recover_sparse_ruled_table_scanned_quote,
)
from purchase_price.services.quote_single_item_ocr_fallback import (
    recover_single_item_from_text,
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
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})


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
    "일반 표 추출은 실패했지만 단일품목 견적에서 명시된 품명과 가격행/합계 근거를 "
    "별도 OCR로 연결해 1건을 복원했습니다. OCR 오인 가능성이 있으므로 제품명·규격/모델·가격·VAT·보증·설치조건을 원문과 대조하세요."
)
_IMAGE_OCR_WARNING = (
    "PNG/JPEG 견적 이미지를 로컬 Tesseract(kor+eng) OCR로 처리했습니다. 사진 기울기·압축·표 선·글자 크기에 따라 "
    "오인식할 수 있으므로 제품명·모델·규격·수량·가격·VAT·설치·보증을 원본 이미지와 대조하세요."
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

    recovered = recover_sparse_ruled_table_scanned_quote(path)
    if recovered is None:
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


def _extract_image_quote_core(path: Path) -> _core.QuoteExtractionResult:
    try:
        ocr = run_local_image_ocr(path, _core._resolve_header_field)
    except ImageOcrUnavailableError as exc:
        raise QuoteExtractionError(  # noqa: F405
            "PNG/JPEG 견적 이미지의 로컬 OCR을 실행할 수 없습니다. Pillow/pytesseract 및 Tesseract kor/eng 런타임을 확인하세요."
        ) from exc

    warnings = list(ocr.warnings)
    if not ocr.text.strip():
        raise QuoteExtractionError(  # noqa: F405
            "견적 이미지에 로컬 OCR을 실행했지만 인식 가능한 텍스트를 찾지 못했습니다. 더 선명한 원본 이미지, PDF 또는 Excel을 사용하세요."
        )

    items: list[QuoteItem] = []  # noqa: F405
    if ocr.table_rows:
        table_items, _ = _core._extract_sheet_rows("이미지 OCR 단어좌표", ocr.table_rows)
        items.extend(table_items)
    if not items:
        items.extend(_core._extract_pdf_line_candidates(ocr.text, 1))
    if not items:
        text_items, _ = _core._extract_sheet_rows(
            "이미지 OCR 텍스트",
            _core._pdf_text_rows(ocr.text),
        )
        items.extend(text_items)

    items = [item for item in items if _core._has_meaningful_identity(item)]
    items = _core._dedupe_quote_items(items)
    items = _core._apply_pdf_context(items, _extract_pdf_context([ocr.text]))

    if not items:
        recovered = recover_sparse_ruled_table_image_quote(path)
        if recovered is None:
            recovered = recover_single_item_from_text(ocr.text, ocr.text, page_number=1)
            if recovered is not None:
                recovered = replace(
                    recovered,
                    source_sheet="이미지 OCR 단일품목 fallback",
                )
        if recovered is not None:
            items = [recovered]
            warnings.append(_SINGLE_ITEM_FOOTER_WARNING)

    if items:
        warnings.append(_IMAGE_OCR_WARNING)
    else:
        warnings.append(
            "이미지 OCR로 텍스트는 인식했지만 의미 있는 품목/가격 행을 식별하지 못했습니다. "
            "세액·합계를 품목으로 임의 생성하지 않고 자동 추출을 보류했습니다."
        )
    return _core.QuoteExtractionResult(items=tuple(items), warnings=tuple(warnings))


def extract_image_quote(path: Path) -> QuoteExtractionResult:
    return _run_with_tracking(_extract_image_quote_core, path)


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
    if suffix in _IMAGE_SUFFIXES:
        return extract_image_quote(path)
    raise QuoteExtractionError(  # noqa: F405
        "지원하지 않는 파일 형식입니다. .xlsx/.xls/.pdf/.png/.jpg/.jpeg만 업로드하세요."
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
