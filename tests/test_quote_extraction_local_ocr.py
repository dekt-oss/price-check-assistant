from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.services import quote_extraction
from purchase_price.services.pdf_ocr import PdfOcrPage, PdfOcrResult, PdfOcrUnavailableError
from purchase_price.services.quote_extraction import QuoteExtractionError, QuoteItem
from purchase_price.services.quote_extraction_diagnostics import (
    QuoteExtractionStrategy,
    diagnose_quote_extraction,
    diagnose_quote_extraction_error,
)


def _no_text_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        quote_extraction,
        "_extract_with_pdfplumber",
        lambda path: ([], [""], [], False),
    )
    monkeypatch.setattr(
        quote_extraction,
        "_extract_pypdf_text",
        lambda path: ([""], [], False),
    )


def test_scanned_pdf_uses_local_ocr_and_enriches_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_text_pdf(monkeypatch)
    ocr_result = PdfOcrResult(
        pages=(
            PdfOcrPage(
                page_number=1,
                text="가스 마취기 Anesthesia Machine Flow-C 1 66,000,000 66,000,000",
                table_rows=(
                    ("품명", "규격", "수량", "단가", "금액"),
                    ("가스 마취기(Anesthesia Machine)", "Flow-C", "1", "66,000,000", "66,000,000"),
                ),
            ),
            PdfOcrPage(
                page_number=2,
                text=(
                    "Manufacturer: Maquet\n"
                    "Model-FLOW-C\n"
                    "1 set\n"
                    "warranty 3 years\n"
                    "The installation and operation should be provided by Contractor.\n"
                    "(V.A.T) Included"
                ),
                table_rows=(),
            ),
        ),
        warnings=(),
    )
    monkeypatch.setattr(quote_extraction, "run_local_pdf_ocr", lambda path, resolver: ocr_result)

    result = quote_extraction.extract_pdf_quote(Path("scan.pdf"))

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "가스 마취기(Anesthesia Machine)"
    assert item.manufacturer == "Maquet"
    assert item.model_name == "FLOW-C"
    assert item.specification == "Flow-C"
    assert item.quantity == Decimal("1")
    assert item.unit == "set"
    assert item.unit_price == Decimal("66000000")
    assert item.total_amount == Decimal("66000000")
    assert item.vat_status == "포함"
    assert item.warranty_condition == "3년"
    assert item.installation_condition == "Contractor 설치·운영 제공"
    assert "로컬 Tesseract" in " ".join(result.warnings)

    diagnostics = diagnose_quote_extraction(Path("scan.pdf"), result)
    assert diagnostics.strategies == (QuoteExtractionStrategy.PDF_LOCAL_OCR,)


def test_text_pdf_never_calls_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    structured = QuoteItem(
        source_sheet="PDF 1페이지 표1",
        source_row=2,
        product_name="Infusion Pump",
        specification="IP-200",
        quantity=Decimal("1"),
        unit_price=Decimal("1000000"),
        total_amount=Decimal("1000000"),
    )
    monkeypatch.setattr(
        quote_extraction,
        "_extract_with_pdfplumber",
        lambda path: ([structured], ["Infusion Pump IP-200"], [], True),
    )
    monkeypatch.setattr(
        quote_extraction,
        "_extract_pypdf_text",
        lambda path: (["Infusion Pump IP-200"], [], True),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("텍스트 PDF에서 OCR이 호출되면 안 됩니다.")

    monkeypatch.setattr(quote_extraction, "run_local_pdf_ocr", fail_if_called)

    result = quote_extraction.extract_pdf_quote(Path("text.pdf"))
    assert len(result.items) == 1
    assert result.items[0].specification == "IP-200"


def test_ocr_dependency_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_text_pdf(monkeypatch)

    def unavailable(*args, **kwargs):
        raise PdfOcrUnavailableError("missing tesseract")

    monkeypatch.setattr(quote_extraction, "run_local_pdf_ocr", unavailable)

    with pytest.raises(QuoteExtractionError, match="로컬 OCR을 실행할 수 없습니다") as captured:
        quote_extraction.extract_pdf_quote(Path("scan.pdf"))

    diagnostics = diagnose_quote_extraction_error(Path("scan.pdf"), captured.value)
    assert diagnostics.strategies == (QuoteExtractionStrategy.PDF_OCR_UNAVAILABLE,)


def test_ocr_text_without_item_does_not_invent_price_row(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_text_pdf(monkeypatch)
    monkeypatch.setattr(
        quote_extraction,
        "run_local_pdf_ocr",
        lambda path, resolver: PdfOcrResult(
            pages=(
                PdfOcrPage(
                    page_number=1,
                    text="공급가 총액 60,000,000\n세액 6,000,000\n합계 66,000,000",
                    table_rows=(),
                ),
            ),
            warnings=(),
        ),
    )

    result = quote_extraction.extract_pdf_quote(Path("scan.pdf"))
    assert result.items == ()
    assert "자동 추출을 보류" in " ".join(result.warnings)
