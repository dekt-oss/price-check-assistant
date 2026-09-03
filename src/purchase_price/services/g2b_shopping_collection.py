from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from purchase_price.collectors.g2b_shopping import G2BShoppingCollector, G2BShoppingOperation
from purchase_price.models import CollectionRun
from purchase_price.services.g2b_pagination import G2BCollectedPage, iter_specific_item_pages
from purchase_price.services.g2b_shopping_ingest import persist_g2b_shopping_payload

__all__ = [
    "G2BCollectedPage",
    "G2BCollectionResult",
    "collect_specific_item_history",
    "iter_specific_item_pages",
]


@dataclass(frozen=True)
class G2BCollectionResult:
    pages_fetched: int
    records_seen: int
    evidence_created: int
    duplicates_seen: int
    reported_total_count: int | None


def collect_specific_item_history(
    session: Session,
    *,
    collector: G2BShoppingCollector,
    run: CollectionRun,
    detail_product_name: str,
    begin_date: date,
    end_date: date,
    num_of_rows: int = 100,
    max_pages: int = 20,
) -> G2BCollectionResult:
    """Fetch all allowed pages and persist each raw record idempotently."""

    pages_fetched = 0
    records_seen = 0
    evidence_created = 0
    duplicates_seen = 0
    reported_total_count: int | None = None

    for collected in iter_specific_item_pages(
        collector,
        detail_product_name=detail_product_name,
        begin_date=begin_date,
        end_date=end_date,
        num_of_rows=num_of_rows,
        max_pages=max_pages,
    ):
        pages_fetched += 1
        reported_total_count = collected.page.total_count
        ingest = persist_g2b_shopping_payload(
            session,
            run=run,
            payload=collected.payload,
            operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
        )
        records_seen += ingest.record_count
        evidence_created += ingest.created_count
        duplicates_seen += ingest.duplicate_count

    return G2BCollectionResult(
        pages_fetched=pages_fetched,
        records_seen=records_seen,
        evidence_created=evidence_created,
        duplicates_seen=duplicates_seen,
        reported_total_count=reported_total_count,
    )
