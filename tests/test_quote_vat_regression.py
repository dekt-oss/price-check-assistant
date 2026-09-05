from pathlib import Path

from openpyxl import Workbook

from purchase_price.services.quote_extraction import (
    _extract_pdf_context,
    extract_quote_file,
)


def test_pdf_context_recognizes_korean_tax_header_with_parenthesized_included() -> None:
    context = _extract_pdf_context(["공급가액 60,000,000\n세액\n(포함)\n합계 66,000,000"])

    assert context.vat_status == "포함"


def test_pdf_context_recognizes_vat_include_and_included_variants() -> None:
    for text in ("(V.A.T) Include", "VAT Included", "V.A.T: Include"):
        assert _extract_pdf_context([text]).vat_status == "포함"


def test_excel_tax_amount_header_is_vat_and_tax_summary_is_not_an_item(tmp_path: Path) -> None:
    path = tmp_path / "synthetic_quote.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "모델명", "수량", "단가", "금액", "세액"])
    sheet.append(["가스 마취기", "FLOW-X", 1, 60000000, 66000000, "(포함)"])
    sheet.append(["세액", "", "", "", 6000000, ""])
    workbook.save(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    assert result.items[0].model_name == "FLOW-X"
    assert result.items[0].total_amount == 66000000
    assert result.items[0].vat_status == "포함"
