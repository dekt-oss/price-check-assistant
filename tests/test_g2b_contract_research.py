from __future__ import annotations

from datetime import date
from decimal import Decimal

from purchase_price.schemas import CollectedPrice
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_contract_research import (
    G2BContractResearchClient,
    parse_contract_research,
)
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchAmountType,
    ResearchSourceResult,
    ResearchSourceStatus,
)
from purchase_price.services.g2b_research_linking import link_procurement_cases


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


def test_contract_total_is_research_context_not_unit_price() -> None:
    record = parse_contract_research(
        {
            "dcsnCntrctNo": "20260900123",
            "bidNtceNo": "R26BK01234567",
            "bidNtceOrd": "00",
            "cntrctNm": "전신가스마취기 구매 계약",
            "prdctClsfcNoNm": "전신가스마취기",
            "cntrctInsttNm": "테스트병원",
            "cntrctCnclsDate": "20260905",
            "totCntrctAmt": "200,000,000",
            "cntrctCorpNm": "테스트업체",
            "cntrctDtlInfoUrl": "https://example.test/contract/1",
        }
    )

    assert record.source_type == G2BResearchSource.CONTRACT
    assert record.contract_no == "20260900123"
    assert record.bid_notice_no == "R26BK01234567"
    assert record.amount == Decimal("200000000")
    assert record.amount_type == ResearchAmountType.CONTRACT_TOTAL
    assert record.supplier == "테스트업체"
    assert record.published_date == date(2026, 9, 5)
    assert not record.is_direct_unit_price
    assert not isinstance(record, CollectedPrice)


def test_contract_client_queries_official_ppssrch_by_notice_number() -> None:
    portal = FakePortal(
        [
            _page(
                [
                    {
                        "dcsnCntrctNo": "20260900123",
                        "ntceNo": "R26BK01234567",
                        "cntrctNm": "전신가스마취기 구매 계약",
                    }
                ]
            )
        ]
    )
    client = G2BContractResearchClient("key", client=portal)  # type: ignore[arg-type]

    records, request_count = client.search_by_bid_notice(
        bid_notice_no="R26BK01234567",
        max_pages=1,
    )

    assert request_count == 1
    assert len(records) == 1
    assert records[0].bid_notice_no == "R26BK01234567"
    _, endpoint, params = portal.calls[0]
    assert endpoint == "getCntrctInfoListThngPPSSrch"
    assert params["inqryDiv"] == "4"
    assert params["ntceNo"] == "R26BK01234567"
    assert "bidNtceNo" not in params
    assert params["pageNo"] == 1


class FakeContractClient:
    def __init__(self, *, fail_notice: str | None = None) -> None:
        self.fail_notice = fail_notice
        self.calls: list[str] = []

    def search_by_bid_notice(self, *, bid_notice_no: str, max_pages: int = 1):
        self.calls.append(bid_notice_no)
        if bid_notice_no == self.fail_notice:
            raise RuntimeError("synthetic contract failure")
        return (
            (
                G2BResearchRecord(
                    source_type=G2BResearchSource.CONTRACT,
                    source_record_id=f"contract:{bid_notice_no}",
                    bid_notice_no=bid_notice_no,
                    contract_no="C-1",
                    amount=Decimal("200000000"),
                    amount_type=ResearchAmountType.CONTRACT_TOTAL,
                ),
            ),
            1,
        )


def _bundle() -> MarketResearchBundle:
    bid = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:1",
        bid_notice_no="R26BK01234567",
        bid_notice_order="00",
        published_date=date(2026, 9, 1),
    )
    source = ResearchSourceResult(
        source=G2BResearchSource.BID_NOTICE,
        status=ResearchSourceStatus.SUCCESS,
        records=(bid,),
    )
    return MarketResearchBundle(query_terms=("마취",), sources=(source,), records=(bid,))


def test_contract_enrichment_links_by_explicit_bid_number() -> None:
    client = FakeContractClient()

    enriched = enrich_market_bundle_with_contracts(
        _bundle(),
        service_key=None,
        client=client,  # type: ignore[arg-type]
    )

    assert client.calls == ["R26BK01234567"]
    contract_source = next(
        source for source in enriched.sources if source.source == G2BResearchSource.CONTRACT
    )
    assert contract_source.status == ResearchSourceStatus.SUCCESS
    assert contract_source.records[0].amount_type == ResearchAmountType.CONTRACT_TOTAL

    linked = link_procurement_cases(enriched.records)
    assert len(linked) == 1
    assert linked[0].bid_notice_no == "R26BK01234567"
    assert linked[0].has_contract
    assert linked[0].contracts == contract_source.records


def test_contract_failure_is_not_zero_results() -> None:
    client = FakeContractClient(fail_notice="R26BK01234567")

    enriched = enrich_market_bundle_with_contracts(
        _bundle(),
        service_key=None,
        client=client,  # type: ignore[arg-type]
    )

    source = next(
        source for source in enriched.sources if source.source == G2BResearchSource.CONTRACT
    )
    assert source.status == ResearchSourceStatus.FAILURE
    assert source.request_count == 1
    assert source.error_type == "RuntimeError"
    assert "synthetic contract failure" in source.error_message
