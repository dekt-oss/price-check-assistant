from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataTransportError
from purchase_price.schemas import ProductQuery
from purchase_price.services import market_research
from purchase_price.services.g2b_market_models import (
    G2BResearchSource,
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
    instances: list["StubPortal"] = []

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


def test_live_g2b_acceptance_retries_once_and_tracks_transport_client_changes() -> None:
    workflow = Path(".github/workflows/g2b-market-sources-live.yml").read_text(encoding="utf-8")

    assert workflow.count("--max-retries 2") == 2
    assert "src/purchase_price/clients/data_go_kr.py" in workflow
