import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import (
    G2BShoppingCollector,
    G2BShoppingOperation,
    build_g2b_source_record_id,
    parse_official_report_record,
    unwrap_g2b_page,
)
from purchase_price.domain import EvidenceType, MatchGrade

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "g2b_shopping"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_unwrap_common_data_go_kr_envelope() -> None:
    page = unwrap_g2b_page(_fixture("shopping_contract_official_labels.json"))

    assert len(page.items) == 1
    assert page.total_count == 1
    assert page.page_no == 1
    assert page.num_of_rows == 10


def test_contract_unit_price_is_classified_as_shopping_contract_evidence() -> None:
    page = unwrap_g2b_page(_fixture("shopping_contract_official_labels.json"))
    result = parse_official_report_record(
        page.items[0], operation=G2BShoppingOperation.SHOPPING_MALL_PRODUCTS
    )

    assert result is not None
    assert result.price == Decimal("36550000")
    assert result.evidence_type == EvidenceType.SHOPPING_CONTRACT_UNIT_PRICE
    assert result.source_record_id == "contract:CNTR-001|product:TEST-001"
    assert result.match_grade == MatchGrade.X


def test_delivery_unit_price_is_classified_as_delivery_evidence() -> None:
    page = unwrap_g2b_page(_fixture("delivery_official_labels.json"))
    result = parse_official_report_record(
        page.items[0], operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS
    )

    assert result is not None
    assert result.price == Decimal("5750000")
    assert result.quantity == Decimal("2")
    assert result.total_amount == Decimal("11500000")
    assert result.evidence_type == EvidenceType.DELIVERY_ORDER_UNIT_PRICE


def test_specific_item_unit_price_requires_contract_or_delivery_semantics() -> None:
    delivery_record = {
        "물품식별번호": "TEST-003",
        "품명": "테스트 특정품목",
        "단가": "128000",
        "계약납품구분": "납품",
    }
    contract_record = {
        "물품식별번호": "TEST-004",
        "품명": "테스트 특정품목",
        "단가": "130000",
        "계약납품구분": "계약",
    }

    delivery = parse_official_report_record(
        delivery_record, operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS
    )
    contract = parse_official_report_record(
        contract_record, operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS
    )

    assert delivery is not None
    assert delivery.price == Decimal("128000")
    assert delivery.evidence_type == EvidenceType.DELIVERY_ORDER_UNIT_PRICE
    assert contract is not None
    assert contract.price == Decimal("130000")
    assert contract.evidence_type == EvidenceType.CONTRACT_UNIT_PRICE


def test_live_specific_item_schema_is_parsed_without_guessing() -> None:
    page = unwrap_g2b_page(_fixture("specific_item_live_20260715.json"))
    result = parse_official_report_record(
        page.items[0], operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS
    )

    assert page.total_count == 427
    assert result is not None
    assert result.product_name == "제습기, 나우이엘, MA-045DT, 45L/d"
    assert result.price == Decimal("450000")
    assert result.quantity == Decimal("1")
    assert result.total_amount == Decimal("450000")
    assert result.unit == "대"
    assert result.transaction_date == date(2026, 7, 15)
    assert result.source_record_id == (
        "delivery:R26TB02131828|change:00|product:24138760|line:1"
    )
    assert result.evidence_type == EvidenceType.DELIVERY_ORDER_UNIT_PRICE
    assert result.match_grade == MatchGrade.X
    assert "공급업체=주식회사 나우이엘" in (result.conditions or "")
    assert "납품조건=현장설치도" in (result.conditions or "")


def test_same_delivery_request_has_distinct_item_level_source_ids() -> None:
    base = {
        "cntrctDlvrReqNo": "R26TB-SAME",
        "cntrctDlvrReqChgOrd": "00",
    }
    first = {
        **base,
        "prdctIdntNo": "PRODUCT-1",
        "prdctSno": "1",
    }
    second = {
        **base,
        "prdctIdntNo": "PRODUCT-2",
        "prdctSno": "2",
    }

    first_id = build_g2b_source_record_id(first)
    second_id = build_g2b_source_record_id(second)

    assert first_id == "delivery:R26TB-SAME|change:00|product:PRODUCT-1|line:1"
    assert second_id == "delivery:R26TB-SAME|change:00|product:PRODUCT-2|line:2"
    assert first_id != second_id


def test_specific_item_live_query_contract_uses_verified_parameters() -> None:
    class StubClient:
        def __init__(self) -> None:
            self.call = None

        def get_json(self, base_url, endpoint, **params):
            self.call = (base_url, endpoint, params)
            return _fixture("specific_item_live_20260715.json")

    stub = StubClient()
    collector = G2BShoppingCollector("unused", client=stub)
    page, _ = collector.fetch_specific_item_page(
        detail_product_name="제습기",
        begin_date=date(2026, 7, 14),
        end_date=date(2026, 8, 13),
        page_no=1,
        num_of_rows=100,
    )

    assert page.total_count == 427
    assert stub.call is not None
    _, endpoint, params = stub.call
    assert endpoint == "getSpcifyPrdlstPrcureInfoList"
    assert params == {
        "pageNo": 1,
        "numOfRows": 100,
        "inqryDiv": "1",
        "inqryBgnDate": "20260714",
        "inqryEndDate": "20260813",
        "inqryPrdctDiv": "2",
        "fnlCntrctDlvrReqChgOrdYn": "Y",
        "dtilPrdctClsfcNoNm": "제습기",
    }


def test_generic_amount_without_verified_unit_price_is_not_promoted() -> None:
    record = {
        "물품식별명": "테스트 품목",
        "금액": "100000000",
    }

    result = parse_official_report_record(
        record, operation=G2BShoppingOperation.SHOPPING_MALL_PRODUCTS
    )

    assert result is None


def test_specific_item_unit_price_without_contract_delivery_type_is_not_promoted() -> None:
    record = {
        "물품식별명": "테스트 품목",
        "단가": "128000",
    }

    result = parse_official_report_record(
        record, operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS
    )

    assert result is None


def test_api_error_header_fails_closed() -> None:
    payload = {
        "response": {
            "header": {"resultCode": "99", "resultMsg": "TEST ERROR"},
            "body": {},
        }
    }

    with pytest.raises(PublicDataClientError, match="resultCode=99"):
        unwrap_g2b_page(payload)
