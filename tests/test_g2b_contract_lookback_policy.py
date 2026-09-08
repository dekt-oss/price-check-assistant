from __future__ import annotations

from datetime import date
from decimal import Decimal

from purchase_price.schemas import CollectedPrice
from purchase_price.services.g2b_contract_enrichment import (
    build_contract_lookback_stages,
    enrich_market_bundle_with_contracts,
)
from purchase_price.services.g2b_contract_research import G2BContractResearchClient
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchAmountType,
    ResearchSourceStatus,
)


class FakePortal:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return self.payloads.pop(0)


def _page(items: list[dict], total_count: int | None = None) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {
                "items": items,
                "totalCount": len(items) if total_count is None else total_count,
                "pageNo": 1,
                "numOfRows": 100,
            },
        }
    }


def test_contract_lookback_stages_expand_only_as_requested() -> None:
    assert build_contract_lookback_stages(30) == (30,)
    assert build_contract_lookback_stages(90) == (90,)
    assert build_contract_lookback_stages(365) == (90, 365)
    assert build_contract_lookback_stages(1095) == (90, 365, 1095)
    assert build_contract_lookback_stages(1825) == (90, 365, 1095, 1825)


def test_independent_contract_search_uses_official_product_and_date_fields() -> None:
    portal = FakePortal([_page([])])
    client = G2BContractResearchClient("key", client=portal)  # type: ignore[arg-type]

    records, request_count = client.search_by_product_name(
        product_name="레이저프린터",
        begin_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        max_pages_per_window=1,
    )

    assert records == ()
    assert request_count == 1
    _, endpoint, params = portal.calls[0]
    assert endpoint == "getCntrctInfoListThngPPSSrch"
    assert params["inqryDiv"] == "1"
    assert params["inqryBgnDate"] == "20260801"
    assert params["inqryEndDate"] == "20260831"
    assert params["prdctClsfcNoNm"] == "레이저프린터"
    assert "ntceNo" not in params
    assert "bidNtceNo" not in params


def test_independent_contract_search_splits_long_ranges_without_overlap() -> None:
    portal = FakePortal([_page([]), _page([]), _page([])])
    client = G2BContractResearchClient("key", client=portal)  # type: ignore[arg-type]

    _, request_count = client.search_by_product_name(
        product_name="레이저프린터",
        begin_date=date(2026, 6, 1),
        end_date=date(2026, 8, 31),
        max_pages_per_window=1,
        max_window_days=31,
    )

    assert request_count == 3
    windows = [
        (call[2]["inqryBgnDate"], call[2]["inqryEndDate"])
        for call in portal.calls
    ]
    assert windows == [
        ("20260601", "20260701"),
        ("20260702", "20260801"),
        ("20260802", "20260831"),
    ]


class FakeIndependentContractClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.bid_calls: list[str] = []
        self.product_calls: list[tuple[str, date, date]] = []

    def search_by_bid_notice(self, *, bid_notice_no: str, max_pages: int = 1):
        self.bid_calls.append(bid_notice_no)
        return (), 1

    def search_by_product_name(
        self,
        *,
        product_name: str,
        begin_date: date,
        end_date: date,
        max_pages_per_window: int = 1,
    ):
        del max_pages_per_window
        self.product_calls.append((product_name, begin_date, end_date))
        if self.fail:
            raise RuntimeError("synthetic independent contract failure")
        if len(self.product_calls) == 1:
            return (), 1
        return (
            (
                G2BResearchRecord(
                    source_type=G2BResearchSource.CONTRACT,
                    source_record_id="contract:C-1:R26BK1:1",
                    title="레이저프린터 구매 계약",
                    contract_no="C-1",
                    product_name="레이저프린터",
                    amount=Decimal("5000000"),
                    amount_type=ResearchAmountType.CONTRACT_TOTAL,
                    search_term=product_name,
                ),
            ),
            1,
        )


def _empty_bundle() -> MarketResearchBundle:
    return MarketResearchBundle(
        query_terms=("레이저프린터",),
        sources=(),
        records=(),
    )


def test_seedless_contract_enrichment_expands_from_90_days_to_one_year() -> None:
    client = FakeIndependentContractClient()

    enriched = enrich_market_bundle_with_contracts(
        _empty_bundle(),
        service_key=None,
        client=client,  # type: ignore[arg-type]
        independent_terms=("레이저프린터",),
        requested_lookback_days=365,
        today=date(2026, 9, 8),
        minimum_records_before_stop=1,
    )

    source = enriched.sources[-1]
    assert client.bid_calls == []
    assert len(client.product_calls) == 2
    assert client.product_calls[0] == (
        "레이저프린터",
        date(2026, 6, 11),
        date(2026, 9, 8),
    )
    assert client.product_calls[1] == (
        "레이저프린터",
        date(2025, 9, 9),
        date(2026, 6, 10),
    )
    assert source.status == ResearchSourceStatus.SUCCESS
    assert source.coverage_start == date(2025, 9, 9)
    assert source.coverage_end == date(2026, 9, 8)
    assert source.requested_lookback_days == 365
    assert "adaptive independent product-name" in source.search_strategy
    assert source.records[0].amount_type == ResearchAmountType.CONTRACT_TOTAL
    assert not source.records[0].is_direct_unit_price
    assert not isinstance(source.records[0], CollectedPrice)


def test_independent_contract_failure_is_not_successful_zero() -> None:
    client = FakeIndependentContractClient(fail=True)

    enriched = enrich_market_bundle_with_contracts(
        _empty_bundle(),
        service_key=None,
        client=client,  # type: ignore[arg-type]
        independent_terms=("레이저프린터",),
        requested_lookback_days=365,
        today=date(2026, 9, 8),
    )

    source = enriched.sources[-1]
    assert source.status == ResearchSourceStatus.FAILURE
    assert source.request_count == 1
    assert source.error_type == "RuntimeError"
    assert "synthetic independent contract failure" in source.error_message


def test_no_seed_and_no_independent_term_is_not_run_not_zero() -> None:
    enriched = enrich_market_bundle_with_contracts(
        _empty_bundle(),
        service_key="configured",
        independent_terms=(),
        requested_lookback_days=365,
    )

    source = enriched.sources[-1]
    assert source.status == ResearchSourceStatus.NOT_RUN
    assert source.request_count == 0
