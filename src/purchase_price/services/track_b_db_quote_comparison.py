from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import exists, or_, select
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
    equivalent_model_keys,
    grade_product_identity,
    parse_g2b_identity,
)


@dataclass(frozen=True)
class TrackBIngestResult:
    inserted: int
    replayed: int
    invalid_rows: int
    conflicts: int


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
    supplier: str | None = None
    demand_institution: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    transaction_type: str = "나라장터 납품요구"


@dataclass(frozen=True)
class TrackBReferenceCandidate:
    source_record_id: str
    product_title: str
    price: Decimal
    reference_reason: str
    raw_object_key: str
    transaction_date: str | None
    supplier: str | None = None
    demand_institution: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    model_name: str | None = None
    transaction_type: str = "나라장터 납품요구"


@dataclass(frozen=True)
class TrackBIdentitySuggestion:
    product_title: str
    manufacturer: str | None
    model_name: str
    transaction_date: str | None
    match_reason: str


@dataclass(frozen=True)
class TrackBQuoteComparison:
    status: str
    candidates: tuple[TrackBQuoteCandidate, ...]
    examined: int
    suggestions: tuple[TrackBIdentitySuggestion, ...] = ()
    reference_candidates: tuple[TrackBReferenceCandidate, ...] = ()


def lookup_track_b_quote(
    query: ProductQuery, *, quote_unit_price: Decimal | None
) -> TrackBQuoteComparison:
    """Prefer the R2-hosted serving index; keep the SQL DB as a development fallback."""
    from purchase_price.services.track_b_r2_quote_index import lookup_track_b_quote_from_r2

    r2_result = lookup_track_b_quote_from_r2(query, quote_unit_price=quote_unit_price)
    if r2_result.status not in {"unavailable", "not_ingested"}:
        return r2_result

    from purchase_price.db import SessionLocal

    try:
        with SessionLocal() as session:
            db_result = compare_track_b_quote(session, query, quote_unit_price=quote_unit_price)
    except SQLAlchemyError:
        return r2_result
    return db_result if db_result.status != "not_ingested" else r2_result


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
        item_sha256=_serving_item_sha256(record),
        identity_conflict=False,
        identity_conflict_count=0,
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
        specification=parsed.specification,
        model_key=normalize_text(parsed.model_name) or None,
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


