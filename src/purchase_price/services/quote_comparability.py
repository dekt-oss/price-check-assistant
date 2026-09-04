from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from purchase_price.domain import (
    DIRECT_PRICE_EVIDENCE_TYPES,
    ComparisonScope,
    MatchGrade,
)
from purchase_price.schemas import CollectedPrice
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.quote_condition_comparison import (
    QuoteConditionProfile,
    QuoteEvidenceConditionComparison,
    compare_quote_to_evidence_conditions,
)

SUPPORTED_CURRENCY = "KRW"
_ALLOWED_INPUT_SCOPES = frozenset(
    {ComparisonScope.OBSERVED_ONLY, ComparisonScope.QUOTE_COMPARABLE}
)


@dataclass(frozen=True)
class QuoteComparabilityContext:
    quote_unit_price: Decimal | None
    quantity: Decimal | None
    unit: str
    quote_date: date | None
    conditions: QuoteConditionProfile


@dataclass(frozen=True)
class QuoteComparabilityDecision:
    eligible_candidate: bool
    reasons: tuple[str, ...]
    condition_comparison: QuoteEvidenceConditionComparison
    evidence_basis_date: date | None
    date_gap_days: int | None

    @property
    def status_label(self) -> str:
        return "비교가능 후보" if self.eligible_candidate else "비교 보류"

    @property
    def reason_text(self) -> str:
        return " / ".join(self.reasons) if self.reasons else "필수 비교조건을 모두 확인함"


def _normalize_unit(value: str | None) -> str:
    return re.sub(r"[\s._/-]+", "", (value or "").strip().casefold())


def _valid_positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def _evidence_basis_date(evidence: CollectedPrice) -> date | None:
    return evidence.transaction_date or evidence.collected_at


def evaluate_quote_comparability_candidate(
    context: QuoteComparabilityContext,
    evidence: CollectedPrice,
) -> QuoteComparabilityDecision:
    """Evaluate whether one evidence row is safe enough to *consider* for quote comparison.

    Passing this gate does not mutate `comparison_scope`. Promotion to `QUOTE_COMPARABLE` remains
    an explicit downstream action so this helper cannot silently change the price-assessment
    contract.
    """

    reasons: list[str] = []

    if evidence.match_grade not in {MatchGrade.A, MatchGrade.B}:
        reasons.append("제품 동일성 A/B가 아님")
    if evidence.evidence_type not in DIRECT_PRICE_EVIDENCE_TYPES:
        reasons.append("직접가격 Evidence Type이 아님")
    if evidence.currency.strip().upper() != SUPPORTED_CURRENCY:
        reasons.append("KRW 가격근거가 아님")
    if evidence.comparison_scope not in _ALLOWED_INPUT_SCOPES:
        reasons.append("현재 비교범위가 reference/exclude임")
    if not _valid_positive(context.quote_unit_price):
        reasons.append("견적 단가 미확인")
    if not _valid_positive(evidence.price):
        reasons.append("외부 단가가 유효하지 않음")

    if context.quantity is None:
        reasons.append("견적 수량 미확인")
    elif evidence.quantity is None:
        reasons.append("외부근거 수량 미확인")
    elif context.quantity != evidence.quantity:
        reasons.append("견적 수량과 외부근거 수량 불일치")

    quote_unit = _normalize_unit(context.unit)
    evidence_unit = _normalize_unit(evidence.unit)
    if not quote_unit:
        reasons.append("견적 단위 미확인")
    elif not evidence_unit:
        reasons.append("외부근거 단위 미확인")
    elif quote_unit != evidence_unit:
        reasons.append("견적 단위와 외부근거 단위 불일치")

    condition_comparison = compare_quote_to_evidence_conditions(
        context.conditions,
        build_price_condition_profile(evidence),
    )
    if condition_comparison.conflict_count:
        reasons.append(f"상업조건 충돌 {condition_comparison.conflict_count}개")
    if condition_comparison.unknown_count:
        reasons.append(f"상업조건 미확인 {condition_comparison.unknown_count}개")

    basis_date = _evidence_basis_date(evidence)
    date_gap_days: int | None = None
    if context.quote_date is None:
        reasons.append("견적 기준일 미확인")
    if basis_date is None:
        reasons.append("외부근거 기준일 미확인")
    if context.quote_date is not None and basis_date is not None:
        date_gap_days = (context.quote_date - basis_date).days
        if date_gap_days < 0:
            reasons.append("외부근거 기준일이 견적일 이후임")

    deduped_reasons = tuple(dict.fromkeys(reasons))
    return QuoteComparabilityDecision(
        eligible_candidate=not deduped_reasons,
        reasons=deduped_reasons,
        condition_comparison=condition_comparison,
        evidence_basis_date=basis_date,
        date_gap_days=date_gap_days,
    )
