from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal

from purchase_price.domain import ComparisonScope
from purchase_price.evidence import payload_sha256
from purchase_price.schemas import CollectedPrice
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)


@dataclass(frozen=True)
class QuoteComparableApproval:
    """Explicit reviewer approval for one quote/evidence pair in the current review session.

    This object is deliberately not a property of the public source record. A public price can be
    comparable to one quote and not comparable to another because quantity, unit, commercial
    conditions and review date differ.
    """

    pair_key: str
    source_name: str
    source_record_id: str | None
    source_url: str | None
    approved_at: datetime
    quote_date: date | None
    evidence_basis_date: date | None
    confirmed_condition_labels: tuple[str, ...]
    reviewer_note: str

    @property
    def short_key(self) -> str:
        return self.pair_key[:12]


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def quote_evidence_pair_key(
    context: QuoteComparabilityContext,
    evidence: CollectedPrice,
) -> str:
    """Fingerprint the exact quote/evidence pair so stale approvals cannot be reused.

    The fingerprint is intended for current-session identity, not public persistence. Any change to
    quote price, quantity, unit, date, six commercial-condition values, or the relevant evidence
    fields produces a different key.
    """

    payload = {
        "quote": {
            "unit_price": _decimal_text(context.quote_unit_price),
            "quantity": _decimal_text(context.quantity),
            "unit": context.unit.strip(),
            "quote_date": context.quote_date.isoformat() if context.quote_date else None,
            "conditions": {
                "vat": context.conditions.vat,
                "delivery": context.conditions.delivery,
                "installation": context.conditions.installation,
                "options": context.conditions.options,
                "warranty": context.conditions.warranty,
                "maintenance": context.conditions.maintenance,
            },
        },
        "evidence": {
            "source_type": evidence.source_type.value,
            "source_name": evidence.source_name,
            "source_record_id": evidence.source_record_id,
            "source_url": evidence.source_url,
            "manufacturer": evidence.manufacturer,
            "product_name": evidence.product_name,
            "model_name": evidence.model_name,
            "specification": evidence.specification,
            "price": _decimal_text(evidence.price),
            "currency": evidence.currency,
            "evidence_type": evidence.evidence_type.value,
            "match_grade": evidence.match_grade.value,
            "quantity": _decimal_text(evidence.quantity),
            "unit": evidence.unit,
            "transaction_date": (
                evidence.transaction_date.isoformat() if evidence.transaction_date else None
            ),
            "collected_at": evidence.collected_at.isoformat(),
            "vat_status": evidence.vat_status,
            "conditions": evidence.conditions,
            "comparison_scope": evidence.comparison_scope.value,
        },
    }
    return payload_sha256(payload)


def create_quote_comparable_approval(
    context: QuoteComparabilityContext,
    evidence: CollectedPrice,
    *,
    reviewer_confirmed: bool,
    reviewer_note: str = "",
    approved_at: datetime | None = None,
) -> QuoteComparableApproval:
    """Create an explicit approval only after the conservative candidate gate passes."""

    decision = evaluate_quote_comparability_candidate(context, evidence)
    if not decision.eligible_candidate:
        raise ValueError(f"quote_comparable 후보가 아님: {decision.reason_text}")
    if not reviewer_confirmed:
        raise ValueError("담당자 원문·조건 확인이 명시적으로 승인되지 않음")

    confirmed_labels = tuple(
        item.label for item in decision.condition_comparison.comparisons if item.status.value == "일치"
    )
    timestamp = approved_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    return QuoteComparableApproval(
        pair_key=quote_evidence_pair_key(context, evidence),
        source_name=evidence.source_name,
        source_record_id=evidence.source_record_id,
        source_url=evidence.source_url,
        approved_at=timestamp,
        quote_date=context.quote_date,
        evidence_basis_date=decision.evidence_basis_date,
        confirmed_condition_labels=confirmed_labels,
        reviewer_note=reviewer_note.strip(),
    )


def apply_quote_comparable_approval(
    context: QuoteComparabilityContext,
    evidence: CollectedPrice,
    approval: QuoteComparableApproval,
) -> CollectedPrice:
    """Return a current-review copy promoted to QUOTE_COMPARABLE.

    The original frozen `CollectedPrice` is never mutated. The approval must match the exact current
    quote/evidence pair and the pair must still pass the candidate gate when applied.
    """

    current_key = quote_evidence_pair_key(context, evidence)
    if approval.pair_key != current_key:
        raise ValueError("현재 견적·근거 pair와 승인기록이 일치하지 않음")

    decision = evaluate_quote_comparability_candidate(context, evidence)
    if not decision.eligible_candidate:
        raise ValueError(f"현재 pair가 더 이상 quote_comparable 후보가 아님: {decision.reason_text}")

    approval_note = (
        "현재 검토 session의 quote/evidence pair에 대해 담당자가 원문·조건을 확인하고 "
        f"명시적으로 승인함; approval={approval.short_key}; "
        f"approved_at={approval.approved_at.isoformat()}"
    )
    if approval.reviewer_note:
        approval_note += f"; reviewer_note={approval.reviewer_note}"

    existing_note = (evidence.comparison_note or "").strip()
    combined_note = f"{existing_note} / {approval_note}" if existing_note else approval_note
    return replace(
        evidence,
        comparison_scope=ComparisonScope.QUOTE_COMPARABLE,
        comparison_note=combined_note,
    )
