from datetime import date
from decimal import Decimal

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_research_terms import research_terms_for_query
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
    G2BUnmappedDiscoveryResult,
)
from purchase_price.services.market_price_research import (
    quote_delta_from_market_median,
    should_run_broad_research,
    summarize_g2b_research,
)


def _candidate(*, price: str, relevance: str) -> G2BDiscoveryCandidate:
    return G2BDiscoveryCandidate(
        title="예시 거래",
        classification_name="가스마취기",
        classification_code="42182000",
        price=Decimal(price),
        transaction_date=date(2026, 9, 1),
        source_record_id=f"row-{price}-{relevance}",
        search_term="마취",
        relevance=relevance,
    )


def test_product_keyword_alone_runs_broad_research() -> None:
    query = ProductQuery(product_name="마취")

    assert should_run_broad_research(query, g2b_enabled=True) is True
    assert should_run_broad_research(query, g2b_enabled=False) is False
    terms = research_terms_for_query(query)
    assert "가스마취기" in terms
    assert "마취기" in terms
    assert len(terms) >= 3


def test_market_reference_summary_aggregates_same_model_only() -> None:
    discovery = G2BUnmappedDiscoveryResult(
        status="success",
        terms=("마취",),
        request_count=1,
        records_seen=4,
        candidates=(
            _candidate(price="100", relevance="모델 표기 후보"),
            _candidate(price="140", relevance="모델 표기 후보"),
            _candidate(price="200", relevance="제조사 표기 후보"),
            _candidate(price="300", relevance="분류 후보"),
        ),
    )

    summary = summarize_g2b_research(discovery)

    assert summary.candidate_count == 4
    assert summary.model_candidate_count == 2
    assert summary.manufacturer_candidate_count == 1
    assert summary.classification_candidate_count == 1
    assert summary.low == Decimal("100")
    assert summary.median == Decimal("120")
    assert summary.high == Decimal("140")
    assert quote_delta_from_market_median(Decimal("150"), summary) == Decimal("25")


def test_alternative_candidates_do_not_create_quote_price_band() -> None:
    discovery = G2BUnmappedDiscoveryResult(
        status="success",
        terms=("재활로봇",),
        request_count=1,
        records_seen=2,
        candidates=(
            _candidate(price="46000000", relevance="제조사 표기 후보"),
            _candidate(price="90000000", relevance="분류 후보"),
        ),
    )

    summary = summarize_g2b_research(discovery)

    assert summary.candidate_count == 2
    assert summary.model_candidate_count == 0
    assert summary.has_prices is False
    assert summary.low is None
    assert summary.median is None
    assert summary.high is None
    assert quote_delta_from_market_median(Decimal("140000000"), summary) is None
