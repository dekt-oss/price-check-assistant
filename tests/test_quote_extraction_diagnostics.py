from pathlib import Path

from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    QuoteExtractionResult,
    QuoteItem,
)
from purchase_price.services.quote_extraction_diagnostics import (
    QuoteExtractionStrategy,
    diagnose_quote_extraction,
    diagnose_quote_extraction_error,
)


def test_pdf_diagnostics_report_ruled_and_word_geometry_without_values() -> None:
    result = QuoteExtractionResult(
        items=(
            QuoteItem(
                source_sheet="PDF 1페이지 표1",
                source_row=2,
                product_name="Sensitive Product",
                unit_price=123456,
            ),
            QuoteItem(
                source_sheet="PDF 2페이지 단어좌표",
                source_row=3,
                product_name="Another Product",
                unit_price=654321,
            ),
        ),
        warnings=("검토 필요",),
    )

    diagnostics = diagnose_quote_extraction(Path("quote.pdf"), result)

    assert diagnostics.strategies == (
        QuoteExtractionStrategy.PDF_RULED_TABLE,
        QuoteExtractionStrategy.PDF_WORD_GEOMETRY,
    )
    public = diagnostics.to_public_dict()
    assert public["extracted_item_count"] == 2
    assert "Sensitive Product" not in str(public)
    assert "123456" not in str(public)


def test_empty_text_pdf_is_reported_as_unresolved_text() -> None:
    result = QuoteExtractionResult(items=(), warnings=("품목 구조 미식별",))

    diagnostics = diagnose_quote_extraction(Path("quote.pdf"), result)

    assert diagnostics.strategies == (QuoteExtractionStrategy.PDF_TEXT_UNRESOLVED,)
    assert diagnostics.manual_review_required is True


def test_scan_pdf_error_is_classified_as_ocr_target() -> None:
    error = QuoteExtractionError(
        "PDF에 추출 가능한 텍스트 레이어가 없습니다. 스캔 이미지형 PDF로 보입니다."
    )

    diagnostics = diagnose_quote_extraction_error(Path("scan.pdf"), error)

    assert diagnostics.strategies == (QuoteExtractionStrategy.PDF_SCAN_NO_TEXT,)
    assert diagnostics.extracted_item_count == 0


def test_excel_strategy_uses_file_suffix() -> None:
    result = QuoteExtractionResult(items=(), warnings=())

    xlsx = diagnose_quote_extraction(Path("quote.xlsx"), result)
    xls = diagnose_quote_extraction(Path("quote.xls"), result)

    assert xlsx.strategies == (QuoteExtractionStrategy.XLSX_TABLE,)
    assert xls.strategies == (QuoteExtractionStrategy.XLS_TABLE,)
