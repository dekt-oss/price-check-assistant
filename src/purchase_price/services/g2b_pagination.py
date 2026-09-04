from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import G2BShoppingCollector, G2BShoppingPage


class G2BPaginationLimitError(PublicDataClientError):
    """Raised when a bounded window cannot be fully collected within the page safety cap."""


@dataclass(frozen=True)
class G2BCollectedPage:
    page: G2BShoppingPage
    payload: dict[str, Any]


def iter_specific_item_pages(
    collector: G2BShoppingCollector,
    *,
    detail_product_name: str,
    begin_date: date,
    end_date: date,
    num_of_rows: int = 100,
    max_pages: int = 20,
) -> Iterator[G2BCollectedPage]:
    """Yield complete public-API pages without importing persistence dependencies.

    Completion is decided from the number of records actually returned, not from the
    requested `num_of_rows`: if the server silently caps a page at fewer rows than requested,
    counting requested rows would stop early and present a truncated result as complete.

    The iterator fails closed when the explicit page cap would truncate the API result, and
    when the API returns an empty page while `totalCount` says records remain.
    It deliberately contains no SQLAlchemy/model imports so live probes and evidence
    capture can run without a database driver.
    """

    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    if num_of_rows < 1:
        raise ValueError("num_of_rows must be positive")

    records_seen = 0
    for page_no in range(1, max_pages + 1):
        page, payload = collector.fetch_specific_item_page(
            detail_product_name=detail_product_name,
            begin_date=begin_date,
            end_date=end_date,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )
        yield G2BCollectedPage(page=page, payload=payload)

        records_seen += len(page.items)
        if page.total_count is not None:
            if records_seen >= page.total_count:
                return
            if not page.items:
                raise PublicDataClientError(
                    "G2B page returned no items before totalCount was reached: "
                    f"page_no={page_no} records_seen={records_seen} "
                    f"total_count={page.total_count} detail_product_name={detail_product_name!r}"
                )
        elif len(page.items) < num_of_rows:
            return

    raise G2BPaginationLimitError(
        "G2B pagination safety limit reached before collection completed: "
        f"max_pages={max_pages} records_seen={records_seen} "
        f"detail_product_name={detail_product_name!r}"
    )
