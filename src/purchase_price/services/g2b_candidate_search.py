from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from purchase_price.collectors.g2b_shopping import (
    G2BShoppingCollector,
    G2BShoppingOperation,
    parse_official_report_record,
)
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_product_mapping import (
    G2BMappingError,
    G2BProductMapping,
    filter_g2b_query_candidates,
    resolve_verified_g2b_mapping,
)
from purchase_price.services.g2b_shopping_collection import iter_specific_item_pages


@dataclass(frozen=True)
class G2BCandidateSearchResult:
    mapping: G2BProductMapping
    pages_fetched: int
    records_seen: int
    reported_total_count: int | None
    candidate_prices: tuple[CollectedPrice, ...]


def search_mapped_g2b_candidates(
    collector: G2BShoppingCollector,
    query: ProductQuery,
    *,
    begin_date: date,
    end_date: date,
    mappings: tuple[G2BProductMapping, ...] | None = None,
    num_of_rows: int = 100,
    max_pages: int = 20,
) -> G2BCandidateSearchResult:
    """Search verified G2B classification history and locally narrow model candidates.

    F1 candidate filtering never promotes MatchGrade. Parsed prices remain MatchGrade.X until
    the F3 identity matcher verifies manufacturer/model/specification equivalence.
    """

    mapping = resolve_verified_g2b_mapping(query, mappings)
    if mapping is None or not mapping.detail_product_name:
        raise G2BMappingError(
            "No verified G2B detail-product mapping for this query; "
            "automatic classification guessing is disabled"
        )

    pages_fetched = 0
    records_seen = 0
    reported_total_count: int | None = None
    prices: list[CollectedPrice] = []

    for collected in iter_specific_item_pages(
        collector,
        detail_product_name=mapping.detail_product_name,
        begin_date=begin_date,
        end_date=end_date,
        num_of_rows=num_of_rows,
        max_pages=max_pages,
    ):
        pages_fetched += 1
        records_seen += len(collected.page.items)
        reported_total_count = collected.page.total_count

        candidates = filter_g2b_query_candidates(collected.page.items, query)
        for record in candidates:
            parsed = parse_official_report_record(
                record,
                operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
            )
            if parsed is not None:
                prices.append(parsed)

    return G2BCandidateSearchResult(
        mapping=mapping,
        pages_fetched=pages_fetched,
        records_seen=records_seen,
        reported_total_count=reported_total_count,
        candidate_prices=tuple(prices),
    )
