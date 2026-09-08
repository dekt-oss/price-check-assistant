from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_lifecycle_enrichment import enrich_market_bundle_with_lifecycle
from purchase_price.services.g2b_market_models import (
    G2BResearchSource,
    MarketResearchBundle,
    ResearchSourceStatus,
)


def _empty_bundle() -> MarketResearchBundle:
    return MarketResearchBundle(query_terms=("이산화탄소배양기",), sources=(), records=())


def _status(bundle: MarketResearchBundle, source_type: G2BResearchSource) -> ResearchSourceStatus:
    return next(source.status for source in bundle.sources if source.source == source_type)


def test_no_seed_followups_are_not_run_not_successful_zero() -> None:
    bid_items = enrich_market_bundle_with_bid_items(_empty_bundle(), service_key=None)
    contracts = enrich_market_bundle_with_contracts(_empty_bundle(), service_key=None)
    lifecycle = enrich_market_bundle_with_lifecycle(_empty_bundle(), service_key=None)

    assert _status(bid_items, G2BResearchSource.BID_ITEM) == ResearchSourceStatus.NOT_RUN
    assert _status(contracts, G2BResearchSource.CONTRACT) == ResearchSourceStatus.NOT_RUN
    assert _status(lifecycle, G2BResearchSource.LIFECYCLE) == ResearchSourceStatus.NOT_RUN

    for bundle in (bid_items, contracts, lifecycle):
        source = bundle.sources[-1]
        assert source.request_count == 0
        assert source.records == ()


def test_not_run_is_not_classified_as_failure() -> None:
    bundle = enrich_market_bundle_with_contracts(_empty_bundle(), service_key=None)

    assert bundle.failures == ()
    assert bundle.sources[-1].status == ResearchSourceStatus.NOT_RUN
