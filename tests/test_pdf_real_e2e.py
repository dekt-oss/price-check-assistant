from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from purchase_price.services.quote_extraction import extract_quote_file

_HEADERS = (
    ("Description", 40),
    ("Specification", 200),
    ("Quantity", 310),
    ("Unit Price", 370),
    ("Amount", 470),
)


def _draw_text_row(canvas: Canvas, y: float, values: tuple[str, ...]) -> None:
    positions = tuple(x for _, x in _HEADERS)
    canvas.setFont("Helvetica", 9)
    for x, value in zip(positions, values, strict=True):
        canvas.drawString(x, y, value)


def _draw_header(canvas: Canvas, y: float) -> None:
    canvas.setFont("Helvetica-Bold", 9)
    for label, x in _HEADERS:
        canvas.drawString(x, y, label)


def _build_line_less_pdf(path: Path) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    _draw_header(canvas, 740)
    _draw_text_row(canvas, 718, ("Infusion Pump", "IP-200", "2", "1,250,000", "2,500,000"))
    canvas.save()


def _build_ruled_pdf(path: Path, *, multipage: bool = False) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    x_points = (35, 190, 300, 360, 460, 555)
    y_points = (760, 735, 710)
    for x in x_points:
        canvas.line(x, y_points[-1], x, y_points[0])
    for y in y_points:
        canvas.line(x_points[0], y, x_points[-1], y)

    canvas.setFont("Helvetica-Bold", 8)
    for index, (label, _) in enumerate(_HEADERS):
        canvas.drawString(x_points[index] + 5, 744, label)

    canvas.setFont("Helvetica", 8)
    row = (
        "Anesthesia Machine" if multipage else "Ventilator",
        "Flow-C" if multipage else "SOPHIE",
        "1",
        "66,000,000" if multipage else "34,500,000",
        "66,000,000" if multipage else "34,500,000",
    )
    for index, value in enumerate(row):
        canvas.drawString(x_points[index] + 5, 719, value)

    if multipage:
        canvas.showPage()
        canvas.setFont("Helvetica", 10)
        canvas.drawString(40, 740, "Manufacturer : Maquet")
        canvas.drawString(40, 720, "Model-FLOW-C           1 set")
        canvas.drawString(40, 700, "warranty 3 years")
        canvas.showPage()
        canvas.drawString(40, 740, "Total (V.A.T) Included 66,000,000")
        canvas.drawString(
            40,
            720,
            "The installation and operation should be provided by Contractor.",
        )
        canvas.drawString(40, 700, "Warranty: Contractor should guarantee three years.")

    canvas.save()


def _build_totals_only_pdf(path: Path) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(40, 740, "Quotation Summary")
    canvas.drawString(40, 720, "Subtotal 1,000,000")
    canvas.drawString(40, 700, "VAT 100,000")
    canvas.drawString(40, 680, "Total 1,100,000")
    canvas.save()


def test_real_line_less_pdf_uses_word_geometry(tmp_path: Path) -> None:
    path = tmp_path / "line-less.pdf"
    _build_line_less_pdf(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Infusion Pump"
    assert item.specification == "IP-200"
    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("1250000")
    assert item.total_amount == Decimal("2500000")
    assert "단어좌표" in item.source_sheet
    assert any("단어 X/Y 좌표" in warning for warning in result.warnings)


def test_real_ruled_pdf_prefers_line_table_extraction(tmp_path: Path) -> None:
    path = tmp_path / "ruled.pdf"
    _build_ruled_pdf(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Ventilator"
    assert item.specification == "SOPHIE"
    assert item.quantity == Decimal("1")
    assert item.unit_price == Decimal("34500000")
    assert item.total_amount == Decimal("34500000")
    assert "표1" in item.source_sheet
    assert "단어좌표" not in item.source_sheet


def test_real_multipage_pdf_enriches_document_context(tmp_path: Path) -> None:
    path = tmp_path / "multipage.pdf"
    _build_ruled_pdf(path, multipage=True)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Anesthesia Machine"
    assert item.specification == "Flow-C"
    assert item.manufacturer == "Maquet"
    assert item.model_name == "FLOW-C"
    assert item.quantity == Decimal("1")
    assert item.unit == "set"
    assert item.unit_price == Decimal("66000000")
    assert item.total_amount == Decimal("66000000")
    assert item.vat_status == "포함"
    assert item.installation_condition == "Contractor 설치·운영 제공"
    assert item.warranty_condition == "3년"


def test_real_totals_only_pdf_does_not_invent_item(tmp_path: Path) -> None:
    path = tmp_path / "totals-only.pdf"
    _build_totals_only_pdf(path)

    result = extract_quote_file(path)

    assert result.items == ()
    assert any("품목/가격 행을 식별하지 못했습니다" in warning for warning in result.warnings)
