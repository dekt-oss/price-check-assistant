from __future__ import annotations

from datetime import date

from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_market_models import G2BResearchRecord, G2BResearchSource
from purchase_price.services.market_research import build_market_research_terms, research_g2b_market


class RecordingResearchClient:
    def __init__(self, source: G2BResearchSource) -> None:
        self.source = source
        self.terms: list[str] = []

    def search(self, *, keyword: str, begin: date, end: date, max_pages_per_window: int = 1):
        del begin, end, max_pages_per_window
        self.terms.append(keyword)
        return (
            (
                G2BResearchRecord(
                    source_type=self.source,
                    source_record_id=f"{self.source}:{keyword}",
                    title=f"{keyword} 공개 조달 자료",
                    search_term=keyword,
                ),
            ),
            1,
        )


def test_official_resolver_candidate_names_precede_static_aliases_for_recall() -> None:
    query = ProductQuery(
        product_name="CO₂ Incubator(Water Jacket)",
        model_name="APC-30D",
        manufacturer="ASTEC",
    )

    terms = build_market_research_terms(
        query,
        max_terms=6,
        additional_terms=("이산화탄소배양기", "Carbon dioxide incubators"),
    )

    assert terms[:5] == (
        "APC-30D",
        "ASTEC APC-30D",
        "CO₂ Incubator(Water Jacket)",
        "이산화탄소배양기",
        "Carbon dioxide incubators",
    )


def test_resolver_candidate_term_remains_research_record_not_collected_price() -> None:
    bid = RecordingResearchClient(G2BResearchSource.BID_NOTICE)
    award = RecordingResearchClient(G2BResearchSource.AWARD)
    prespec = RecordingResearchClient(G2BResearchSource.PRESPEC)

    result = research_g2b_market(
        ProductQuery(product_name="CO₂ Incubator(Water Jacket)", model_name="APC-30D"),
        service_key=None,
        today=date(2026, 9, 8),
        max_terms=4,
        additional_terms=("이산화탄소배양기",),
        bid_client=bid,  # type: ignore[arg-type]
        award_client=award,  # type: ignore[arg-type]
        prespec_client=prespec,  # type: ignore[arg-type]
    )

    assert "이산화탄소배양기" in result.query_terms
    assert "이산화탄소배양기" in bid.terms
    assert "이산화탄소배양기" in award.terms
    assert "이산화탄소배양기" in prespec.terms
    assert result.records
    assert all(not isinstance(record, CollectedPrice) for record in result.records)
