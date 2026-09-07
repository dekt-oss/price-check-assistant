from __future__ import annotations

from datetime import date

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchSourceStatus,
)
from purchase_price.services.market_research import (
    is_g2b_research_authorization_error,
    research_g2b_market,
)


class StubResearchClient:
    def __init__(self, source: G2BResearchSource, *, auth_failure: bool = False) -> None:
        self.source = source
        self.auth_failure = auth_failure
        self.terms: list[str] = []

    def search(self, *, keyword: str, begin: date, end: date, max_pages_per_window: int = 1):
        self.terms.append(keyword)
        if self.auth_failure:
            raise PublicDataClientError(
                "Public Data Portal request failed: HTTP 403 code=30"
            )
        return (
            (
                G2BResearchRecord(
                    source_type=self.source,
                    source_record_id=f"{self.source.value}:{keyword}",
                    title=keyword,
                    search_term=keyword,
                ),
            ),
            1,
        )


def test_authorization_error_classifier_is_specific_to_observed_gateway_markers() -> None:
    assert is_g2b_research_authorization_error(
        PublicDataClientError("Public Data Portal request failed: HTTP 403 code=30")
    )
    assert is_g2b_research_authorization_error(PublicDataClientError("code=30"))
    assert not is_g2b_research_authorization_error(PublicDataClientError("HTTP 500"))
    assert not is_g2b_research_authorization_error(RuntimeError("synthetic failure"))


def test_unauthorized_source_stops_after_first_term_while_other_sources_continue() -> None:
    bid = StubResearchClient(G2BResearchSource.BID_NOTICE, auth_failure=True)
    award = StubResearchClient(G2BResearchSource.AWARD)
    prespec = StubResearchClient(G2BResearchSource.PRESPEC)

    result = research_g2b_market(
        ProductQuery(product_name="마취"),
        service_key=None,
        today=date(2026, 9, 7),
        bid_client=bid,  # type: ignore[arg-type]
        award_client=award,  # type: ignore[arg-type]
        prespec_client=prespec,  # type: ignore[arg-type]
    )

    expected_terms = ["마취", "마취기", "가스마취기", "전신가스마취기", "마취기시스템"]
    bid_result = next(
        source
        for source in result.sources
        if source.source == G2BResearchSource.BID_NOTICE
    )
    award_result = next(
        source for source in result.sources if source.source == G2BResearchSource.AWARD
    )
    prespec_result = next(
        source for source in result.sources if source.source == G2BResearchSource.PRESPEC
    )

    assert bid.terms == ["마취"]
    assert bid_result.status == ResearchSourceStatus.NOT_AUTHORIZED
    assert bid_result.request_count == 1
    assert "403" in bid_result.error_message

    assert award.terms == expected_terms
    assert prespec.terms == expected_terms
    assert award_result.status == ResearchSourceStatus.SUCCESS
    assert prespec_result.status == ResearchSourceStatus.SUCCESS
    assert len(award_result.records) == len(expected_terms)
    assert len(prespec_result.records) == len(expected_terms)
