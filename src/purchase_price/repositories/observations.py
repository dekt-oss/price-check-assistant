from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from purchase_price.models import PriceObservation, Product, RawEvidence
from purchase_price.schemas import CollectedPrice


def get_or_create_price_observation(
    session: Session,
    *,
    product: Product,
    evidence: RawEvidence,
    collected: CollectedPrice,
    derivation_version: str,
) -> tuple[PriceObservation, bool]:
    """Persist one normalized price derivation for one raw evidence record.

    The idempotency key deliberately includes EvidenceType because a future parser may derive more
    than one distinct monetary meaning from the same raw record. A changed derivation contract must
    use a new `derivation_version` rather than silently overwriting a previous normalization.
    """

    version = derivation_version.strip()
    if not version:
        raise ValueError("derivation_version is required")
    if evidence.source_name != collected.source_name:
        raise ValueError("collected price source_name must match raw evidence source_name")

    session.flush()
    existing = session.scalar(
        select(PriceObservation).where(
            PriceObservation.evidence_id == evidence.id,
            PriceObservation.product_id == product.id,
            PriceObservation.derivation_version == version,
            PriceObservation.evidence_type == collected.evidence_type,
        )
    )
    if existing is not None:
        return existing, False

    observation = PriceObservation(
        product=product,
        evidence=evidence,
        derivation_version=version,
        price=collected.price,
        evidence_type=collected.evidence_type,
        currency=collected.currency,
        quantity=collected.quantity,
        unit=collected.unit,
        total_amount=collected.total_amount,
        vat_status=collected.vat_status,
        conditions=collected.conditions,
        comparison_scope=collected.comparison_scope,
        comparison_note=collected.comparison_note,
        source_type=collected.source_type,
        source_name=collected.source_name,
        source_url=collected.source_url,
        source_record_id=collected.source_record_id,
        original_title=collected.original_title,
        collected_at=collected.collected_at,
        transaction_date=collected.transaction_date,
        match_grade=collected.match_grade,
        match_note=collected.match_note,
    )
    session.add(observation)
    session.flush()
    return observation, True
