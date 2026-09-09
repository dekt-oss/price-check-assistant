from decimal import Decimal
from pathlib import Path

from purchase_price.services import quote_extraction
from purchase_price.services.quote_extraction_core import QuoteExtractionResult, QuoteItem
from purchase_price.services.quote_single_item_ocr_fallback import recover_single_item_from_text


def test_recovers_single_item_when_product_and_footer_price_are_separated() -> None:
    full_text = """
    병원 견적서
    품명                 수량        금액        비고
    재활로봇-X
    1 구성
    1. 본체/구동부/제어부                 1 set
    2 remark
    1. 무상 보증 기간
    - 납품 후 3년
    4. 장비 도입관련 공사여부 : 해당없음
    6. 대금지불조건 : 리스결제
    """
    footer_text = """
    TOTAL PRICE With VAT
    개별단가
    140,000,000
    """

    item = recover_single_item_from_text(full_text, footer_text)

    assert item is not None
    assert item.product_name == "재활로봇-X"
    assert item.unit_price == Decimal("140000000")
    assert item.total_amount == Decimal("140000000")
    assert item.vat_status == "포함"
    assert item.warranty_condition == "3년"
    assert item.installation_condition == "해당없음"
    assert item.other_conditions == "결제조건: 리스결제"


def test_recovers_deidentified_ruled_table_scan_split_by_psm4() -> None:
    full_text = """
    견적서
    제조/수입업체 SAMPLE MAKER          무상 Warranty 기간 4년(종료월말일)
    결제조건         리스(익월결제)수용
    아래와 같이 견적합니다.

    AUTOLOGOUS BLOOD
    RECOVERY SYSTEM
    Included with

    Cell Saver | unit | 1 | W41,000,000 | W41,000,000 | 부가세포함
    ELITE+ |

    1.Operating manual
    2.Service manual
    합계 일금 사천일백만원정 (W 41,000,000)
    """

    item = recover_single_item_from_text(full_text, "")

    assert item is not None
    assert item.product_name == "AUTOLOGOUS BLOOD RECOVERY SYSTEM"
    assert item.specification == "Cell Saver ELITE+"
    assert item.quantity == Decimal("1")
    assert item.unit == "unit"
    assert item.unit_price == Decimal("41000000")
    assert item.total_amount == Decimal("41000000")
    assert item.vat_status == "포함"
    assert item.warranty_condition == "4년"
    assert item.other_conditions == "결제조건: 리스(익월결제)수용"


def test_does_not_turn_generic_summary_into_a_product() -> None:
    full_text = """
    견적서
    품명                 수량        금액        비고
    합계
    """
    footer_text = "TOTAL PRICE With VAT 140,000,000"

    assert recover_single_item_from_text(full_text, footer_text) is None


def test_does_not_recover_repeated_amount_summary_as_item() -> None:
    full_text = """
    견적서
    합계 | 1 | W41,000,000 | W41,000,000
    """

    assert recover_single_item_from_text(full_text, "") is None


def test_does_not_recover_when_multiple_product_candidates_exist() -> None:
    full_text = """
    견적서
    품명                 수량        금액        비고
    재활로봇-X
    재활로봇-Y
    1 구성
    """
    footer_text = "TOTAL PRICE With VAT 140,000,000"

    assert recover_single_item_from_text(full_text, footer_text) is None


def test_does_not_recover_when_multiple_priced_rows_exist() -> None:
    full_text = """
    견적서
    PRODUCT FAMILY
    Included with
    Model-A | unit | 1 | W10,000,000 | W10,000,000
    Model-B | unit | 1 | W20,000,000 | W20,000,000
    """

    assert recover_single_item_from_text(full_text, "") is None


def test_quote_extraction_uses_footer_fallback_only_after_zero_items(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"placeholder")
    recovered = QuoteItem(
        source_sheet="PDF 1페이지 OCR 단일품목 fallback",
        source_row=4,
        product_name="재활로봇-X",
        unit_price=Decimal("140000000"),
        total_amount=Decimal("140000000"),
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
        "recover_single_item_scanned_quote",
        lambda _: recovered,
    )

    result = quote_extraction.extract_pdf_quote(path)

    assert result.items == (recovered,)
    assert any("TOTAL PRICE/개별단가" in warning for warning in result.warnings)
    assert not any("의미 있는 품목/가격 행을 식별하지 못했습니다" in warning for warning in result.warnings)
