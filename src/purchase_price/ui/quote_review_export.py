from __future__ import annotations

from typing import Any

from purchase_price.services.quote_comparable_approval import quote_evidence_pair_key
from purchase_price.ui.quote_review_state import QuoteReviewState


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    return format(value, "f")  # type: ignore[arg-type]


def build_record(state: QuoteReviewState) -> dict[str, Any]:
    """Build a downloadable review record without the uploaded filename or source document text."""
    items: list[dict[str, Any]] = []
    for index, item in enumerate(state.items):
        context = state.comparability_context.get(index)
        run = state.search_runs.get(index)
        evidence_rows: list[dict[str, Any]] = []
        if run is not None:
            for evidence in run.results:
                pair_key = quote_evidence_pair_key(context, evidence) if context is not None else None
                approval = state.approvals.get(pair_key or "")
                evidence_rows.append(
                    {
                        "source_name": evidence.source_name,
                        "source_record_id": evidence.source_record_id,
                        "source_url": evidence.source_url,
                        "price": _decimal(evidence.price),
                        "currency": evidence.currency,
                        "match_grade": evidence.match_grade.value,
                        "evidence_type": evidence.evidence_type.value,
                        "comparison_scope": evidence.comparison_scope.value,
                        "pair_key": pair_key,
                        "approved": approval is not None,
                        "approval": (
                            {
                                "approved_at": approval.approved_at.isoformat(),
                                "reviewer_note": approval.reviewer_note,
                                "confirmed_condition_labels": list(
                                    approval.confirmed_condition_labels
                                ),
                            }
                            if approval is not None
                            else None
                        ),
                    }
                )
        items.append(
            {
                "item_index": index,
                "product_name": item.product_name,
                "manufacturer": item.manufacturer,
                "model_name": item.model_name,
                "specification": item.specification,
                "quantity": _decimal(item.quantity),
                "unit": item.unit,
                "unit_price": _decimal(item.unit_price),
                "total_amount": _decimal(item.total_amount),
                "vat_status": item.vat_status,
                "conditions": {
                    "delivery": item.delivery_condition,
                    "installation": item.installation_condition,
                    "options": item.option_condition,
                    "warranty": item.warranty_condition,
                    "maintenance": item.maintenance_condition,
                    "other": item.other_conditions,
                },
                "confirmed": state.item_confirmed.get(index, False),
                "review_note": state.item_notes.get(index, ""),
                "quote_date": (
                    context.quote_date.isoformat()
                    if context is not None and context.quote_date is not None
                    else None
                ),
                "evidence": evidence_rows,
            }
        )

    return {
        "schema_version": "quote-review-r5-v1",
        "started_at": state.started_at.isoformat(),
        "reviewer": state.reviewer,
        "step": state.step,
        "lookback_days": state.lookback_days,
        "items": items,
    }
