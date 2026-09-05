from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from purchase_price.services.quote_extraction import extract_quote_file


def _build_text_quote_pdf(path: Path) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    canvas.setFont("Helvetica-Bold", 14)
    headers = (
        ("Description", 30),
        ("Specification", 220),
        ("Quantity", 355),
        ("Unit Price", 420),
        ("Amount", 520),
    )
    for label, x in headers:
        canvas.drawString(x, 700, label)

    canvas.setFont("Helvetica", 14)
    row = (
        ("Infusion Pump", 30),
        ("IP-200", 220),
        ("2", 365),
        ("1250000", 420),
        ("2500000", 520),
    )
    for value, x in row:
        canvas.drawString(x, 660, value)
    canvas.save()


def _rasterize_to_image_only_pdf(source: Path, output: Path) -> None:
    document = pdfium.PdfDocument(str(source))
    page = None
    bitmap = None
    try:
        page = document[0]
        bitmap = page.render(scale=220 / 72)
        image = bitmap.to_pil().convert("RGB")
        image.save(output, format="PDF", resolution=220.0)
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        document.close()


def test_real_image_only_pdf_runs_tesseract_and_extracts_quote(tmp_path: Path) -> None:
    text_pdf = tmp_path / "source-text.pdf"
    scan_pdf = tmp_path / "scan-image-only.pdf"
    _build_text_quote_pdf(text_pdf)
    _rasterize_to_image_only_pdf(text_pdf, scan_pdf)

    reader = PdfReader(str(scan_pdf))
    assert all(not (page.extract_text() or "").strip() for page in reader.pages)

    result = extract_quote_file(scan_pdf)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Infusion Pump"
    assert item.specification == "IP-200"
    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("1250000")
    assert item.total_amount == Decimal("2500000")
    assert "OCR" in item.source_sheet
    assert any("Tesseract" in warning for warning in result.warnings)
