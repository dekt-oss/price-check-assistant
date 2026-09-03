from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import (
    G2BShoppingCollector,
    G2BShoppingOperation,
    G2BShoppingPage,
)
from purchase_price.models import CollectionRun
from purchase_price.services.g2b_shopping_ingest import persist_g2b_shopping_payload


@dataclass(frozen=True)
class G2BCollectedPage:
    page: G2BShoppingPage
    payload: dict[str, Any]


@dataclass(frozen=True)
class G2BCollectionResult:
    pages_fetched: int
    records_seen: int
    evidence_created: int
    duplicates_seen: int
    reported_total_count: int | None


def iter_specific_item_pages(
    collector: G2BShoppingCollector,
    *,
    detail_product_name: str,
    begin_date: date,
    end_date: date,
    num_of_rows: int = 100,
    max_pages: int = 20,
) -> Iterator[G2BCollectedPage]:
    """Yield complete pages or fail when the explicit safety cap would truncate results."""

    if max_pages < 1:
        raise ValueError("max_pages must be positive")

    for page_no in range(1, max_pages + 1):
        page, payload = collector.fetch_specific_item_page(
            detail_product_name=detail_product_name,
            begin_date=begin_date,
            end_date=end_date,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )
        yield G2BCollectedPage(page=page, payload=payload)

        if page.total_count is not None:
            if page_no * num_of_rows >= page.total_count:
                return
        elif len(page.items) < num_of_rows:
            return

    raise PublicDataClientError(
        "G2B pagination safety limit reached before collection completed: "
        f"max_pages={max_pages} detail_product_name={detail_product_name!r}"
    )


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
