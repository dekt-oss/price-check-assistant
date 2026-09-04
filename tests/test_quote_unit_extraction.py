from pathlib import Path

from openpyxl import Workbook

from purchase_price.services.quote_extraction import extract_quote_file


def test_quote_unit_header_is_extracted(tmp_path: Path) -> None:
    path = tmp_path / "quote.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "모델명", "수량", "단위", "단가"])
    sheet.append(["초음파진단기", "US-100", 1, "대", 12000000])
    workbook.save(path)

    item = extract_quote_file(path).items[0]

    assert item.quantity == 1
    assert item.unit == "대"
