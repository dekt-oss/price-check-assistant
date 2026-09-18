from __future__ import annotations

from datetime import date
from decimal import Decimal

from purchase_price.collectors.g2b_shopping import G2BShoppingPage
from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.scripts.probe_g2b_cross_evidence import build_report


def _price(record_id: str, amount: str = "100000") -> CollectedPrice:
    return CollectedPrice(
        manufacturer=None,
        product_name="레이저프린터",
        model_name=None,
        specification=None,
        price=Decimal(amount),
        evidence_type=EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        source_type=SourceType.PROCUREMENT,
        source_name="g2b",
        source_url=None,
        collected_at=date(2026, 9, 18),
        source_record_id=record_id,
        match_grade=MatchGrade.X,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )


class FakeShoppingCollector:
    def __init__(self, cases):
        self.cases = cases

    def fetch_specific_item_page(self, **kwargs):
        value = self.cases[kwargs["detail_product_name"]]
        if isinstance(value, Exception):
            raise value
        prices = value
        page = G2BShoppingPage(
            items=tuple({"row": index} for index, _ in enumerate(prices)),
            total_count=len(prices),
            page_no=1,
            num_of_rows=100,
        )
        return page, {"prices": prices}

    def parse_payload(self, payload, *, operation):
        return list(payload["prices"])


class FakeContractClient:
    def __init__(self, cases):
        self.cases = cases

    def fetch_product_search_page(self, **kwargs):
        value = self.cases[kwargs["product_name"]]
        if isinstance(value, Exception):
            raise value
        return G2BShoppingPage(
            items=tuple(value),
            total_count=len(value),
            page_no=1,
            num_of_rows=100,
        )


def _contract(contract_no: str) -> dict[str, str]:
    return {
        "dcsnCntrctNo": contract_no,
        "ntceNo": "R26BK01234567",
        "cntrctDtlSeq": "1",
        "prdctIdntNo": "12345678",
        "prdctClsfcNoNm": "레이저프린터",
        "totCntrctAmt": "99999999",
    }


def test_cross_evidence_report_dedupes_within_each_source() -> None:
    report = build_report(
        product_names=["레이저프린터"],
        lookback_days=30,
        today=date(2026, 9, 18),
        shopping_collector=FakeShoppingCollector(
            {"레이저프린터": [_price("delivery:1"), _price("delivery:1")]}
        ),
        contract_client=FakeContractClient(
            {"레이저프린터": [_contract("C-1"), _contract("C-1")]}
        ),
        key_sources={"shopping_key_source": "test", "research_key_source": "test"},
    )

    assert report["validation_status"] == "pass"
    assert report["cross_evidence_case_count"] == 1
    assert report["cross_evidence_rate"] == 1.0

    case = report["cases"][0]
    assert case["shopping"]["direct_price_record_count"] == 2
    assert case["shopping"]["unique_direct_price_record_count"] == 1
    assert case["shopping"]["duplicates_removed"] == 1
    assert case["contract"]["raw_record_count"] == 2
    assert case["contract"]["unique_contract_record_count"] == 1
    assert case["contract"]["duplicates_removed"] == 1
    assert case["contract"]["direct_price_record_count"] == 0


def test_zero_result_is_success_not_api_failure() -> None:
    report = build_report(
        product_names=["인공호흡기"],
        lookback_days=30,
        today=date(2026, 9, 18),
        shopping_collector=FakeShoppingCollector({"인공호흡기": []}),
        contract_client=FakeContractClient({"인공호흡기": []}),
    )

    assert report["validation_status"] == "pass"
    assert report["both_sources_success_case_count"] == 1
    assert report["source_failure_case_count"] == 0
    assert report["cross_evidence_rate"] == 0.0
    assert report["cases"][0]["shopping"]["status"] == "success_0"
    assert report["cases"][0]["contract"]["status"] == "success_0"


def test_source_failure_is_excluded_from_cross_evidence_denominator() -> None:
    report = build_report(
        product_names=["레이저프린터", "인공호흡기"],
        lookback_days=30,
        today=date(2026, 9, 18),
        shopping_collector=FakeShoppingCollector(
            {
                "레이저프린터": [_price("delivery:1")],
                "인공호흡기": RuntimeError("synthetic shopping failure"),
            }
        ),
        contract_client=FakeContractClient(
            {
                "레이저프린터": [_contract("C-1")],
                "인공호흡기": [_contract("C-2")],
            }
        ),
    )

    assert report["validation_status"] == "partial_failure"
    assert report["both_sources_success_case_count"] == 1
    assert report["source_failure_case_count"] == 1
    assert report["cross_evidence_case_count"] == 1
    assert report["cross_evidence_rate"] == 1.0
    failed = next(case for case in report["cases"] if case["product_name"] == "인공호흡기")
    assert failed["shopping"]["status"] == "failure"
    assert failed["contract"]["status"] == "success"


def test_safety_contract_never_promotes_contract_total_or_auto_comparability() -> None:
    report = build_report(
        product_names=["레이저프린터"],
        lookback_days=30,
        today=date(2026, 9, 18),
        shopping_collector=FakeShoppingCollector({"레이저프린터": [_price("delivery:1")]}),
        contract_client=FakeContractClient({"레이저프린터": [_contract("C-1")]}),
    )

    safety = report["safety_contract"]
    assert safety["contract_total_promoted_to_direct_price"] is False
    assert safety["cross_source_records_collapsed_without_verified_link_key"] is False
    assert safety["cross_evidence_is_automatic_quote_comparability"] is False
