from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
    G2BUnmappedDiscoveryResult,
)
from purchase_price.ui.widgets import build_observation_groups, discovery_candidate_rows


def _evidence(source: str, vat: str, price: str) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="Maker",
        product_name="Printer",
        model_name="M-1",
        specification="A3",
        price=Decimal(price),
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.MANUFACTURER,
        source_name=source,
        source_url="https://example.com",
        collected_at=date(2026, 9, 1),
        quantity=Decimal("1"),
        unit="대",
        vat_status=vat,
        match_grade=MatchGrade.A,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )


def test_observation_groups_do_not_merge_source_or_vat_scope() -> None:
    groups = build_observation_groups(
        [
            _evidence("source-a", "포함", "100"),
            _evidence("source-a", "포함", "110"),
            _evidence("source-a", "별도", "90"),
            _evidence("source-b", "포함", "120"),
        ]
    )
    assert [(group.source_name, group.vat_status, group.count) for group in groups] == [
        ("source-a", "별도", 1),
        ("source-a", "포함", 2),
        ("source-b", "포함", 1),
    ]


def test_discovery_candidate_amount_is_explicitly_unverified() -> None:
    candidate = G2BDiscoveryCandidate(
        title="Printer M-1",
        classification_name="프린터",
        classification_code="123",
        price=Decimal("100"),
        source_record_id="g-1",
        transaction_date=date(2026, 8, 1),
    )
    discovery = G2BUnmappedDiscoveryResult(
        status="success",
        terms=("M-1",),
        candidates=(candidate,),
        request_count=1,
        records_seen=1,
    )
    rows = discovery_candidate_rows(discovery)
    assert "표기 금액 (미검증)" in rows[0]
    assert "등급" not in rows[0]
    assert "단가" not in rows[0]
