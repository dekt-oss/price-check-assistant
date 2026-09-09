from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw

from purchase_price.services import quote_extraction
from purchase_price.services.quote_extraction_core import QuoteExtractionResult, QuoteItem
from purchase_price.services.quote_ruled_table_ocr import (
    _remove_long_grid_lines,
    recover_sparse_single_item_from_text,
)


def test_recovers_sparse_ruled_table_shape_from_real_uat_ocr() -> None:
    sparse_text = """
    견적서
    Haemonet ics
    4년(종료월 말일)
    리스(익월결제)수용
    AUTOLOGOUS BLOOD
    Cel! Saver
    t
    1
    41,000,000 41,000,000
    부가세포함
    RECOVERY SYSTEM
    ELITE+
    Included with
    1.Operating manual
    1부
    """
    context_text = """
    제조/수입업체
    Haemonet ics
    PatWarranty71 2!
    4년(종료월말일)
    리스(익월결제)수용
    AUTOLOGOUS BLOOD
    Cell Saver
    RECOVERY SYSTEM
    ELITE+
    unit
    W41,000,000 | W41,000,000
    부가세포함
    """

    item = recover_sparse_single_item_from_text(
        sparse_text,
        context_text=context_text,
    )

    assert item is not None
    assert item.product_name == "AUTOLOGOUS BLOOD RECOVERY SYSTEM"
    assert item.manufacturer == "Haemonetics"
    assert item.specification == "Cel! Saver ELITE+"
    assert item.quantity == Decimal("1")
    assert item.unit == "unit"
    assert item.unit_price == Decimal("41000000")
    assert item.total_amount == Decimal("41000000")
    assert item.vat_status == "포함"
    assert item.warranty_condition == "4년"
    assert "리스" in item.other_conditions


def test_sparse_recovery_rejects_summary_only_repeated_amount() -> None:
    text = """
    견적서
    합계
    1
    41,000,000 41,000,000
    부가세포함
    """

    assert recover_sparse_single_item_from_text(text) is None


def test_sparse_recovery_rejects_multiple_priced_rows() -> None:
    text = """
    견적서
    AUTOLOGOUS BLOOD
    Cell Saver ELITE+
    1
    41,000,000 41,000,000
    SECOND PRODUCT
    Model-X
    1
    10,000,000 10,000,000
    """

    assert recover_sparse_single_item_from_text(text) is None


def test_grid_cleanup_removes_long_ruling_but_keeps_short_stroke() -> None:
    image = Image.new("L", (400, 220), 255)
    draw = ImageDraw.Draw(image)
    draw.line((10, 100, 390, 100), fill=0, width=2)
    draw.line((200, 10, 200, 210), fill=0, width=2)
    draw.line((30, 40, 50, 40), fill=0, width=2)

    cleaned = _remove_long_grid_lines(image)

    assert cleaned.getpixel((120, 100)) > 240
    assert cleaned.getpixel((200, 160)) > 240
    assert cleaned.getpixel((40, 40)) < 100


def test_quote_extraction_prefers_ruled_table_recovery(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"placeholder")
    recovered = QuoteItem(
        source_sheet="PDF 1페이지 OCR ruled-table fallback",
        source_row=9,
        product_name="AUTOLOGOUS BLOOD RECOVERY SYSTEM",
        manufacturer="Haemonetics",
        specification="Cell Saver ELITE+",
        quantity=Decimal("1"),
        unit="unit",
        unit_price=Decimal("41000000"),
        total_amount=Decimal("41000000"),
        vat_status="포함",
    )

    monkeypatch.setattr(
        quote_extraction,
        "_original_extract_pdf_quote",
        lambda _: QuoteExtractionResult(
            items=(),
            warnings=("로컬 OCR로 텍스트는 인식했지만 의미 있는 품목/가격 행을 식별하지 못했습니다.",),
        ),
    )
    monkeypatch.setattr(
        quote_extraction,
        "recover_sparse_ruled_table_scanned_quote",
        lambda _: recovered,
    )

    def legacy_must_not_run(_: Path) -> QuoteItem | None:
        raise AssertionError("ruled-table recovery succeeded, legacy fallback must not run")

    monkeypatch.setattr(
        quote_extraction,
        "recover_single_item_scanned_quote",
        legacy_must_not_run,
    )

    result = quote_extraction.extract_pdf_quote(path)

    assert result.items == (recovered,)
    assert any("가격행/합계 근거" in warning for warning in result.warnings)
    assert not any("의미 있는 품목/가격 행을 식별하지 못했습니다" in warning for warning in result.warnings)
