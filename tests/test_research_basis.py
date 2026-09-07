from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import build_g2b_research_terms
from purchase_price.services.research_basis import (
    ResearchBasisStatus,
    research_terms_with_basis,
    resolve_research_basis,
)


def test_verified_mapping_becomes_official_research_basis() -> None:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        model_name="ApeosPrint C5570 GK",
        manufacturer="FUJIFILM Business Innovation",
    )
    basis = resolve_research_basis(query)

    assert basis.status == ResearchBasisStatus.VERIFIED_OFFICIAL_CLASSIFICATION
    assert basis.name == "레이저프린터"
    assert basis.code == "4321210501"
    assert "레이저프린터" in research_terms_with_basis(query)


def test_verified_mapping_adds_official_term_when_quote_label_differs() -> None:
    query = ProductQuery(
        product_name="핵산증폭기",
        model_name="Veriti Pro Dx",
        manufacturer="Thermo Fisher Scientific",
    )

    curated_terms = research_terms_with_basis(query)
    assert curated_terms == ("유전자증폭기",)
    assert build_g2b_research_terms(query, curated_terms=curated_terms) == (
        "핵산증폭기",
        "유전자증폭기",
    )


def test_exoatlet_uses_curated_category_as_unverified_research_basis() -> None:
    query = ProductQuery(product_name="엑소아틀레트 - II")
    basis = resolve_research_basis(query)

    assert basis.status == ResearchBasisStatus.RESEARCH_CANDIDATE
    assert basis.name == "로봇보조 정형용 운동장치"
    assert basis.code is None
    assert basis.is_verified_official is False
    assert research_terms_with_basis(query) == (
        "로봇보조 정형용 운동장치",
        "보행재활로봇",
        "재활로봇",
    )


def test_unmapped_product_without_curated_terms_falls_back_to_quote_label() -> None:
    query = ProductQuery(product_name="완전히새로운장비")
    basis = resolve_research_basis(query)

    assert basis.status == ResearchBasisStatus.QUOTE_LABEL_FALLBACK
    assert basis.name == "완전히새로운장비"
    assert basis.code is None
    assert research_terms_with_basis(query) == ()
