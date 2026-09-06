from pathlib import Path

from openpyxl import Workbook

from purchase_price.services import quote_extraction


def test_extraction_reports_summary_rows_it_actually_excluded(tmp_path: Path) -> None:
    path = tmp_path / "quote.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "모델명", "수량", "단가", "금액"])
    sheet.append(["컬러 레이저프린터", "C5570", 1, 3_500_000, 3_500_000])
    sheet.append(["공급가액", "", "", "", 3_500_000])
    sheet.append(["세액", "", "", "", 350_000])
    sheet.append(["합계", "", "", "", 3_850_000])
    workbook.save(path)

    result = quote_extraction.extract_quote_file(path)

    assert len(result.items) == 1
    assert len(result.excluded_rows) == 3
    assert any("공급가액" in row for row in result.excluded_rows)
    assert any("세액" in row for row in result.excluded_rows)
    assert any("합계" in row for row in result.excluded_rows)


def test_pdf_context_conflict_fails_closed_and_sets_warning_flag() -> None:
    token = quote_extraction._VAT_CONFLICT.set(False)
    try:
        context = quote_extraction._extract_pdf_context(["VAT 포함\nVAT 별도"])
        assert context.vat_status == ""
        assert quote_extraction._VAT_CONFLICT.get() is True
    finally:
        quote_extraction._VAT_CONFLICT.reset(token)
