from __future__ import annotations

from datetime import date
from decimal import Decimal

from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchAmountType,
    ResearchSourceStatus,
)
from purchase_price.services.g2b_market_sources import (
    G2BBidResearchClient,
    parse_award,
    parse_bid_notice,
    parse_prespec,
)
from purchase_price.services.market_research import research_g2b_market


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


def test_bid_notice_amount_is_estimate_not_direct_price() -> None:
    record = parse_bid_notice(
        {
            "bidNtceNo": "R26BK0001",
            "bidNtceOrd": "00",
            "bidNtceNm": "전신가스마취기 4sets 구매",
            "dminsttNm": "테스트병원",
            "bidNtceDt": "202608141030",
            "presmptPrce": "220000000",
            "bidNtceDtlUrl": "https://example.test/bid/1",
            "ntceSpecFileNm1": "규격서.pdf",
            "ntceSpecDocUrl1": "https://example.test/spec.pdf",
        },
        search_term="마취",
    )

    assert record.source_type == G2BResearchSource.BID_NOTICE
    assert record.bid_notice_no == "R26BK0001"
    assert record.amount == Decimal("220000000")
    assert record.amount_type == ResearchAmountType.ESTIMATED_PRICE
    assert not record.is_direct_unit_price
    assert record.attachments[0].name == "규격서.pdf"


def test_award_amount_is_total_not_unit_price() -> None:
    record = parse_award(
        {
            "bidNtceNo": "R26BK0002",
            "bidNtceOrd": "00",
            "bidNtceNm": "가스마취기 구매",
            "sucsfbidAmt": "200000000",
            "bidwinnrNm": "테스트업체",
            "fnlSucsfDate": "20260820",
        },
        search_term="마취",
    )

    assert record.amount == Decimal("200000000")
    assert record.amount_type == ResearchAmountType.AWARD_TOTAL
    assert record.supplier == "테스트업체"
    assert not record.is_direct_unit_price


def test_prespec_budget_is_context_not_unit_price() -> None:
    record = parse_prespec(
        {
            "bfSpecRgstNo": "123456",
            "bfSpecNm": "마취기시스템 구입",
            "prdctClsfcNoNm": "의료용가스마취기",
            "asignBdgtAmt": "66000000",
            "rlDminsttNm": "테스트병원",
            "rgstDt": "20260801",
        },
        search_term="마취",
    )

    assert record.amount == Decimal("66000000")
    assert record.amount_type == ResearchAmountType.BUDGET_AMOUNT
    assert record.prespec_no == "123456"
    assert not record.is_direct_unit_price


def test_bid_search_uses_keyword_without_verified_mapping_and_splits_date_windows() -> None:
    portal = FakePortal(
        [
            _page([{"bidNtceNo": "R26BK1", "bidNtceNm": "가스마취기 구매"}]),
            _page([]),
        ]
    )
    client = G2BBidResearchClient("key", client=portal)  # type: ignore[arg-type]

    records, request_count = client.search(
        keyword="마취",
        begin=date(2026, 7, 20),
        end=date(2026, 9, 6),
        max_pages_per_window=1,
    )

    assert request_count == 2
    assert len(records) == 1
    assert records[0].title == "가스마취기 구매"
    assert [call[2]["bidNtceNm"] for call in portal.calls] == ["마취", "마취"]
    assert portal.calls[0][2]["inqryBgnDt"] == "202607200000"
    assert portal.calls[0][2]["inqryEndDt"] == "202608182359"
    assert portal.calls[1][2]["inqryBgnDt"] == "202608190000"
    assert portal.calls[1][2]["inqryEndDt"] == "202609062359"


class FakeResearchClient:
    def __init__(self, source: G2BResearchSource, *, fail: bool = False) -> None:
        self.source = source
        self.fail = fail
        self.terms: list[str] = []

    def search(self, *, keyword: str, begin: date, end: date, max_pages_per_window: int = 1):
        self.terms.append(keyword)
        if self.fail:
            raise RuntimeError("synthetic source failure")
        return (
            (
                G2BResearchRecord(
                    source_type=self.source,
                    source_record_id=f"{self.source}:{keyword}",
                    title=f"{keyword} 관련 자료",
                    search_term=keyword,
                ),
            ),
            1,
        )


def test_market_research_runs_for_plain_product_keyword_without_model_or_mapping() -> None:
    bid = FakeResearchClient(G2BResearchSource.BID_NOTICE)
    award = FakeResearchClient(G2BResearchSource.AWARD)
    prespec = FakeResearchClient(G2BResearchSource.PRESPEC)

    result = research_g2b_market(
        ProductQuery(product_name="마취"),
        service_key=None,
        today=date(2026, 9, 6),
        bid_client=bid,  # type: ignore[arg-type]
        award_client=award,  # type: ignore[arg-type]
        prespec_client=prespec,  # type: ignore[arg-type]
    )

    expected_terms = ("마취", "마취기", "가스마취기", "전신가스마취기", "마취기시스템")
    assert result.query_terms == expected_terms
    assert bid.terms == list(expected_terms)
    assert award.terms == list(expected_terms)
    assert prespec.terms == list(expected_terms)
    assert len(result.records) == 15
    assert all(not isinstance(record, CollectedPrice) for record in result.records)


def test_source_failure_is_not_reported_as_zero_results() -> None:
    bid = FakeResearchClient(G2BResearchSource.BID_NOTICE, fail=True)
    award = FakeResearchClient(G2BResearchSource.AWARD)
    prespec = FakeResearchClient(G2BResearchSource.PRESPEC)

    result = research_g2b_market(
        ProductQuery(product_name="마취"),
        service_key=None,
        today=date(2026, 9, 6),
        bid_client=bid,  # type: ignore[arg-type]
        award_client=award,  # type: ignore[arg-type]
        prespec_client=prespec,  # type: ignore[arg-type]
    )

    bid_result = next(source for source in result.sources if source.source == G2BResearchSource.BID_NOTICE)
    assert bid_result.status == ResearchSourceStatus.FAILURE
    assert bid_result.error_type == "RuntimeError"
    assert "synthetic source failure" in bid_result.error_message
