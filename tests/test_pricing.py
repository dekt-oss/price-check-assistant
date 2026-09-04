from datetime import date
from decimal import Decimal

from purchase_price.domain import (
    ComparisonScope,
    EvidenceType,
    MatchGrade,
    SourceType,
)
from purchase_price.schemas import CollectedPrice
from purchase_price.services.pricing import assess_prices


def item(
    price: str,
    grade: MatchGrade,
    evidence_type: EvidenceType = EvidenceType.CONTRACT_UNIT_PRICE,
    *,
    comparison_scope: ComparisonScope = ComparisonScope.OBSERVED_ONLY,
    currency: str = "KRW",
    source_name: str = "test",
) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="ABC",
        product_name="Monitor",
        model_name="XYZ-100",
        specification="std",
        price=Decimal(price),
        evidence_type=evidence_type,
        source_type=SourceType.PUBLIC_CONTRACT,
        source_name=source_name,
        source_url=None,
        collected_at=date.today(),
        currency=currency,
        match_grade=grade,
        comparison_scope=comparison_scope,
    )


def test_ab_direct_evidence_defines_observed_range_but_not_quote_position() -> None:
    result = assess_prices(
        [
            item("35800000", MatchGrade.A),
            item("37500000", MatchGrade.B, EvidenceType.PUBLIC_SALE_PRICE),
            item("34000000", MatchGrade.C),
        ],
        Decimal("38500000"),
    )
    assert result.observed_count == 2
    assert result.low == Decimal("35800000")
    assert result.high == Decimal("37500000")
    assert result.quote_comparable_count == 0
    assert result.quote_position is None
    assert "판정하지 않음" in result.message


def test_quote_position_requires_explicit_quote_comparable_scope() -> None:
    result = assess_prices(
        [
            item(
                "35800000",
                MatchGrade.A,
                comparison_scope=ComparisonScope.QUOTE_COMPARABLE,
                source_name="source-a",
            ),
            item(
                "37500000",
                MatchGrade.B,
                EvidenceType.PUBLIC_SALE_PRICE,
                comparison_scope=ComparisonScope.QUOTE_COMPARABLE,
                source_name="source-b",
            ),
        ],
        Decimal("38500000"),
    )
    assert result.quote_comparable_count == 2
    assert result.quote_comparable_low == Decimal("35800000")
    assert result.quote_comparable_high == Decimal("37500000")
    assert result.quote_position == "상단 초과"


def test_no_direct_evidence_returns_insufficient() -> None:
    result = assess_prices([item("34000000", MatchGrade.C)], Decimal("38500000"))
    assert result.low is None
    assert result.confidence == "낮음"
    assert "산정 불가" in result.message


def test_same_product_budget_is_not_direct_price_evidence() -> None:
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


def test_non_krw_direct_evidence_is_not_mixed_into_krw_range() -> None:
    result = assess_prices(
        [
            item("1000", MatchGrade.A, currency="USD"),
            item("5000000", MatchGrade.A, currency="KRW"),
        ]
    )
    assert result.observed_count == 1
    assert result.low == Decimal("5000000")
    assert result.high == Decimal("5000000")


def test_reference_only_scope_cannot_enter_observed_direct_range() -> None:
    result = assess_prices(
        [
            item(
                "2500000",
                MatchGrade.A,
                comparison_scope=ComparisonScope.REFERENCE_ONLY,
            )
        ]
    )
    assert result.observed_count == 0
    assert result.low is None


def test_repeated_transactions_from_one_source_do_not_create_high_confidence() -> None:
    result = assess_prices(
        [
            item("100", MatchGrade.A, source_name="same-source"),
            item("110", MatchGrade.A, source_name="same-source"),
            item("120", MatchGrade.A, source_name="same-source"),
        ]
    )
    assert result.source_count == 1
    assert result.confidence == "보통"


def test_independent_sources_can_support_high_confidence() -> None:
    result = assess_prices(
        [
            item("100", MatchGrade.A, source_name="source-a"),
            item("110", MatchGrade.A, source_name="source-a"),
            item("120", MatchGrade.A, source_name="source-b"),
        ]
    )
    assert result.source_count == 2
    assert result.confidence == "높음"
