from __future__ import annotations

from pathlib import Path

from purchase_price.services.pdf_ocr import PdfOcrUnavailableError, run_local_pdf_ocr
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    QuoteExtractionResult,
    _apply_pdf_context,
    _dedupe_quote_items,
    _extract_pdf_context,
    _extract_pdf_line_candidates,
    _extract_sheet_rows,
    _has_meaningful_identity,
    _pdf_text_rows,
    _resolve_header_field,
    extract_quote_file,
)

_SCAN_NO_TEXT_MARKER = "텍스트 레이어가 없습니다"


def _extract_ocr_quote(path: Path) -> QuoteExtractionResult:
    try:
        ocr = run_local_pdf_ocr(path, _resolve_header_field)
    except PdfOcrUnavailableError as exc:
        raise QuoteExtractionError(
            "스캔 PDF로 감지했지만 로컬 OCR을 실행할 수 없습니다. "
            "Streamlit의 pytesseract/pypdfium2 및 tesseract-ocr kor/eng 배포 의존성을 확인하세요."
        ) from exc

    warnings = list(ocr.warnings)
    texts = [page.text for page in ocr.pages if page.text.strip()]
    if not texts:
        raise QuoteExtractionError(
            "스캔 PDF에 로컬 OCR을 실행했지만 인식 가능한 텍스트를 찾지 못했습니다. "
            "해상도가 높은 원본 또는 원본 Excel을 사용하세요."
        )

    items = []
    for page in ocr.pages:
        page_items = []
        if page.table_rows:
            page_items, _ = _extract_sheet_rows(
                f"PDF {page.page_number}페이지 OCR 단어좌표",
                page.table_rows,
            )
        if not page_items and page.text:
            page_items.extend(_extract_pdf_line_candidates(page.text, page.page_number))
        if not page_items and page.text:
            text_items, _ = _extract_sheet_rows(
                f"PDF {page.page_number}페이지 OCR 텍스트",
                _pdf_text_rows(page.text),
            )
            page_items.extend(text_items)
        items.extend(item for item in page_items if _has_meaningful_identity(item))

    items = _dedupe_quote_items(items)
    items = _apply_pdf_context(items, _extract_pdf_context(texts))

    if items:
        warnings.append(
            "텍스트 레이어가 없는 스캔 PDF를 로컬 Tesseract(kor+eng) OCR로 처리했습니다. "
            "OCR 결과는 오인식 가능성이 높으므로 제품명·모델·규격·수량·가격·VAT·설치·보증을 "
            "반드시 원문 이미지와 대조하세요."
        )
    else:
        warnings.append(
            "로컬 OCR로 텍스트는 인식했지만 의미 있는 품목/가격 행을 식별하지 못했습니다. "
            "세액·합계를 품목으로 임의 생성하지 않고 자동 추출을 보류했습니다."
        )
    return QuoteExtractionResult(items=tuple(items), warnings=tuple(warnings))


def extract_quote_file_with_ocr(path: Path) -> QuoteExtractionResult:
    """Use the normal parser first and local OCR only for scan/no-text PDFs."""

    try:
        return extract_quote_file(path)
    except QuoteExtractionError as exc:
        if path.suffix.casefold() != ".pdf" or _SCAN_NO_TEXT_MARKER not in str(exc):
            raise
    return _extract_ocr_quote(path)
