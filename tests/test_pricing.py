from datetime import date
from decimal import Decimal

from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.pricing import assess_prices


def item(
    price: str,
    grade: MatchGrade,
    evidence_type: EvidenceType = EvidenceType.CONTRACT_UNIT_PRICE,
) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="ABC",
        product_name="Monitor",
        model_name="XYZ-100",
        specification="std",
        price=Decimal(price),
        evidence_type=evidence_type,
        source_type=SourceType.PUBLIC_CONTRACT,
        source_name="test",
        source_url=None,
        collected_at=date.today(),
        match_grade=grade,
    )


def test_ab_only_define_direct_range():
    result = assess_prices(
        [
            item("35800000", MatchGrade.A),
            item("37500000", MatchGrade.B, EvidenceType.PUBLIC_SALE_PRICE),
            item("34000000", MatchGrade.C),
        ],
        Decimal("38500000"),
    )
    assert result.low == Decimal("35800000")
    assert result.high == Decimal("37500000")
    assert result.quote_position == "상단 초과"


def test_no_direct_evidence_returns_insufficient():
    result = assess_prices([item("34000000", MatchGrade.C)], Decimal("38500000"))
    assert result.low is None
    assert result.confidence == "낮음"
    assert "산정 불가" in result.message


def test_same_product_budget_is_not_direct_price_evidence():
    result = assess_prices(
        [
            item("50000000", MatchGrade.A, EvidenceType.BUDGET_AMOUNT),
            item("49000000", MatchGrade.A, EvidenceType.BID_BASE_AMOUNT),
        ],
        Decimal("38500000"),
    )
    assert result.comparable_count == 0
    assert result.low is None
    assert result.high is None
    assert result.confidence == "산정불가"
