from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import resolve_verified_g2b_mapping
from purchase_price.services.g2b_research_terms import research_terms_for_query


class ResearchBasisStatus(StrEnum):
    VERIFIED_OFFICIAL_CLASSIFICATION = "verified_official_classification"
    RESEARCH_CANDIDATE = "research_candidate"
    QUOTE_LABEL_FALLBACK = "quote_label_fallback"


@dataclass(frozen=True)
class ResearchBasis:
    name: str
    status: ResearchBasisStatus
    code: str | None = None
    rationale: str = ""

    @property
    def is_verified_official(self) -> bool:
        return self.status == ResearchBasisStatus.VERIFIED_OFFICIAL_CLASSIFICATION


def resolve_research_basis(query: ProductQuery) -> ResearchBasis:
    """Return the best price-research basis without promoting inferred identity.

    A verified G2B mapping is the only route to an official classification in this resolver.
    Curated research terms are useful fallback category names, but remain explicitly unverified.
    """

    mapping = resolve_verified_g2b_mapping(query)
    if mapping is not None and mapping.detail_product_name:
        return ResearchBasis(
            name=mapping.detail_product_name,
            code=mapping.detail_product_code,
            status=ResearchBasisStatus.VERIFIED_OFFICIAL_CLASSIFICATION,
            rationale="검증된 나라장터 세부품명 mapping",
        )

    research_terms = research_terms_for_query(query)
    if research_terms:
        return ResearchBasis(
            name=research_terms[0],
            status=ResearchBasisStatus.RESEARCH_CANDIDATE,
            rationale="Research 확장용 기준 품목 후보이며 공식분류·동일제품 근거 아님",
        )

    fallback = query.product_name.strip() or query.model_name.strip()
    return ResearchBasis(
        name=fallback,
        status=ResearchBasisStatus.QUOTE_LABEL_FALLBACK,
        rationale="별도 분류 근거가 없어 견적 표기를 그대로 사용",
    )
