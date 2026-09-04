from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_quote_file,
    parse_quote_decimal,
    quote_item_query,
)


def _write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "견적"
    sheet.append(["병원 구매 견적서"])
    sheet.append(["품명", "제조사", "모델명", "규격", "수량", "단가", "금액"])
    sheet.append(
        [
            "노트북",
            "삼성전자",
            "NT960XJG-K72AG",
            "16GB / 1TB",
            2,
            "2,500,000원",
            "5,000,000",
        ]
    )
    sheet.append(["합계", "", "", "", "", "", "5,000,000"])

    ignored = workbook.create_sheet("안내")
    ignored.append(["납기 및 보증 조건"])
    workbook.save(path)


def test_extract_xlsx_quote_finds_header_and_skips_summary(tmp_path: Path) -> None:
    path = tmp_path / "quote.xlsx"
    _write_workbook(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_sheet == "견적"
    assert item.source_row == 3
    assert item.product_name == "노트북"
    assert item.manufacturer == "삼성전자"
    assert item.model_name == "NT960XJG-K72AG"
    assert item.specification == "16GB / 1TB"
    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("2500000")
    assert item.total_amount == Decimal("5000000")
    assert any("안내" in warning for warning in result.warnings)


def test_quote_item_converts_to_existing_product_query(tmp_path: Path) -> None:
    path = tmp_path / "quote.xlsx"
    _write_workbook(path)
    item = extract_quote_file(path).items[0]

    query = quote_item_query(item)

    assert query.product_name == "노트북"
    assert query.manufacturer == "삼성전자"
    assert query.model_name == "NT960XJG-K72AG"
    assert query.specification == "16GB / 1TB"


def test_rows_without_a_price_are_not_auto_extracted(tmp_path: Path) -> None:
    path = tmp_path / "quote.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "모델명", "단가"])
    sheet.append(["노트북", "NT960XJG-K72AG", None])
    workbook.save(path)

    result = extract_quote_file(path)

    assert result.items == ()
    assert any("자동 추출된 견적 품목이 없습니다" in warning for warning in result.warnings)


def test_parse_quote_decimal_handles_common_krw_display() -> None:
    assert parse_quote_decimal("₩ 1,234,500원") == Decimal("1234500")
    assert parse_quote_decimal(1200) == Decimal("1200")
    assert parse_quote_decimal("문의") is None


def test_unsupported_file_type_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    path.write_bytes(b"%PDF-1.4")

    try:
        extract_quote_file(path)
    except QuoteExtractionError as exc:
        assert ".xlsx" in str(exc)
    else:
        raise AssertionError("unsupported file type must fail closed")
