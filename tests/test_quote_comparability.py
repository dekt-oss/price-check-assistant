from datetime import date
from decimal import Decimal

from purchase_price.domain import (
    ComparisonScope,
    EvidenceType,
    MatchGrade,
    SourceType,
)
from purchase_price.schemas import CollectedPrice
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile


def _evidence(**overrides: object) -> CollectedPrice:
    values: dict[str, object] = {
        "manufacturer": "예시메디칼",
        "product_name": "초음파진단기",
        "model_name": "US-100",
        "specification": "Console",
        "price": Decimal("12000000"),
        "evidence_type": EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        "source_type": SourceType.PROCUREMENT,
        "source_name": "나라장터",
        "source_url": "https://example.invalid/evidence",
        "collected_at": date(2026, 9, 4),
        "transaction_date": date(2026, 8, 30),
        "quantity": Decimal("1"),
        "unit": "대",
        "currency": "KRW",
        "vat_status": "포함",
        "conditions": (
            "배송비=무료; 설치비=포함; 옵션=기본구성; 보증기간=2년; 유지보수=별도계약"
        ),
        "match_grade": MatchGrade.A,
        "comparison_scope": ComparisonScope.OBSERVED_ONLY,
    }
    values.update(overrides)
    return CollectedPrice(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> QuoteComparabilityContext:
    values: dict[str, object] = {
        "quote_unit_price": Decimal("12500000"),
        "quantity": Decimal("1"),
        "unit": "대",
        "quote_date": date(2026, 9, 1),
        "conditions": build_quote_condition_profile(
            vat="VAT 포함",
            delivery="무료",
            installation="설치 포함",
            options="기본구성",
            warranty="24개월",
            maintenance="별도",
        ),
    }
    values.update(overrides)
    return QuoteComparabilityContext(**values)  # type: ignore[arg-type]


def test_fully_verified_evidence_becomes_candidate_without_mutating_scope() -> None:
    evidence = _evidence()

    decision = evaluate_quote_comparability_candidate(_context(), evidence)

    assert decision.eligible_candidate is True
    assert decision.status_label == "비교가능 후보"
    assert decision.reasons == ()
    assert decision.condition_comparison.fully_aligned is True
    assert decision.date_gap_days == 2
    assert evidence.comparison_scope == ComparisonScope.OBSERVED_ONLY


def test_missing_conditions_fail_closed_with_reasons() -> None:
    evidence = _evidence(vat_status=None, conditions=None, quantity=None, unit=None)

    decision = evaluate_quote_comparability_candidate(_context(), evidence)

    assert decision.eligible_candidate is False
    assert "외부근거 수량 미확인" in decision.reasons
    assert "외부근거 단위 미확인" in decision.reasons
    assert "상업조건 미확인 6개" in decision.reasons


def test_quantity_and_unit_mismatch_block_candidate() -> None:
    evidence = _evidence(quantity=Decimal("10"), unit="set")

    decision = evaluate_quote_comparability_candidate(_context(), evidence)

    assert decision.eligible_candidate is False
    assert "견적 수량과 외부근거 수량 불일치" in decision.reasons
    assert "견적 단위와 외부근거 단위 불일치" in decision.reasons


def test_non_direct_or_non_ab_evidence_is_rejected() -> None:
    evidence = _evidence(
        match_grade=MatchGrade.C,
        evidence_type=EvidenceType.BUDGET_AMOUNT,
        comparison_scope=ComparisonScope.REFERENCE_ONLY,
    )

    decision = evaluate_quote_comparability_candidate(_context(), evidence)

    assert decision.eligible_candidate is False
    assert "제품 동일성 A/B가 아님" in decision.reasons
    assert "직접가격 Evidence Type이 아님" in decision.reasons
    assert "현재 비교범위가 reference/exclude임" in decision.reasons


def test_evidence_after_quote_date_is_not_used_for_historical_quote() -> None:
    evidence = _evidence(transaction_date=date(2026, 9, 3))

    decision = evaluate_quote_comparability_candidate(_context(), evidence)

    assert decision.eligible_candidate is False
    assert decision.date_gap_days == -2
    assert "외부근거 기준일이 견적일 이후임" in decision.reasons


def test_missing_quote_price_or_date_blocks_candidate() -> None:
    decision = evaluate_quote_comparability_candidate(
        _context(quote_unit_price=None, quote_date=None),
        _evidence(),
    )

    assert decision.eligible_candidate is False
    assert "견적 단가 미확인" in decision.reasons
    assert "견적 기준일 미확인" in decision.reasons
