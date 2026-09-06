from __future__ import annotations

from datetime import date
from decimal import Decimal

from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchAmountType,
    ResearchSourceResult,
    ResearchSourceStatus,
)


class FakeItemClient:
    def __init__(self, *, fail_notice: str | None = None) -> None:
        self.fail_notice = fail_notice
        self.calls: list[tuple[str, str | None, int]] = []

    def fetch_items(
        self,
        *,
        bid_notice_no: str,
        bid_notice_order: str | None = None,
        max_pages: int = 1,
    ):
        self.calls.append((bid_notice_no, bid_notice_order, max_pages))
        if bid_notice_no == self.fail_notice:
            raise RuntimeError("synthetic item detail failure")
        return (
            (
                G2BResearchRecord(
                    source_type=G2BResearchSource.BID_ITEM,
                    source_record_id=f"item:{bid_notice_no}",
                    bid_notice_no=bid_notice_no,
                    bid_notice_order=bid_notice_order,
                    product_name="전신가스마취기",
                    quantity=Decimal("4"),
                    unit="SET",
                    amount=Decimal("55000000"),
                    amount_type=ResearchAmountType.ESTIMATED_UNIT_PRICE,
                ),
            ),
            1,
        )


def _bundle() -> MarketResearchBundle:
    older = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:old",
        bid_notice_no="R26BK00000001",
        bid_notice_order="00",
        published_date=date(2026, 8, 1),
    )
    newer = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:new",
        bid_notice_no="R26BK00000002",
        bid_notice_order="00",
        published_date=date(2026, 9, 1),
    )
    source = ResearchSourceResult(
        source=G2BResearchSource.BID_NOTICE,
        status=ResearchSourceStatus.SUCCESS,
        records=(older, newer),
    )
    return MarketResearchBundle(
        query_terms=("마취",),
        sources=(source,),
        records=(older, newer),
    )


def test_enrichment_is_bounded_and_prefers_latest_bid_notice() -> None:
    client = FakeItemClient()

    enriched = enrich_market_bundle_with_bid_items(
        _bundle(),
        service_key=None,
        max_bid_notices=1,
        client=client,  # type: ignore[arg-type]
    )

    assert client.calls == [("R26BK00000002", "00", 1)]
    item_source = next(
        source for source in enriched.sources if source.source == G2BResearchSource.BID_ITEM
    )
    assert item_source.status == ResearchSourceStatus.SUCCESS
    assert item_source.request_count == 1
    assert len(item_source.records) == 1
    assert item_source.records[0].amount_type == ResearchAmountType.ESTIMATED_UNIT_PRICE
    assert not item_source.records[0].is_direct_unit_price


def test_enrichment_failure_is_not_reported_as_zero_results() -> None:
    client = FakeItemClient(fail_notice="R26BK00000002")

    enriched = enrich_market_bundle_with_bid_items(
        _bundle(),
        service_key=None,
        max_bid_notices=1,
        client=client,  # type: ignore[arg-type]
    )

    item_source = next(
        source for source in enriched.sources if source.source == G2BResearchSource.BID_ITEM
    )
    assert item_source.status == ResearchSourceStatus.FAILURE
    assert item_source.request_count == 1
    assert item_source.error_type == "RuntimeError"
    assert "synthetic item detail failure" in item_source.error_message
    assert not item_source.records


def test_no_bid_notices_is_successful_zero_without_api_call() -> None:
    bundle = MarketResearchBundle(query_terms=("마취",), sources=(), records=())
    client = FakeItemClient()

    enriched = enrich_market_bundle_with_bid_items(
        bundle,
        service_key=None,
        client=client,  # type: ignore[arg-type]
    )

    assert not client.calls
    assert enriched.sources[-1].source == G2BResearchSource.BID_ITEM
    assert enriched.sources[-1].status == ResearchSourceStatus.SUCCESS_0
