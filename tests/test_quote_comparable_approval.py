from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_comparability import QuoteComparabilityContext
from purchase_price.services.quote_comparable_approval import (
    apply_quote_comparable_approval,
    create_quote_comparable_approval,
    quote_evidence_pair_key,
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
        "conditions": "배송비=무료; 설치비=포함; 옵션=기본구성; 보증기간=2년; 유지보수=별도계약",
        "source_record_id": "G2B-001",
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


def test_explicit_confirmation_is_required_even_for_candidate() -> None:
    with pytest.raises(ValueError, match="명시적으로 승인"):
        create_quote_comparable_approval(
            _context(),
            _evidence(),
            reviewer_confirmed=False,
        )


def test_non_candidate_cannot_be_human_overridden_by_this_workflow() -> None:
    with pytest.raises(ValueError, match="후보가 아님"):
        create_quote_comparable_approval(
            _context(),
            _evidence(quantity=Decimal("10")),
            reviewer_confirmed=True,
        )


def test_approval_is_pair_specific_and_records_review_basis() -> None:
    approved_at = datetime(2026, 9, 4, 14, 0, tzinfo=UTC)
    context = _context()
    evidence = _evidence()

    approval = create_quote_comparable_approval(
        context,
        evidence,
        reviewer_confirmed=True,
        reviewer_note="계약 상세 원문과 견적 원문 대조",
        approved_at=approved_at,
    )

    assert approval.pair_key == quote_evidence_pair_key(context, evidence)
    assert approval.source_record_id == "G2B-001"
    assert approval.approved_at == approved_at
    assert approval.quote_date == date(2026, 9, 1)
    assert approval.evidence_basis_date == date(2026, 8, 30)
    assert approval.confirmed_condition_labels == (
        "VAT",
        "배송",
        "설치",
        "옵션",
        "보증",
        "유지보수",
    )
    assert approval.reviewer_note == "계약 상세 원문과 견적 원문 대조"


def test_pair_key_changes_when_quote_or_evidence_changes() -> None:
    context = _context()
    evidence = _evidence()
    original = quote_evidence_pair_key(context, evidence)

    assert quote_evidence_pair_key(_context(quote_unit_price=Decimal("12600000")), evidence) != original
    assert quote_evidence_pair_key(_context(quantity=Decimal("2")), evidence) != original
    assert quote_evidence_pair_key(context, _evidence(price=Decimal("12100000"))) != original


def test_apply_returns_session_copy_and_does_not_mutate_public_source() -> None:
    context = _context()
    evidence = _evidence()
    approval = create_quote_comparable_approval(
        context,
        evidence,
        reviewer_confirmed=True,
        approved_at=datetime(2026, 9, 4, 14, 0, tzinfo=UTC),
    )

    promoted = apply_quote_comparable_approval(context, evidence, approval)

    assert evidence.comparison_scope == ComparisonScope.OBSERVED_ONLY
    assert promoted is not evidence
    assert promoted.comparison_scope == ComparisonScope.QUOTE_COMPARABLE
    assert "담당자가 원문·조건을 확인" in (promoted.comparison_note or "")
    assert approval.short_key in (promoted.comparison_note or "")


def test_stale_approval_cannot_be_reused_after_quote_change() -> None:
    context = _context()
    evidence = _evidence()
    approval = create_quote_comparable_approval(
        context,
        evidence,
        reviewer_confirmed=True,
    )

    with pytest.raises(ValueError, match="승인기록이 일치하지 않음"):
        apply_quote_comparable_approval(
            _context(quote_unit_price=Decimal("13000000")),
            evidence,
            approval,
        )


def test_only_approved_pair_unlocks_quote_position() -> None:
    context = _context()
    evidence = _evidence()

    before = assess_prices([evidence], context.quote_unit_price)
    assert before.quote_position is None

    approval = create_quote_comparable_approval(
        context,
        evidence,
        reviewer_confirmed=True,
    )
    promoted = apply_quote_comparable_approval(context, evidence, approval)
    after = assess_prices([promoted], context.quote_unit_price)

    assert after.quote_comparable_count == 1
    assert after.quote_position == "상단 초과"
    assert after.difference_rate is not None
