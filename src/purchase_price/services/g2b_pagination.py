from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import G2BShoppingCollector, G2BShoppingPage


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

    The iterator fails closed if the explicit page cap would truncate the API result.
    It deliberately contains no SQLAlchemy/model imports so live probes and evidence
    capture can run without a database driver.
    """

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
