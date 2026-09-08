from __future__ import annotations

from decimal import Decimal

from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_bid_items import parse_bid_purchase_item
from purchase_price.services.g2b_contract_research import parse_contract_research
from purchase_price.services.g2b_market_models import ResearchAmountType
from purchase_price.services.g2b_unmapped_discovery import _candidate_from_record


def test_bid_item_retains_identity_spec_and_raw_amount_without_price_promotion() -> None:
    item = parse_bid_purchase_item(
        {
            "bidNtceNo": "R26BK01234567",
            "bidNtceOrd": "00",
            "bidNtceDtlSeq": "2",
            "prdctClsfcNo": "42181703",
            "dtilPrdctClsfcNo": "4218170301",
            "prdctClsfcNoNm": "전신가스마취기",
            "prdctIdntNo": "24680001",
            "prdctSpcfctn": "FLOW-C, vaporizer 2EA, gas module 포함",
            "prdctQty": "4",
            "prdctUnit": "SET",
            "presmptUnitPrce": "55,000,000",
            "dlvryCndtnNm": "현장설치도",
            "purchsObjPrdctChgOrd": "1",
            "mnfcturNm": "Maquet",
            "modelNm": "FLOW-C",
        }
    )

    assert item.product_id == "24680001"
    assert item.detail_product_code == "4218170301"
    assert item.item_sequence == "2"
    assert item.original_specification == "FLOW-C, vaporizer 2EA, gas module 포함"
    assert item.original_amount_text == "55,000,000"
    assert item.delivery_condition == "현장설치도"
    assert item.record_change_order == "1"
    assert item.amount == Decimal("55000000")
    assert item.amount_type == ResearchAmountType.ESTIMATED_UNIT_PRICE
    assert not item.is_direct_unit_price
    assert not isinstance(item, CollectedPrice)


def test_bid_item_line_identity_does_not_collapse_same_notice_products() -> None:
    common = {
        "bidNtceNo": "R26BK01234567",
        "bidNtceOrd": "00",
        "prdctClsfcNoNm": "전신가스마취기",
        "presmptUnitPrce": "55,000,000",
    }
    first = parse_bid_purchase_item({**common, "bidNtceDtlSeq": "1", "prdctIdntNo": "24680001"})
    second = parse_bid_purchase_item({**common, "bidNtceDtlSeq": "2", "prdctIdntNo": "24680002"})

    assert first.source_record_id != second.source_record_id
    assert first.item_sequence == "1"
    assert second.item_sequence == "2"


def test_contract_retains_line_provenance_but_total_stays_contract_total() -> None:
    record = parse_contract_research(
        {
            "dcsnCntrctNo": "R26TA00001234-00",
            "ntceNo": "R26BK01234567",
            "cntrctDtlSeq": "3",
            "cntrctNm": "전신가스마취기 구매 계약",
            "prdctClsfcNoNm": "전신가스마취기",
            "dtilPrdctClsfcNo": "4218170301",
            "prdctIdntNo": "24680001",
            "krnPrdctNm": "Maquet FLOW-C / vaporizer 2EA",
            "prdctQty": "2",
            "prdctUnit": "SET",
            "totCntrctAmt": "132,000,000",
            "cntrctCorpNm": "공급사A",
            "dlvryCndtnNm": "현장설치도",
            "cntrctDtlChgOrd": "2",
        },
        search_term="전신가스마취기",
    )

    assert record.product_id == "24680001"
    assert record.detail_product_code == "4218170301"
    assert record.item_sequence == "3"
    assert record.original_specification == "Maquet FLOW-C / vaporizer 2EA"
    assert record.original_amount_text == "132,000,000"
    assert record.delivery_condition == "현장설치도"
    assert record.record_change_order == "2"
    assert record.search_term == "전신가스마취기"
    assert record.amount == Decimal("132000000")
    assert record.amount_type == ResearchAmountType.CONTRACT_TOTAL
    assert not record.is_direct_unit_price


def test_shopping_research_candidate_retains_delivery_line_provenance() -> None:
    candidate = _candidate_from_record(
        {
            "prdctIdntNo": "24888744",
            "prdctIdntNoNm": "레이저프린터, Fujifilm, ApeosPrint C5570 GK",
            "dtilPrdctClsfcNo": "4321210501",
            "dtilPrdctClsfcNoNm": "레이저프린터",
            "prdctUprc": "2981000",
            "prdctQty": "2",
            "prdctUnit": "대",
            "cntrctDlvrDivNm": "납품",
            "cntrctDlvrReqNo": "4526301234",
            "cntrctDlvrReqChgOrd": "1",
            "prdctSno": "2",
            "dminsttNm": "테스트기관",
            "corpNm": "테스트공급사",
            "dlvryCndtnNm": "납품장소도",
            "krnPrdctNm": "A3, 컬러 55ppm, 양면인쇄",
            "cntrctDlvrReqDate": "20260820",
        },
        ProductQuery(
            product_name="레이저프린터",
            manufacturer="Fujifilm",
            model_name="ApeosPrint C5570 GK",
        ),
        search_term="레이저프린터",
    )

    assert candidate is not None
    assert candidate.product_id == "24888744"
    assert candidate.classification_code == "4321210501"
    assert candidate.institution == "테스트기관"
    assert candidate.supplier == "테스트공급사"
    assert candidate.quantity == Decimal("2")
    assert candidate.unit == "대"
    assert candidate.item_sequence == "2"
    assert candidate.delivery_condition == "납품장소도"
    assert candidate.record_change_order == "1"
    assert candidate.original_specification == "A3, 컬러 55ppm, 양면인쇄"
    assert candidate.price == Decimal("2981000")
    assert candidate.relevance == "모델 표기 후보"


def test_eight_digit_classification_is_not_mislabeled_as_detail_product_code() -> None:
    item = parse_bid_purchase_item(
        {
            "bidNtceNo": "R26BK1",
            "bidNtceDtlSeq": "1",
            "prdctClsfcNo": "42181703",
            "prdctClsfcNoNm": "전신가스마취기",
        }
    )

    assert item.detail_product_code is None
