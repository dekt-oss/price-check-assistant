from datetime import date

from purchase_price.services.g2b_lifecycle import (
    G2BLifecycleInquiry,
    G2BLifecycleRecord,
    G2BLifecycleResult,
)
from purchase_price.services.g2b_lifecycle_enrichment import enrich_market_bundle_with_lifecycle
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchAmountType,
    ResearchSourceResult,
    ResearchSourceStatus,
)


class StubLifecycleClient:
    def __init__(self) -> None:
        self.calls: list[tuple[G2BLifecycleInquiry, str]] = []

    def fetch(self, *, inquiry, identifier, bid_notice_order=None, page_no=1, num_of_rows=20):
        self.calls.append((inquiry, identifier))
        return G2BLifecycleResult(
            inquiry=inquiry,
            identifier=identifier,
            records=(
                G2BLifecycleRecord(
                    source_record_id=f"bid:{identifier}:00|prespec:123",
                    order_business_name="의료장비 구매",
                    order_institution="타 기관",
                    prespec_no="123",
                    bid_notice_no=identifier,
                    bid_notice_order="00",
                    bid_notice_name="의료장비 입찰",
                    bid_institution="타 기관",
                    bid_notice_datetime="2026-09-01 10:00:00",
                    award_info_list="[1^업체^50000000]",
                    contract_info_list="[1^계약^60000000]",
                ),
            ),
        )


def test_lifecycle_enrichment_uses_existing_bid_identifier_and_never_sets_amount() -> None:
    bid = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:20260901001:00",
        title="의료장비 입찰",
        published_date=date(2026, 9, 1),
        bid_notice_no="20260901001",
    )
    bundle = MarketResearchBundle(
        query_terms=("의료장비",),
        sources=(
            ResearchSourceResult(
                source=G2BResearchSource.BID_NOTICE,
                status=ResearchSourceStatus.SUCCESS,
                records=(bid,),
            ),
        ),
        records=(bid,),
    )
    stub = StubLifecycleClient()

    enriched = enrich_market_bundle_with_lifecycle(
        bundle,
        service_key=None,
        max_bid_notices=1,
        client=stub,
    )

    assert stub.calls == [(G2BLifecycleInquiry.BID_NOTICE, "20260901001")]
    lifecycle_source = next(
        source for source in enriched.sources if source.source == G2BResearchSource.LIFECYCLE
    )
    assert lifecycle_source.status == ResearchSourceStatus.SUCCESS
    assert len(lifecycle_source.records) == 1
    record = lifecycle_source.records[0]
    assert record.prespec_no == "123"
    assert record.amount is None
    assert record.amount_type == ResearchAmountType.UNKNOWN
    assert not record.is_direct_unit_price


def test_lifecycle_enrichment_skips_network_when_no_bid_notice_exists() -> None:
    bundle = MarketResearchBundle(query_terms=("의료장비",), sources=(), records=())

    enriched = enrich_market_bundle_with_lifecycle(bundle, service_key=None)

    source = next(source for source in enriched.sources if source.source == G2BResearchSource.LIFECYCLE)
    assert source.status == ResearchSourceStatus.NOT_RUN
    assert source.request_count == 0
    assert source.records == ()
