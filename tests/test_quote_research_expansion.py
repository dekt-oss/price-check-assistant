from decimal import Decimal

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
    G2BUnmappedDiscoveryResult,
    build_g2b_research_terms,
)
from purchase_price.services.market_price_research import (
    should_run_broad_research,
    summarize_g2b_research_bands,
)
from purchase_price.services.market_research import build_market_research_terms
from purchase_price.services.quote_research_hints import build_quote_filename_research_hints


def test_quote_filename_yields_product_family_hints_without_department_prefix() -> None:
    hints = build_quote_filename_research_hints(
        "재활의학과 로봇보조 정형용 운동장치 견적2.pdf"
    )

    assert "로봇보조 정형용 운동장치" in hints
    assert "로봇보조정형용운동장치" in hints
    assert "정형용 운동장치" in hints
    assert not any("재활의학과" in term for term in hints)


def test_market_research_searches_exact_label_and_category_hints_together() -> None:
    query = ProductQuery(
        product_name="엑소아틀레트 - II",
        research_hints=("로봇보조 정형용 운동장치", "로봇보조정형용운동장치"),
    )

    terms = build_market_research_terms(query)

    assert terms[0] == "엑소아틀레트 - II"
    assert "로봇보조 정형용 운동장치" in terms
    assert "로봇보조정형용운동장치" in terms


def test_shopping_research_uses_category_hints_even_when_quote_label_is_model_like() -> None:
    query = ProductQuery(
        product_name="엑소아틀레트 - II",
        research_hints=("로봇보조 정형용 운동장치", "정형용 운동장치"),
    )

    terms = build_g2b_research_terms(query)

    assert "엑소아틀레트 II" in terms
    assert "로봇보조 정형용 운동장치" in terms
    assert "정형용 운동장치" in terms


def test_broad_research_can_start_from_model_or_research_hint_without_product_name() -> None:
    assert should_run_broad_research(ProductQuery(model_name="FLOW-C"), g2b_enabled=True)
    assert should_run_broad_research(
        ProductQuery(research_hints=("가스마취기",)), g2b_enabled=True
    )


def _candidate(relevance: str, price: str) -> G2BDiscoveryCandidate:
    return G2BDiscoveryCandidate(
        title=f"{relevance} 제품",
        classification_name="스마트폰",
        classification_code="123",
        price=Decimal(price),
        transaction_date=None,
        source_record_id=f"{relevance}-{price}",
        relevance=relevance,
    )


def test_model_and_alternative_price_bands_never_mix() -> None:
    discovery = G2BUnmappedDiscoveryResult(
        status="success",
        terms=("아이폰17", "스마트폰"),
        request_count=2,
        records_seen=3,
        candidates=(
            _candidate("모델 표기 후보", "100"),
            _candidate("동일분류·대체 후보", "70"),
            _candidate("동일분류·대체 후보", "80"),
        ),
    )

    model_band, manufacturer_band, alternative_band = summarize_g2b_research_bands(discovery)

    assert model_band.candidate_count == 1
    assert model_band.median == Decimal("100")
    assert manufacturer_band.candidate_count == 0
    assert alternative_band.candidate_count == 2
    assert alternative_band.low == Decimal("70")
    assert alternative_band.high == Decimal("80")
