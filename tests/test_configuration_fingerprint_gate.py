from datetime import date
from decimal import Decimal

import pytest

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_comparable_approval import (
    apply_quote_comparable_approval,
    create_quote_comparable_approval,
    quote_evidence_pair_key,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile


def _conditions(*, options: str = "Desflurane", warranty: str = "3년"):
    return build_quote_condition_profile(
        vat="VAT 포함",
        delivery="무료",
        installation="설치 포함",
        options=options,
        warranty=warranty,
        maintenance="별도",
    )


def _identity(**overrides: str) -> ProductQuery:
    values = {
        "product_name": "가스마취기",
        "manufacturer": "Maquet",
        "model_name": "FLOW-C",
        "specification": "FLOW-C console",
    }
    values.update(overrides)
    return ProductQuery(**values)


def _context(**overrides: object) -> QuoteComparabilityContext:
    values: dict[str, object] = {
        "quote_unit_price": Decimal("67000000"),
        "quantity": Decimal("1"),
        "unit": "set",
        "quote_date": date(2026, 9, 1),
        "conditions": _conditions(),
        "quote_identity": _identity(),
    }
    values.update(overrides)
    return QuoteComparabilityContext(**values)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> CollectedPrice:
    values: dict[str, object] = {
        "manufacturer": "Maquet",
        "product_name": "가스마취기",
        "model_name": "FLOW-C",
        "specification": "FLOW-C console",
        "price": Decimal("66000000"),
        "evidence_type": EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        "source_type": SourceType.PROCUREMENT,
        "source_name": "나라장터",
        "source_url": "https://example.invalid/evidence",
        "source_record_id": "FLOW-C-001",
        "collected_at": date(2026, 9, 1),
        "transaction_date": date(2026, 8, 30),
        "quantity": Decimal("1"),
        "unit": "set",
        "currency": "KRW",
        "vat_status": "포함",
        "conditions": "배송비=무료; 설치비=포함; 옵션=Desflurane; 보증기간=3년; 유지보수=별도계약",
        "match_grade": MatchGrade.A,
        "comparison_scope": ComparisonScope.OBSERVED_ONLY,
    }
    values.update(overrides)
    return CollectedPrice(**values)  # type: ignore[arg-type]


def test_identity_aware_context_keeps_matching_flow_c_candidate() -> None:
    decision = evaluate_quote_comparability_candidate(_context(), _evidence())

    assert decision.eligible_candidate is True
    assert decision.configuration_comparison is not None
    assert decision.configuration_comparison.axis("model").status.value == "일치"


def test_flow_c20_cannot_be_promoted_even_if_upstream_grade_is_b() -> None:
    decision = evaluate_quote_comparability_candidate(
        _context(),
        _evidence(model_name="FLOW-C20", match_grade=MatchGrade.B),
    )

    assert decision.eligible_candidate is False
    assert "모델 충돌" in decision.reasons


def test_missing_public_spec_blocks_quote_position_when_quote_spec_is_explicit() -> None:
    decision = evaluate_quote_comparability_candidate(
        _context(quote_identity=_identity(specification="FLOW-C Desflurane vaporizer")),
        _evidence(specification="", match_grade=MatchGrade.B),
    )

    assert decision.eligible_candidate is False
    assert "핵심 규격·구성 미확인" in decision.reasons


def test_legacy_context_without_identity_preserves_existing_gate_contract() -> None:
    decision = evaluate_quote_comparability_candidate(
        _context(quote_identity=None),
        _evidence(specification="", match_grade=MatchGrade.B),
    )

    assert decision.eligible_candidate is True


def test_semantic_option_and_warranty_conflicts_remain_blocking() -> None:
    decision = evaluate_quote_comparability_candidate(
        _context(conditions=_conditions(options="Desflurane", warranty="3년")),
        _evidence(
            conditions="배송비=무료; 설치비=포함; 옵션=Sevoflurane; 보증기간=1년; 유지보수=별도계약"
        ),
    )

    assert decision.eligible_candidate is False
    assert "상업조건 충돌 2개" in decision.reasons


def test_quote_identity_changes_pair_key_and_invalidates_existing_approval() -> None:
    context = _context()
    evidence = _evidence()
    approval = create_quote_comparable_approval(
        context,
        evidence,
        reviewer_confirmed=True,
        reviewer_note="원문 대조",
    )
    changed = _context(quote_identity=_identity(specification="FLOW-C console rev.B"))

    assert quote_evidence_pair_key(changed, evidence) != approval.pair_key
    with pytest.raises(ValueError, match="승인기록이 일치하지 않음"):
        apply_quote_comparable_approval(changed, evidence, approval)
