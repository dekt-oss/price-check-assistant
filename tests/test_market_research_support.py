from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.market_research_support import (
    SupplierPriority,
    SupplierSource,
    alternative_research_gate,
    build_alternative_web_search_links,
    build_web_supplier_search_links,
    extract_g2b_supplier_candidates,
    extract_mfds_business_supplier_candidates,
)
from purchase_price.services.mfds_device_intelligence import MedicalDeviceBusinessRecord


def _price(*, conditions: str | None) -> CollectedPrice:
    return CollectedPrice(
        manufacturer=None,
        product_name="심장충격기",
        model_name="MODEL-1",
        specification=None,
        price=Decimal("1000000"),
        evidence_type=EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        source_type=SourceType.PROCUREMENT,
        source_name="나라장터",
        source_url="https://example.invalid/evidence",
        collected_at=date(2026, 9, 4),
        conditions=conditions,
        match_grade=MatchGrade.A,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )


def _business(*, name: str, status: str, permit: str) -> MedicalDeviceBusinessRecord:
    return MedicalDeviceBusinessRecord(
        company_name=name,
        industry_type="의료기기 수입업",
        business_status=status,
        permit_date=date(2024, 1, 1),
        address="서울",
        business_permit_number=permit,
    )


def test_extract_g2b_supplier_candidates_uses_explicit_supplier_only() -> None:
    candidates = extract_g2b_supplier_candidates(
        [
            _price(conditions="공급업체=부산메디칼; 수요기관=병원A"),
            _price(conditions="공급업체=부산메디칼; 수요기관=병원B"),
            _price(conditions="수요기관=병원C"),
            _price(conditions="공급업체=서울헬스케어"),
        ]
    )

    assert [item.name for item in candidates] == ["부산메디칼", "서울헬스케어"]
    assert all(item.source == SupplierSource.G2B for item in candidates)
    assert all(item.priority == SupplierPriority.G2B for item in candidates)


def test_mfds_business_supplier_candidates_use_only_active_business_permits() -> None:
    candidates = extract_mfds_business_supplier_candidates(
        [
            _business(name="예시메디칼", status="영업", permit="A-1"),
            _business(name="예시메디칼", status="영업", permit="A-1"),
            _business(name="폐업메디칼", status="폐업", permit="X-1"),
        ]
    )

    assert [item.name for item in candidates] == ["예시메디칼"]
    assert candidates[0].source == SupplierSource.MFDS
    assert candidates[0].priority == SupplierPriority.MFDS
    assert "업허가" in candidates[0].evidence
    assert "총판·대리점 관계를 의미하지 않음" in candidates[0].evidence


def test_alternative_research_gate_opens_only_on_zero_active_candidates() -> None:
    assert alternative_research_gate(2).enabled is False
    assert alternative_research_gate(0).enabled is True


def test_web_supplier_links_are_explicitly_web_labeled() -> None:
    links = build_web_supplier_search_links("심장충격기", "MODEL-1")

    assert links
    assert all(label.startswith("웹 ·") for label, _ in links)
    assert all(url.startswith("https://www.google.com/search?q=") for _, url in links)


def test_alternative_web_search_is_research_not_empty_query() -> None:
    links = build_alternative_web_search_links(
        product_name="심장충격기",
        intended_use="응급 심율동전환",
        key_specification="biphasic",
    )

    assert links[0][0] == "웹 · 대체장비 후보 조사"
    assert "google.com/search" in links[0][1]
