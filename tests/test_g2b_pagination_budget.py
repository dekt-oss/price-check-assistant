from datetime import date

import pytest

from purchase_price.collectors.g2b_shopping import G2BShoppingPage
from purchase_price.services.g2b_pagination import (
    G2BPaginationLimitError,
    iter_specific_item_pages,
)


class FakeCollector:
    def __init__(self, *, total_count: int, item_count: int = 100) -> None:
        self.total_count = total_count
        self.item_count = item_count
        self.calls: list[int] = []

    def fetch_specific_item_page(self, **kwargs):
        page_no = int(kwargs["page_no"])
        self.calls.append(page_no)
        return (
            G2BShoppingPage(
                items=tuple({"row": index} for index in range(self.item_count)),
                total_count=self.total_count,
                page_no=page_no,
                num_of_rows=int(kwargs["num_of_rows"]),
            ),
            {"page": page_no},
        )


def test_total_count_over_capacity_fails_after_first_request() -> None:
    collector = FakeCollector(total_count=5000)

    with pytest.raises(G2BPaginationLimitError, match="exceeds the bounded page budget"):
        list(
            iter_specific_item_pages(
                collector,
                detail_product_name="제습기",
                begin_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                num_of_rows=100,
                max_pages=20,
            )
        )

    assert collector.calls == [1]


def test_total_count_at_capacity_does_not_fail_fast() -> None:
    collector = FakeCollector(total_count=2000)
    pages = iter_specific_item_pages(
        collector,
        detail_product_name="제습기",
        begin_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        num_of_rows=100,
        max_pages=20,
    )

    first_page = next(pages)
    assert first_page.page.total_count == 2000
    assert collector.calls == [1]
