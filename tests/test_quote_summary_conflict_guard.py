from pathlib import Path

from openpyxl import Workbook

from purchase_price.services.quote_extraction import _extract_pdf_context, extract_quote_file


def test_excel_summary_variants_do_not_become_quote_items(tmp_path: Path) -> None:
    path = tmp_path / "summary_variants.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "모델명", "수량", "단가", "금액"])
    sheet.append(["가스 마취기", "FLOW-X", 1, 60000000, 60000000])
    sheet.append(["공급가액", "", "", "", 60000000])
    sheet.append(["부가가치세 (VAT)", "", "", "", 6000000])
    sheet.append(["견적금액 합계", "", "", "", 66000000])
    workbook.save(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    assert result.items[0].model_name == "FLOW-X"


def test_summary_word_inside_real_product_name_is_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "real_product_with_summary_word.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "모델명", "수량", "단가", "금액"])
    sheet.append(["VAT 분석기", "VAT-200", 1, 1200000, 1200000])
    workbook.save(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    assert result.items[0].model_name == "VAT-200"


def test_conflicting_document_level_vat_evidence_stays_unknown() -> None:
    context = _extract_pdf_context(
        [
            "견적 조건: VAT 별도",
            "참고 문구: V.A.T Include",
        ]
    )

    assert context.vat_status == ""


def test_repeated_consistent_document_level_vat_evidence_is_accepted() -> None:
    context = _extract_pdf_context(
        [
            "세액\n(포함)",
            "V.A.T Included",
        ]
    )

    assert context.vat_status == "포함"
