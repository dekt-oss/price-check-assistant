"""Direct 나라장터 delivery lines supplied by one company, matched by name only.

Used by the company-centric search result. The serving index stores the supplier name but not
its 사업자등록번호, so matching is "same name after removing legal-form markers"
(company_core_key: "(주)나눔테크" == "나눔테크"). Callers must present this as a name match, not
a confirmed identity. Only the latest change order of each line counts, and lines cancelled by
a change order (final quantity 0) are excluded, as in the direct-price comparison.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from purchase_price.models import TrackBDeliveryLine
from purchase_price.services import track_b_search_index as search_index
from purchase_price.services.mfds_business_license_view import company_core_key

_LEGAL_FORMS = ("주식회사", "(주)", "㈜", "(유)", "유한회사", "(재)", "재단법인")
CANDIDATE_LIMIT = 20000


def _search_text(company_name: str) -> str:
    text = company_name
    for marker in _LEGAL_FORMS:
        text = text.replace(marker, " ")
    return " ".join(text.split())


def supplier_trade_summary(session: Session | None, company_name: str) -> dict[str, Any]:
    core = company_core_key(company_name)
    needle = _search_text(company_name)
    if session is None or not core or len(needle) < 2:
        return {"status": "not_applicable", "trade_count": 0}
    newer = aliased(TrackBDeliveryLine)
    current = ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )
    try:
        # A substring LIKE cannot use a B-tree index; the side index narrows the rows read
        # and keeps the full scan's row order (by id), so the 20000-row cut is unchanged.
        rows = search_index.matching_rows(
            session,
            select(
                TrackBDeliveryLine.supplier,
                TrackBDeliveryLine.model_name,
                TrackBDeliveryLine.demand_institution,
                TrackBDeliveryLine.transaction_date,
            ).where(
                current,
                TrackBDeliveryLine.supplier.like(f"%{needle}%"),
                TrackBDeliveryLine.identity_conflict.is_(False),
                or_(TrackBDeliveryLine.quantity.is_(None), TrackBDeliveryLine.quantity != 0),
                or_(
                    TrackBDeliveryLine.unit_price > 0,
                    and_(TrackBDeliveryLine.total_amount > 0, TrackBDeliveryLine.quantity > 0),
                ),
            ),
            search_index.Contains("supplier", needle),
            limit=CANDIDATE_LIMIT,
            order="id",
            scalars=False,
        )
    except Exception:  # optional section; never break the search
        return {"status": "unavailable", "trade_count": 0}

    matched = [row for row in rows if company_core_key(row.supplier) == core]
    models = Counter(str(row.model_name or "").strip() for row in matched if str(row.model_name or "").strip())
    dates = [row.transaction_date for row in matched if row.transaction_date is not None]
    return {
        "status": "success" if matched else "success_0",
        "trade_count": len(matched),
        "matched_names": sorted({str(row.supplier) for row in matched}),
        "model_count": len(models),
        "institution_count": len({row.demand_institution for row in matched if row.demand_institution}),
        "latest": max(dates).isoformat() if dates else "",
        "top_models": [f"{model} {count}건" for model, count in models.most_common(5)],
        "truncated": len(rows) >= CANDIDATE_LIMIT,
    }
