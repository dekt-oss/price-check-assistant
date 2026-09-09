from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.services import quote_extraction
from purchase_price.services.image_ocr import ImageOcrResult
from purchase_price.services.quote_extraction_diagnostics import (
    QuoteExtractionStrategy,
    diagnose_quote_extraction,
)


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg"])
def test_image_quote_uses_same_table_contract_as_pdf_ocr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suffix: str,
) -> None:
    path = tmp_path / f"quote{suffix}"
    path.write_bytes(b"image-placeholder")
    monkeypatch.setattr(
        quote_extraction,
        "run_local_image_ocr",
        lambda *_args, **_kwargs: ImageOcrResult(
            text="VAT Included\nManufacturer: ACME Medical",
            table_rows=(
                ("Description", "Model", "Qty", "Unit", "Unit Price", "Amount"),
                ("Infusion Pump", "IP-200", "1", "set", "1250000", "1250000"),
            ),
            warnings=(),
        ),
    )

    result = quote_extraction.extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Infusion Pump"
    assert item.model_name == "IP-200"
    assert item.quantity == Decimal("1")
    assert item.unit == "set"
    assert item.unit_price == Decimal("1250000")
    assert item.total_amount == Decimal("1250000")
    assert item.vat_status == "포함"
    diagnostics = diagnose_quote_extraction(path, result)
    assert diagnostics.strategies == (QuoteExtractionStrategy.IMAGE_LOCAL_OCR,)


def test_image_quote_uses_ruled_table_fallback_when_normal_ocr_has_no_item(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "quote.png"
    path.write_bytes(b"image-placeholder")
    monkeypatch.setattr(
        quote_extraction,
        "run_local_image_ocr",
        lambda *_args, **_kwargs: ImageOcrResult(
            text="QUOTATION\nAUTOLOGOUS BLOOD\nRECOVERY SYSTEM\n41,000,000",
            table_rows=(),
            warnings=(),
        ),
    )
    recovered = quote_extraction.QuoteItem(
        source_sheet="이미지 OCR ruled-table fallback",
        source_row=8,
        product_name="AUTOLOGOUS BLOOD RECOVERY SYSTEM",
        manufacturer="Haemonetics",
        specification="Cel! Saver ELITE+",
        quantity=Decimal("1"),
        unit="unit",
        unit_price=Decimal("41000000"),
        total_amount=Decimal("41000000"),
        vat_status="포함",
    )
    monkeypatch.setattr(
        quote_extraction,
        "recover_sparse_ruled_table_image_quote",
        lambda _path: recovered,
    )

    result = quote_extraction.extract_quote_file(path)

    assert result.items == (recovered,)
    assert any("로컬 Tesseract" in warning for warning in result.warnings)


def test_unsupported_gif_still_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "quote.gif"
    path.write_bytes(b"gif-placeholder")

    with pytest.raises(quote_extraction.QuoteExtractionError, match="png/.jpg/.jpeg"):
        quote_extraction.extract_quote_file(path)
