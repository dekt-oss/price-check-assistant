from purchase_price.schemas import ProductQuery
from purchase_price.services.research_basis import (
    ResearchBasisStatus,
    resolve_research_basis,
)


def test_verified_mapping_becomes_official_research_basis() -> None:
    basis = resolve_research_basis(
        ProductQuery(
            product_name="컬러 레이저프린터",
            model_name="ApeosPrint C5570 GK",
            manufacturer="FUJIFILM Business Innovation",
        )
    )

    assert basis.status == ResearchBasisStatus.VERIFIED_OFFICIAL_CLASSIFICATION
    assert basis.name == "레이저프린터"
    assert basis.code == "4321210501"


def test_exoatlet_uses_curated_category_as_unverified_research_basis() -> None:
    basis = resolve_research_basis(ProductQuery(product_name="엑소아틀레트 - II"))

    assert basis.status == ResearchBasisStatus.RESEARCH_CANDIDATE
    assert basis.name == "로봇보조 정형용 운동장치"
    assert basis.code is None
    assert basis.is_verified_official is False


def test_unmapped_product_without_curated_terms_falls_back_to_quote_label() -> None:
    basis = resolve_research_basis(ProductQuery(product_name="완전히새로운장비"))

    assert basis.status == ResearchBasisStatus.QUOTE_LABEL_FALLBACK
    assert basis.name == "완전히새로운장비"
    assert basis.code is None
