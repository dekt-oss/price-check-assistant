from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from purchase_price.collectors.g2b_shopping import (
    FIELD_ALIASES,
    SOURCE_NAME,
    G2BShoppingOperation,
    build_g2b_source_record_id,
    unwrap_g2b_page,
)
from purchase_price.models import CollectionRun
from purchase_price.repositories.evidence import get_or_create_raw_evidence


@dataclass(frozen=True)
class G2BShoppingIngestResult:
    record_count: int
    created_count: int
    duplicate_count: int


def _first(record: Mapping[str, Any], logical_name: str) -> Any:
    for key in FIELD_ALIASES[logical_name]:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def persist_g2b_shopping_payload(
    session: Session,
    *,
    run: CollectionRun,
    payload: Mapping[str, Any],
    operation: G2BShoppingOperation,
) -> G2BShoppingIngestResult:
    """Persist every raw record before product matching or price promotion.

    Raw evidence is intentionally saved even when no unit price can be parsed. This keeps
    collection auditable and lets later parser versions reprocess previously fetched records.
    Item identity uses the same composite external key as the normalized parser so one delivery
    request containing multiple products cannot collapse into a single `source_record_id`.
    """

    page = unwrap_g2b_page(payload)
    created_count = 0

    for record in page.items:
        product_name = _first(record, "product_name")
        _, created = get_or_create_raw_evidence(
            session,
            run=run,
            source_name=SOURCE_NAME,
            payload=record,
            source_record_id=build_g2b_source_record_id(record),
            original_title=str(product_name) if product_name not in (None, "") else None,
            parser_version=f"g2b-shopping-v2:{operation.value}",
        )
        if created:
            created_count += 1

    record_count = len(page.items)
    return G2BShoppingIngestResult(
        record_count=record_count,
        created_count=created_count,
        duplicate_count=record_count - created_count,
    )
