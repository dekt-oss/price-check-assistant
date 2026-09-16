from __future__ import annotations

from decimal import Decimal

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from purchase_price.domain import MatchGrade
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteCandidate,
    TrackBQuoteComparison,
)


def add_same_class_reference_prices(
    session: Session,
    query: ProductQuery,
    comparison: TrackBQuoteComparison,
    *,
    limit: int = 20,
) -> TrackBQuoteComparison:
    """Broaden a zero exact-model result with reference-only same-class prices.

    This path is intentionally separate from identity grading. It runs only after the strict
    comparison returned zero candidates for a model-specific query, requires an exact normalized
    product-class match, excludes the requested model, and emits grade C rows with no quote delta.
    These rows are market context only and must never enter the automatic fair-price verdict.
    """

    if comparison.status != "success_0":
        return comparison
    if limit < 1 or limit > 100:
        raise ValueError("reference limit must be between 1 and 100")

    model_key = normalize_text(query.model_name)
    class_key = normalize_text(query.product_name)
    if not model_key or not class_key:
        return comparison

    newer = aliased(TrackBDeliveryLine)
    current = ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )
    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(
            current,
            TrackBDeliveryLine.class_key == class_key,
            TrackBDeliveryLine.unit_price > 0,
            TrackBDeliveryLine.identity_conflict.is_(False),
            or_(
                TrackBDeliveryLine.model_key.is_(None),
                TrackBDeliveryLine.model_key != model_key,
            ),
        )
        .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        .limit(limit)
    ).all()
    if not rows:
        return comparison

    references: list[TrackBQuoteCandidate] = []
    for row in rows:
        if row.unit_price is None or row.product_title is None:
            continue
        references.append(
            TrackBQuoteCandidate(
                source_record_id=(
                    f"delivery:{row.delivery_request_number}"
                    f"|change:{row.change_order}|line:{row.product_sequence}"
                ),
                product_title=row.product_title,
                price=Decimal(row.unit_price),
                match_grade=MatchGrade.C,
                match_note=(
                    "reference-only same product class; requested model is different or missing; "
                    "not eligible for direct quote comparison"
                ),
                delta_percent=None,
                raw_object_key=row.raw_object_key,
                amount_check=row.amount_check,
                transaction_date=(
                    row.transaction_date.isoformat() if row.transaction_date is not None else None
                ),
            )
        )

    if not references:
        return comparison
    return TrackBQuoteComparison(
        status="reference",
        candidates=tuple(references),
        examined=comparison.examined + len(rows),
        suggestions=comparison.suggestions,
    )
