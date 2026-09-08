from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataTransportError
from purchase_price.schemas import ProductQuery
from purchase_price.services import market_research
from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_lifecycle_enrichment import enrich_market_bundle_with_lifecycle
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchSourceResult,
    ResearchSourceStatus,
)
from purchase_price.services.market_research import research_g2b_market


class TransportFailingResearchClient:
    def __init__(self) -> None:
        self.terms: list[str] = []

    def search(self, *, keyword: str, begin: date, end: date, max_pages_per_window: int = 1):
        del begin, end, max_pages_per_window
        self.terms.append(keyword)
        raise PublicDataTransportError("synthetic transport outage")


@pytest.mark.parametrize(
    "source",
    (
        G2BResearchSource.BID_NOTICE,
        G2BResearchSource.AWARD,
        G2BResearchSource.PRESPEC,
    ),
)
def test_transport_outage_opens_source_local_circuit_after_first_term(source) -> None:
    bid = TransportFailingResearchClient()
    award = TransportFailingResearchClient()
    prespec = TransportFailingResearchClient()

    result = research_g2b_market(
        ProductQuery(product_name="마취"),
        service_key=None,
        today=date(2026, 9, 8),
        bid_client=bid,  # type: ignore[arg-type]
        award_client=award,  # type: ignore[arg-type]
        prespec_client=prespec,  # type: ignore[arg-type]
    )

    selected = next(row for row in result.sources if row.source == source)
    assert selected.status == ResearchSourceStatus.FAILURE
    assert selected.request_count == 1
    assert selected.error_type == "PublicDataTransportError"
    assert "synthetic transport outage" in selected.error_message
    assert bid.terms == ["마취"]
    assert award.terms == ["마취"]
    assert prespec.terms == ["마취"]
    assert isinstance(PublicDataTransportError("x"), PublicDataClientError)


class StubPortal:
    instances: list[StubPortal] = []

    def __init__(self, service_key: str, *, timeout_seconds: float, max_retries: int) -> None:
        self.service_key = service_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.closed = False
        type(self).instances.append(self)

    def close(self) -> None:
        self.closed = True


class StubResearchClient:
    clients: list[StubPortal] = []

    def __init__(self, service_key: str, **kwargs) -> None:
        del service_key
        self.portal = kwargs["client"]
        type(self).clients.append(self.portal)

    def search(self, *, keyword: str, begin: date, end: date, max_pages_per_window: int = 1):
        del keyword, begin, end, max_pages_per_window
        return (), 1


def test_auto_built_market_sources_share_one_portal_connection_pool(monkeypatch) -> None:
    StubPortal.instances = []
    StubResearchClient.clients = []
    monkeypatch.setattr(market_research, "PublicDataPortalClient", StubPortal)
    monkeypatch.setattr(market_research, "G2BBidResearchClient", StubResearchClient)
    monkeypatch.setattr(market_research, "G2BAwardResearchClient", StubResearchClient)
    monkeypatch.setattr(market_research, "G2BPrespecResearchClient", StubResearchClient)

    result = research_g2b_market(
        ProductQuery(product_name="마취"),
        service_key="configured-key",
        today=date(2026, 9, 8),
        max_terms=1,
    )

    assert len(StubPortal.instances) == 1
    portal = StubPortal.instances[0]
    assert StubResearchClient.clients == [portal, portal, portal]
    assert portal.closed
    assert all(row.status == ResearchSourceStatus.SUCCESS_0 for row in result.sources)


def _two_bid_bundle() -> MarketResearchBundle:
    older = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:older",
        bid_notice_no="R26BK00000001",
        bid_notice_order="00",
        published_date=date(2026, 8, 1),
    )
    newer = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:newer",
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


class TransportFailingBidItemClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_items(self, *, bid_notice_no: str, bid_notice_order=None, max_pages: int = 1):
        del bid_notice_order, max_pages
        self.calls.append(bid_notice_no)
        raise PublicDataTransportError("bid item transport outage")


class TransportFailingContractClient:
    def __init__(self) -> None:
        self.bid_calls: list[str] = []
        self.product_calls: list[str] = []

    def search_by_bid_notice(self, *, bid_notice_no: str, max_pages: int = 1):
        del max_pages
        self.bid_calls.append(bid_notice_no)
        raise PublicDataTransportError("contract transport outage")

    def search_by_product_name(
        self,
        *,
        product_name: str,
        begin_date: date,
        end_date: date,
        max_pages_per_window: int = 1,
    ):
        del begin_date, end_date, max_pages_per_window
        self.product_calls.append(product_name)
        raise AssertionError("independent fallback must not run after a linked transport outage")


class TransportFailingLifecycleClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, *, inquiry, identifier, bid_notice_order=None, page_no=1, num_of_rows=20):
        del inquiry, bid_notice_order, page_no, num_of_rows
        self.calls.append(identifier)
        raise PublicDataTransportError("lifecycle transport outage")


def test_follow_up_sources_stop_seed_fan_out_after_transport_outage() -> None:
    bundle = _two_bid_bundle()

    item_client = TransportFailingBidItemClient()
    item_result = enrich_market_bundle_with_bid_items(
        bundle,
        service_key=None,
        max_bid_notices=2,
        client=item_client,  # type: ignore[arg-type]
    )
    item_source = next(row for row in item_result.sources if row.source == G2BResearchSource.BID_ITEM)
    assert item_client.calls == ["R26BK00000002"]
    assert item_source.status == ResearchSourceStatus.FAILURE
    assert item_source.request_count == 1

    contract_client = TransportFailingContractClient()
    contract_result = enrich_market_bundle_with_contracts(
        bundle,
        service_key=None,
        max_bid_notices=2,
        client=contract_client,  # type: ignore[arg-type]
        independent_terms=("마취",),
        today=date(2026, 9, 8),
    )
    contract_source = next(
        row for row in contract_result.sources if row.source == G2BResearchSource.CONTRACT
    )
    assert contract_client.bid_calls == ["R26BK00000002"]
    assert contract_client.product_calls == []
    assert contract_source.status == ResearchSourceStatus.FAILURE
    assert contract_source.request_count == 1

    lifecycle_client = TransportFailingLifecycleClient()
    lifecycle_result = enrich_market_bundle_with_lifecycle(
        bundle,
        service_key=None,
        max_bid_notices=2,
        client=lifecycle_client,  # type: ignore[arg-type]
    )
    lifecycle_source = next(
        row for row in lifecycle_result.sources if row.source == G2BResearchSource.LIFECYCLE
    )
    assert lifecycle_client.calls == ["R26BK00000002"]
    assert lifecycle_source.status == ResearchSourceStatus.FAILURE
    assert lifecycle_source.request_count == 1


def test_live_g2b_acceptance_retries_once_and_tracks_transport_client_changes() -> None:
    workflow = Path(".github/workflows/g2b-market-sources-live.yml").read_text(encoding="utf-8")

    assert workflow.count("--max-retries 2") == 2
    assert "src/purchase_price/clients/data_go_kr.py" in workflow
