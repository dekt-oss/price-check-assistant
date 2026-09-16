from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import (
    G2BMappingError,
    resolve_verified_g2b_mapping,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteComparison,
    TrackBReferenceCandidate,
)

_GENERIC_TOKENS = {
    "machine",
    "system",
    "device",
    "equipment",
    "medical",
    "set",
    "장비",
    "기기",
    "시스템",
    "장치",
    "세트",
}
_ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def _current_clause():
    newer = aliased(TrackBDeliveryLine)
    return ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )


def _base_query(current_clause):
    return select(TrackBDeliveryLine).where(
        current_clause,
        TrackBDeliveryLine.unit_price > 0,
        TrackBDeliveryLine.identity_conflict.is_(False),
    )


def _recent_rows(session: Session, statement, *, scan_limit: int = 200) -> list[TrackBDeliveryLine]:
    return list(
        session.scalars(
            statement.order_by(
                TrackBDeliveryLine.transaction_date.desc(),
                TrackBDeliveryLine.id.desc(),
            ).limit(scan_limit)
        ).all()
    )


def _strict_product_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    tokens: list[str] = []
    for raw in re.findall(r"[0-9A-Za-z가-힣]{2,}", value):
        token = raw.casefold()
        if token in _GENERIC_TOKENS or token in _ROMAN_NUMERALS:
            continue
        if token.isascii() and len(token) < 3:
            continue
        if token not in tokens:
            tokens.append(token)
    ranked = sorted(tokens, key=lambda token: (-len(token), token))
    if not ranked:
        return ()
    if len(ranked) == 1 and len(ranked[0]) < 4:
        return ()
    return tuple(ranked[:2])


def _source_record_id(row: TrackBDeliveryLine) -> str:
    return (
        f"delivery:{row.delivery_request_number}"
        f"|change:{row.change_order}|line:{row.product_sequence}"
    )


def _to_references(
    rows: Iterable[TrackBDeliveryLine],
    *,
    reason: str,
    limit: int,
) -> tuple[TrackBReferenceCandidate, ...]:
    references: list[TrackBReferenceCandidate] = []
    seen: set[str] = set()
    for row in rows:
        if row.unit_price is None or row.product_title is None:
            continue
        record_id = _source_record_id(row)
        if record_id in seen:
            continue
        seen.add(record_id)
        references.append(
            TrackBReferenceCandidate(
                source_record_id=record_id,
                product_title=row.product_title,
                price=row.unit_price,
                reference_reason=reason,
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


def _verified_classification_references(
    session: Session,
    query: ProductQuery,
    *,
    current_clause,
    limit: int,
) -> tuple[TrackBReferenceCandidate, ...]:
    try:
        mapping = resolve_verified_g2b_mapping(query)
    except G2BMappingError:
        return ()
    if mapping is None or not mapping.detail_product_code:
        return ()
    rows = _recent_rows(
        session,
        _base_query(current_clause).where(
            TrackBDeliveryLine.detail_code == mapping.detail_product_code
        ),
    )
    if not rows:
        return ()
    reason = (
        "검증된 나라장터 세부품명코드 참고 · "
        f"{mapping.detail_product_code} · {mapping.detail_product_name or '세부품명 미확인'}"
    )
    return _to_references(rows, reason=reason, limit=limit)


def _strong_model_references(
    session: Session,
    query: ProductQuery,
    *,
    current_clause,
    limit: int,
) -> tuple[TrackBReferenceCandidate, ...]:
    model_key = normalize_text(query.model_name)
    raw_model = (query.model_name or "").strip()
    if not model_key or len(model_key) < 4:
        return ()

    conditions = [TrackBDeliveryLine.model_key == model_key]
    if raw_model:
        conditions.append(TrackBDeliveryLine.product_title.ilike(f"%{raw_model}%"))
    if len(model_key) >= 5:
        conditions.append(TrackBDeliveryLine.model_key.like(f"%{model_key}%"))

    rows = _recent_rows(
        session,
        _base_query(current_clause).where(or_(*conditions)),
    )
    if not rows:
        return ()
    return _to_references(
        rows,
        reason="모델명 포함 거래 참고 · 제조사/규격 직접 동일성 미검증",
        limit=limit,
    )


def _strict_product_references(
    session: Session,
    query: ProductQuery,
    *,
    current_clause,
    limit: int,
) -> tuple[TrackBReferenceCandidate, ...]:
    class_key = normalize_text(query.product_name)
    if class_key:
        exact_rows = _recent_rows(
            session,
            _base_query(current_clause).where(TrackBDeliveryLine.class_key == class_key),
        )
        if exact_rows:
            return _to_references(exact_rows, reason="동일 품목명 참고", limit=limit)

    tokens = _strict_product_tokens(query.product_name)
    if not tokens:
        return ()
    token_clause = and_(
        *(TrackBDeliveryLine.product_title.ilike(f"%{token}%") for token in tokens)
    )
    rows = _recent_rows(
        session,
        _base_query(current_clause).where(token_clause),
    )
    if not rows:
        return ()
    return _to_references(
        rows,
        reason="품명 강일치 참고 · " + " + ".join(tokens),
        limit=limit,
    )


def refine_track_b_reference_quality(
    session: Session,
    query: ProductQuery,
    result: TrackBQuoteComparison,
    *,
    limit: int = 25,
) -> TrackBQuoteComparison:
    """Replace permissive zero-match references with fail-closed, relevance-first evidence.

    This function never creates or upgrades A/B/C candidates. It only changes the Research-only
    reference list returned after strict matching produced zero comparable candidates.
    """
    if result.status != "success_0" or result.candidates:
        return result

    current = _current_clause()
    references = _verified_classification_references(
        session,
        query,
        current_clause=current,
        limit=limit,
    )
    if not references:
        references = _strong_model_references(
            session,
            query,
            current_clause=current,
            limit=limit,
        )
    if not references:
        references = _strict_product_references(
            session,
            query,
            current_clause=current,
            limit=limit,
        )

    return TrackBQuoteComparison(
        status=result.status,
        candidates=result.candidates,
        examined=result.examined,
        suggestions=result.suggestions,
        reference_candidates=references,
    )
