from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from purchase_price.domain import MatchGrade
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_track_b_normalization import (
    NormalizedTrackBRecord,
    TrackBIdentityConflictError,
    TrackBNormalizationError,
    TrackBRawPage,
    normalize_track_b_page,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import (
    ProductIdentity,
    grade_product_identity,
    parse_g2b_identity,
)


@dataclass(frozen=True)
class TrackBIngestResult:
    inserted: int
    replayed: int
    invalid_rows: int


@dataclass(frozen=True)
class TrackBQuoteCandidate:
    source_record_id: str
    product_title: str
    price: Decimal
    match_grade: MatchGrade
    match_note: str
    delta_percent: Decimal | None
    raw_object_key: str
    amount_check: str
    transaction_date: str | None


@dataclass(frozen=True)
class TrackBQuoteComparison:
    status: str
    candidates: tuple[TrackBQuoteCandidate, ...]
    examined: int


def lookup_track_b_quote(
    query: ProductQuery, *, quote_unit_price: Decimal | None
) -> TrackBQuoteComparison:
    """UI adapter: a missing or offline DB is distinct from a successful zero-result search."""
    from purchase_price.db import SessionLocal

    try:
        with SessionLocal() as session:
            return compare_track_b_quote(session, query, quote_unit_price=quote_unit_price)
    except SQLAlchemyError:
        return TrackBQuoteComparison("unavailable", (), 0)


def _line_from_record(record: NormalizedTrackBRecord) -> TrackBDeliveryLine:
    change_order = record.identity.change_order
    if not change_order.isdigit():
        raise TrackBNormalizationError(
            "Track B change order must be numeric for current projection"
        )
    if not record.provenance.raw_object_key or not record.provenance.raw_payload_sha256:
        raise TrackBNormalizationError("R2 raw key and hash are required for DB serving")
    parsed = parse_g2b_identity(record.product_name)
    return TrackBDeliveryLine(
        delivery_request_number=record.identity.delivery_request_number,
        change_order=change_order,
        change_order_number=int(change_order),
        product_sequence=record.identity.product_sequence,
        item_sha256=record.item_sha256,
        raw_object_key=record.provenance.raw_object_key,
        raw_payload_sha256=record.provenance.raw_payload_sha256,
        detail_code=record.detail_code,
        product_id=record.product_id,
        product_title=record.product_name,
        product_class=parsed.product_name,
        class_key=normalize_text(parsed.product_name) or None,
        manufacturer=parsed.manufacturer,
        manufacturer_qualifier=parsed.manufacturer_qualifier,
        model_name=parsed.model_name,
        model_qualifier=parsed.model_qualifier,
        model_qualifier_verified_as_origin=parsed.model_qualifier_verified_as_origin,
        model_key=normalize_text(parsed.model_name) or None,
        specification=parsed.specification,
        unit_price=record.unit_price,
        quantity=record.quantity,
        unit=record.unit,
        total_amount=record.total_amount,
        amount_check=record.amount_check.value,
        transaction_date=record.transaction_date,
        supplier=record.supplier,
        demand_institution=record.demand_institution,
        api_params_json=json.dumps(dict(record.provenance.api_params), sort_keys=True),
    )


def ingest_track_b_page(session: Session, page: TrackBRawPage) -> TrackBIngestResult:
    """Persist an R2-verified page; caller owns the transaction boundary."""
    result = normalize_track_b_page(
        page.payload,
        raw_object_key=page.raw_object_key,
        raw_payload_sha256=page.raw_payload_sha256,
        fetched_at=page.fetched_at,
    )
    if any(issue.code == "IDENTITY_CONFLICT" for issue in result.issues):
        raise TrackBIdentityConflictError("Track B page has divergent stable identity payloads")
    inserted = 0
    replayed = result.duplicate_count
    for record in result.records:
        identity = record.identity
        existing = session.scalar(
            select(TrackBDeliveryLine).where(
                TrackBDeliveryLine.delivery_request_number == identity.delivery_request_number,
                TrackBDeliveryLine.change_order == identity.change_order,
                TrackBDeliveryLine.product_sequence == identity.product_sequence,
            )
        )
        if existing is not None:
            if existing.item_sha256 != record.item_sha256:
                raise TrackBIdentityConflictError(
                    f"stable identity {identity.source_record_id} has divergent payloads"
                )
            replayed += 1
            continue
        numeric_collision = session.scalar(
            select(TrackBDeliveryLine).where(
                TrackBDeliveryLine.delivery_request_number == identity.delivery_request_number,
                TrackBDeliveryLine.change_order_number == int(identity.change_order),
                TrackBDeliveryLine.product_sequence == identity.product_sequence,
            )
        )
        if numeric_collision is not None:
            raise TrackBIdentityConflictError(
                f"change order {identity.change_order} collides with stored"
                f" {numeric_collision.change_order} for {identity.source_record_id}"
            )
        session.add(_line_from_record(record))
        session.flush()
        inserted += 1
    return TrackBIngestResult(
        inserted=inserted,
        replayed=replayed,
        invalid_rows=sum(
            issue.code in {"INVALID_ITEM", "INVALID_IDENTITY"} for issue in result.issues
        ),
    )


def compare_track_b_quote(
    session: Session,
    query: ProductQuery,
    *,
    quote_unit_price: Decimal | None,
    limit: int = 50,
) -> TrackBQuoteComparison:
    """Read current Track B lines as observed Research, never as an automatic fair-price verdict."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    model_key = normalize_text(query.model_name)
    class_key = normalize_text(query.product_name)
    if not model_key and not class_key:
        return TrackBQuoteComparison("insufficient_identity", (), 0)
    newer = aliased(TrackBDeliveryLine)
    current = ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )
    identity_filter = (
        TrackBDeliveryLine.model_key == model_key
        if model_key
        else TrackBDeliveryLine.class_key == class_key
    )
    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(current, identity_filter, TrackBDeliveryLine.unit_price > 0)
        .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        .limit(limit + 1)
    ).all()
    candidates: list[TrackBQuoteCandidate] = []
    for row in rows[:limit]:
        identity = ProductIdentity(
            product_name=row.product_class,
            manufacturer=row.manufacturer,
            manufacturer_qualifier=row.manufacturer_qualifier,
            model_name=row.model_name,
            model_qualifier=row.model_qualifier,
            model_qualifier_verified_as_origin=row.model_qualifier_verified_as_origin,
            specification=row.specification,
            source_title=row.product_title,
        )
        decision = grade_product_identity(query, identity)
        if decision.grade not in {MatchGrade.A, MatchGrade.B, MatchGrade.C}:
            continue
        if row.unit_price is None or row.product_title is None:
            continue
        delta = None
        if (
            decision.grade in {MatchGrade.A, MatchGrade.B}
            and quote_unit_price is not None
            and quote_unit_price > 0
        ):
            delta = ((quote_unit_price - row.unit_price) / row.unit_price * 100).quantize(
                Decimal("0.1")
            )
        candidates.append(
            TrackBQuoteCandidate(
                source_record_id=(
                    f"delivery:{row.delivery_request_number}"
                    f"|change:{row.change_order}|line:{row.product_sequence}"
                ),
                product_title=row.product_title,
                price=row.unit_price,
                match_grade=decision.grade,
                match_note=decision.note,
                delta_percent=delta,
                raw_object_key=row.raw_object_key,
                amount_check=row.amount_check,
                transaction_date=(
                    row.transaction_date.isoformat() if row.transaction_date is not None else None
                ),
            )
        )
    status = "partial" if len(rows) > limit else "success" if candidates else "success_0"
    if status == "success_0" and session.scalar(select(TrackBDeliveryLine.id).limit(1)) is None:
        status = "not_ingested"
    return TrackBQuoteComparison(
        status=status,
        candidates=tuple(candidates),
        examined=min(len(rows), limit),
    )
