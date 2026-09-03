from datetime import date
from decimal import Decimal

from purchase_price.domain import MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.pricing import assess_prices


def item(price: str, grade: MatchGrade) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="ABC",
        product_name="Monitor",
        model_name="XYZ-100",
        specification="std",
        price=Decimal(price),
        source_type=SourceType.PUBLIC_CONTRACT,
        source_name="test",
        source_url=None,
        collected_at=date.today(),
        match_grade=grade,
    )


def test_ab_only_define_direct_range():
    result = assess_prices(
        [item("35800000", MatchGrade.A), item("37500000", MatchGrade.B), item("34000000", MatchGrade.C)],
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