def _serving_item_sha256(record: NormalizedTrackBRecord) -> str:
    """Fingerprint fields that can affect the DB serving result, excluding raw-only metadata."""
    payload = {
        "detail_code": record.detail_code,
        "detail_name": record.detail_name,
        "product_id": record.product_id,
        "product_name": record.product_name,
        "unit_price": str(record.unit_price) if record.unit_price is not None else None,
        "quantity": str(record.quantity) if record.quantity is not None else None,
        "unit": record.unit,
        "total_amount": str(record.total_amount) if record.total_amount is not None else None,
        "amount_check": record.amount_check.value,
        "supplier": record.supplier,
        "demand_institution": record.demand_institution,
        "transaction_date": (
            record.transaction_date.isoformat() if record.transaction_date is not None else None
        ),
        "contract_delivery_type": record.contract_delivery_type,
        "contract_type": record.contract_type,
        "delivery_condition": record.delivery_condition,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    conflicts = 0
    delivery_request_numbers = {
        record.identity.delivery_request_number for record in result.records
    }
    existing_rows = (
        session.scalars(
            select(TrackBDeliveryLine).where(
                TrackBDeliveryLine.delivery_request_number.in_(delivery_request_numbers)
            )
        ).all()
        if delivery_request_numbers
        else []
    )
    exact_rows = {
        (row.delivery_request_number, row.change_order, row.product_sequence): row
        for row in existing_rows
    }
    numeric_rows = {
        (row.delivery_request_number, row.change_order_number, row.product_sequence): row
        for row in existing_rows
    }
    for record in result.records:
        identity = record.identity
        exact_key = (
            identity.delivery_request_number,
            identity.change_order,
            identity.product_sequence,
        )
        existing = exact_rows.get(exact_key)
        if existing is not None:
            if existing.item_sha256 != _serving_item_sha256(record):
                existing.identity_conflict = True
                existing.identity_conflict_count += 1
                conflicts += 1
            else:
                replayed += 1
            continue
        numeric_key = (
            identity.delivery_request_number,
            int(identity.change_order),
            identity.product_sequence,
        )
        numeric_collision = numeric_rows.get(numeric_key)
        if numeric_collision is not None:
            raise TrackBIdentityConflictError(
                f"change order {identity.change_order} collides with stored"
                f" {numeric_collision.change_order} for {identity.source_record_id}"
            )
        line = _line_from_record(record)
        session.add(line)
        exact_rows[exact_key] = line
        numeric_rows[numeric_key] = line
        inserted += 1
    if inserted or conflicts:
        session.flush()
    return TrackBIngestResult(
        inserted=inserted,
        replayed=replayed,
        invalid_rows=sum(
            issue.code in {"INVALID_ITEM", "INVALID_IDENTITY"} for issue in result.issues
        ),
        conflicts=conflicts,
    )


def _model_edit_distance(left: str, right: str) -> int:
    left_compact = re.sub(r"[^0-9a-z]+", "", left.casefold())
    right_compact = re.sub(r"[^0-9a-z]+", "", right.casefold())
    if left_compact == right_compact:
        return 0
    if abs(len(left_compact) - len(right_compact)) > 1:
        return 2
    previous = list(range(len(right_compact) + 1))
    for row_index, left_char in enumerate(left_compact, start=1):
        current = [row_index]
        for column_index, right_char in enumerate(right_compact, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _suggest_similar_identities(
    session: Session,
    *,
    model_key: str,
    class_key: str,
    current_clause,
    limit: int = 5,
) -> tuple[TrackBIdentitySuggestion, ...]:
    compact_query = re.sub(r"[^0-9a-z]+", "", model_key.casefold())
    if len(compact_query) < 5 or not class_key:
        return ()
    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(
            current_clause,
            TrackBDeliveryLine.class_key == class_key,
            TrackBDeliveryLine.model_key.is_not(None),
            TrackBDeliveryLine.identity_conflict.is_(False),
        )
        .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        .limit(200)
    ).all()
    suggestions: list[TrackBIdentitySuggestion] = []
    seen: set[tuple[str, str | None]] = set()
    for row in rows:
        if not row.model_key or not row.model_name or _model_edit_distance(model_key, row.model_key) != 1:
            continue
        identity_key = (row.model_key, row.manufacturer)
        if identity_key in seen or row.product_title is None:
            continue
        seen.add(identity_key)
        suggestions.append(
            TrackBIdentitySuggestion(
                product_title=row.product_title,
                manufacturer=row.manufacturer,
                model_name=row.model_name,
                transaction_date=(
                    row.transaction_date.isoformat() if row.transaction_date is not None else None
                ),
                match_reason="모델명 편집거리 1 — 식별 확인 필요",
            )
        )
        if len(suggestions) >= limit:
            break
    return tuple(suggestions)


def _reference_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    stop = {"machine", "system", "device", "equipment", "medical"}
    tokens = re.findall(r"[0-9A-Za-z가-힣]{2,}", value)
    normalized: list[str] = []
    for token in tokens:
        key = token.casefold()
        if key in stop:
            continue
        if key not in normalized:
            normalized.append(key)
    return tuple(sorted(normalized, key=len, reverse=True)[:4])


def _reference_reason(
    row: TrackBDeliveryLine,
    *,
    model_key: str,
    class_key: str,
    tokens: tuple[str, ...],
) -> str:
    if model_key and row.model_key == model_key:
        return "동일 모델명 · 제조사/규격 조건 확인 필요"
    if model_key and row.model_key and (model_key in row.model_key or row.model_key in model_key):
        return "유사 모델명 참고"
    if class_key and row.class_key == class_key:
        return "동일 품목명 참고"
    title = (row.product_title or "").casefold()
    matched = next((token for token in tokens if token in title), None)
    return f"품명 키워드 참고 · {matched}" if matched else "검색 참고"


def _find_reference_candidates(
    session: Session,
    *,
    query: ProductQuery,
    model_key: str,
    class_key: str,
    current_clause,
    limit: int = 25,
) -> tuple[TrackBReferenceCandidate, ...]:
    """Return broad observed-price references without promoting them to comparable evidence."""
    conditions = []
    if model_key:
        conditions.append(TrackBDeliveryLine.model_key.like(f"%{model_key}%"))
    if class_key:
        conditions.append(TrackBDeliveryLine.class_key.like(f"%{class_key}%"))
    tokens = _reference_tokens(query.product_name)
    for token in tokens:
        conditions.append(TrackBDeliveryLine.product_title.ilike(f"%{token}%"))
    if not conditions:
        return ()

    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(
            current_clause,
            or_(*conditions),
            TrackBDeliveryLine.unit_price > 0,
            TrackBDeliveryLine.identity_conflict.is_(False),
        )
        .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        .limit(200)
    ).all()

    ranked = sorted(
        rows,
        key=lambda row: (
            0
            if model_key and row.model_key == model_key
            else 1
            if model_key
            and row.model_key
            and (model_key in row.model_key or row.model_key in model_key)
            else 2
            if class_key and row.class_key == class_key
            else 3,
            -(row.transaction_date.toordinal() if row.transaction_date is not None else 0),
            -row.id,
        ),
    )
    references: list[TrackBReferenceCandidate] = []
    seen: set[str] = set()
    for row in ranked:
        if row.unit_price is None or row.product_title is None:
            continue
        source_record_id = (
            f"delivery:{row.delivery_request_number}"
            f"|change:{row.change_order}|line:{row.product_sequence}"
        )
        if source_record_id in seen:
            continue
        seen.add(source_record_id)
        references.append(
            TrackBReferenceCandidate(
                source_record_id=source_record_id,
                product_title=row.product_title,
                price=row.unit_price,
                reference_reason=_reference_reason(
                    row, model_key=model_key, class_key=class_key, tokens=tokens
                ),
                raw_object_key=row.raw_object_key,
                transaction_date=(
                    row.transaction_date.isoformat() if row.transaction_date is not None else None
                ),
                supplier=row.supplier,
                demand_institution=row.demand_institution,
                quantity=row.quantity,
                unit=row.unit,
                model_name=row.model_name,
            )
        )
        if len(references) >= limit:
            break
    return tuple(references)


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
    model_keys = equivalent_model_keys(query.model_name)
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
        TrackBDeliveryLine.model_key.in_(model_keys)
        if model_keys
        else TrackBDeliveryLine.class_key == class_key
    )
    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(
            current,
            identity_filter,
            TrackBDeliveryLine.unit_price > 0,
            TrackBDeliveryLine.identity_conflict.is_(False),
        )
        .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        .limit(limit + 1)
    ).all()
    candidates: list[TrackBQuoteCandidate] = []
    for row in rows[:limit]:
        # Re-parse the immutable G2B source title with the current verified parser at read time.
        # The serving index can outlive parser-rule updates (for example a newly verified origin
        # qualifier), so relying only on persisted derived flags would require a full index rebuild
        # before a safe rule correction can take effect.
        identity = parse_g2b_identity(row.product_title)
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
                supplier=row.supplier,
                demand_institution=row.demand_institution,
                quantity=row.quantity,
                unit=row.unit,
            )
        )
    status = "partial" if len(rows) > limit else "success" if candidates else "success_0"
    if status == "success_0" and session.scalar(select(TrackBDeliveryLine.id).limit(1)) is None:
        status = "not_ingested"
    suggestions = (
        _suggest_similar_identities(
            session,
            model_key=model_key,
            class_key=class_key,
            current_clause=current,
        )
        if status == "success_0" and model_key
        else ()
    )
    references = (
        _find_reference_candidates(
            session,
            query=query,
            model_key=model_key,
            class_key=class_key,
            current_clause=current,
        )
        if status == "success_0"
        else ()
    )
    return TrackBQuoteComparison(
        status=status,
        candidates=tuple(candidates),
        examined=min(len(rows), limit),
        suggestions=suggestions,
        reference_candidates=references,
    )
