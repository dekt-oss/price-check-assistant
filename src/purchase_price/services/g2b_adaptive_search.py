from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from purchase_price.collectors.g2b_shopping import G2BShoppingCollector
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_candidate_search import search_mapped_g2b_candidates
from purchase_price.services.g2b_pagination import G2BPaginationLimitError
from purchase_price.services.g2b_product_mapping import (
    G2BMappingError,
    G2BProductMapping,
    resolve_verified_g2b_mapping,
)


@dataclass(frozen=True)
class AdaptiveWindowResult:
    begin_date: date
    end_date: date
    split_depth: int
    pages_fetched: int
    records_seen: int
    reported_total_count: int | None
    candidate_count: int


@dataclass(frozen=True)
class G2BAdaptiveSearchResult:
    mapping: G2BProductMapping
    windows: tuple[AdaptiveWindowResult, ...]
    candidate_prices: tuple[CollectedPrice, ...]

    @property
    def records_seen(self) -> int:
        return sum(window.records_seen for window in self.windows)

    @property
    def pages_fetched(self) -> int:
        return sum(window.pages_fetched for window in self.windows)


def _midpoint(begin_date: date, end_date: date) -> date:
    span_days = (end_date - begin_date).days
    return begin_date + timedelta(days=span_days // 2)


def _dedupe_candidate_prices(prices: list[CollectedPrice]) -> tuple[CollectedPrice, ...]:
    """Deduplicate only records carrying a stable external id; never guess identity without one."""

    seen_record_ids: set[tuple[str, str]] = set()
    output: list[CollectedPrice] = []
    for item in sorted(
        prices,
        key=lambda row: (
            row.transaction_date or date.max,
            row.source_record_id or "",
            row.original_title or row.product_name,
        ),
    ):
        if item.source_record_id:
            key = (item.source_name, item.source_record_id)
            if key in seen_record_ids:
                continue
            seen_record_ids.add(key)
        output.append(item)
    return tuple(output)


def search_mapped_g2b_candidates_adaptive(
    collector: G2BShoppingCollector,
    query: ProductQuery,
    *,
    begin_date: date,
    end_date: date,
    mappings: tuple[G2BProductMapping, ...] | None = None,
    num_of_rows: int = 100,
    max_pages: int = 20,
    max_split_depth: int = 12,
) -> G2BAdaptiveSearchResult:
    """Collect a verified G2B classification, splitting only page-cap overflow windows.

    A busy classification may exceed the explicit pagination safety cap even over a short period.
    In that case the inclusive date window is bisected and both halves are collected completely.
    Other API/payload failures are not disguised as density problems and therefore propagate.

    If a one-day window still exceeds the cap, collection fails closed rather than presenting a
    partial result as complete.
    """

    if begin_date > end_date:
        raise ValueError("begin_date must not be after end_date")
    if max_split_depth < 0:
        raise ValueError("max_split_depth must not be negative")

    mapping = resolve_verified_g2b_mapping(query, mappings)
    if mapping is None or not mapping.detail_product_name:
        raise G2BMappingError(
            "No verified G2B detail-product mapping for this query; automatic guessing is disabled"
        )

    windows: list[AdaptiveWindowResult] = []
    prices: list[CollectedPrice] = []

    def collect_window(window_begin: date, window_end: date, depth: int) -> None:
        try:
            result = search_mapped_g2b_candidates(
                collector,
                query,
                begin_date=window_begin,
                end_date=window_end,
                mappings=(mapping,),
                num_of_rows=num_of_rows,
                max_pages=max_pages,
            )
        except G2BPaginationLimitError as exc:
            if window_begin == window_end or depth >= max_split_depth:
                raise G2BPaginationLimitError(
                    "Adaptive G2B search could not fully collect the bounded window: "
                    f"begin={window_begin.isoformat()} end={window_end.isoformat()} "
                    f"split_depth={depth}"
                ) from exc

            midpoint = _midpoint(window_begin, window_end)
            collect_window(window_begin, midpoint, depth + 1)
            collect_window(midpoint + timedelta(days=1), window_end, depth + 1)
            return

        windows.append(
            AdaptiveWindowResult(
                begin_date=window_begin,
                end_date=window_end,
                split_depth=depth,
                pages_fetched=result.pages_fetched,
                records_seen=result.records_seen,
                reported_total_count=result.reported_total_count,
                candidate_count=len(result.candidate_prices),
            )
        )
        prices.extend(result.candidate_prices)

    collect_window(begin_date, end_date, 0)
    windows.sort(key=lambda window: (window.begin_date, window.end_date))

    return G2BAdaptiveSearchResult(
        mapping=mapping,
        windows=tuple(windows),
        candidate_prices=_dedupe_candidate_prices(prices),
    )
