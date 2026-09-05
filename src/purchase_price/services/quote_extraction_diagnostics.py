from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from purchase_price.services.quote_extraction import QuoteExtractionError, QuoteExtractionResult


class QuoteExtractionStrategy(StrEnum):
    XLSX_TABLE = "xlsx_table"
    XLS_TABLE = "xls_table"
    PDF_RULED_TABLE = "pdf_ruled_table"
    PDF_WORD_GEOMETRY = "pdf_word_geometry"
    PDF_TEXT_FALLBACK = "pdf_text_fallback"
    PDF_LOCAL_OCR = "pdf_local_ocr"
    PDF_TEXT_UNRESOLVED = "pdf_text_unresolved"
    PDF_SCAN_NO_TEXT = "pdf_scan_no_text"
    PDF_OCR_UNAVAILABLE = "pdf_ocr_unavailable"
    UNKNOWN = "unknown"


_STRATEGY_LABELS = {
    QuoteExtractionStrategy.XLSX_TABLE: "Excel(.xlsx) 헤더/행 추출",
    QuoteExtractionStrategy.XLS_TABLE: "Excel(.xls) 헤더/행 추출",
    QuoteExtractionStrategy.PDF_RULED_TABLE: "PDF 표 선/셀 구조",
    QuoteExtractionStrategy.PDF_WORD_GEOMETRY: "PDF 단어 X/Y 좌표 재구성",
    QuoteExtractionStrategy.PDF_TEXT_FALLBACK: "PDF 텍스트 fallback",
    QuoteExtractionStrategy.PDF_LOCAL_OCR: "PDF 로컬 OCR(Tesseract kor+eng)",
    QuoteExtractionStrategy.PDF_TEXT_UNRESOLVED: "PDF 텍스트는 있으나 품목 구조 미식별",
    QuoteExtractionStrategy.PDF_SCAN_NO_TEXT: "PDF 텍스트 레이어 없음(OCR 대상)",
    QuoteExtractionStrategy.PDF_OCR_UNAVAILABLE: "PDF OCR 실행 불가",
    QuoteExtractionStrategy.UNKNOWN: "추출 경로 미확인",
}


@dataclass(frozen=True)
class QuoteExtractionDiagnostics:
    file_kind: str
    strategies: tuple[QuoteExtractionStrategy, ...]
    extracted_item_count: int
    warning_count: int
    manual_review_required: bool = True

    @property
    def strategy_label(self) -> str:
        return " → ".join(_STRATEGY_LABELS[strategy] for strategy in self.strategies)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "file_kind": self.file_kind,
            "strategies": [strategy.value for strategy in self.strategies],
            "strategy_label": self.strategy_label,
            "extracted_item_count": self.extracted_item_count,
            "warning_count": self.warning_count,
            "manual_review_required": self.manual_review_required,
        }


def _pdf_strategies(result: QuoteExtractionResult) -> tuple[QuoteExtractionStrategy, ...]:
    strategies: list[QuoteExtractionStrategy] = []
    for item in result.items:
        source = item.source_sheet
        if "OCR" in source:
            strategy = QuoteExtractionStrategy.PDF_LOCAL_OCR
        elif "단어좌표" in source:
            strategy = QuoteExtractionStrategy.PDF_WORD_GEOMETRY
        elif "표" in source:
            strategy = QuoteExtractionStrategy.PDF_RULED_TABLE
        else:
            strategy = QuoteExtractionStrategy.PDF_TEXT_FALLBACK
        if strategy not in strategies:
            strategies.append(strategy)

    if not strategies:
        if any("로컬 OCR" in warning or "OCR" in warning for warning in result.warnings):
            strategies.append(QuoteExtractionStrategy.PDF_LOCAL_OCR)
        else:
            strategies.append(QuoteExtractionStrategy.PDF_TEXT_UNRESOLVED)
    return tuple(strategies)


def diagnose_quote_extraction(
    path: Path,
    result: QuoteExtractionResult,
) -> QuoteExtractionDiagnostics:
    suffix = path.suffix.casefold()
    if suffix == ".xlsx":
        strategies = (QuoteExtractionStrategy.XLSX_TABLE,)
    elif suffix == ".xls":
        strategies = (QuoteExtractionStrategy.XLS_TABLE,)
    elif suffix == ".pdf":
        strategies = _pdf_strategies(result)
    else:
        strategies = (QuoteExtractionStrategy.UNKNOWN,)

    return QuoteExtractionDiagnostics(
        file_kind=suffix.lstrip(".") or "unknown",
        strategies=strategies,
        extracted_item_count=len(result.items),
        warning_count=len(result.warnings),
    )


def diagnose_quote_extraction_error(
    path: Path,
    error: QuoteExtractionError,
) -> QuoteExtractionDiagnostics:
    suffix = path.suffix.casefold()
    message = str(error)
    if suffix == ".pdf" and (
        "OCR을 실행할 수 없습니다" in message
        or "OCR Python 모듈" in message
        or "tesseract-ocr" in message
    ):
        strategies = (QuoteExtractionStrategy.PDF_OCR_UNAVAILABLE,)
    elif suffix == ".pdf" and "텍스트 레이어가 없습니다" in message:
        strategies = (QuoteExtractionStrategy.PDF_SCAN_NO_TEXT,)
    else:
        strategies = (QuoteExtractionStrategy.UNKNOWN,)
    return QuoteExtractionDiagnostics(
        file_kind=suffix.lstrip(".") or "unknown",
        strategies=strategies,
        extracted_item_count=0,
        warning_count=1,
    )
