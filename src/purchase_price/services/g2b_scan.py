from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import G2BShoppingCollector
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_candidate_search import search_mapped_g2b_candidates
from purchase_price.services.g2b_product_mapping import G2BProductMapping
from purchase_price.services.matching import normalize_text


@dataclass(frozen=True)
class DateChunk:
    begin: date
    end: date


def iter_date_chunks(begin: date, end: date, *, max_days: int) -> Iterator[DateChunk]:
    """Split an inclusive date range into consecutive inclusive windows of at most `max_days`."""

    if max_days < 1:
        raise ValueError("max_days must be positive")
    if begin > end:
        raise ValueError("begin must not be after end")

    cursor = begin
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_days - 1))
        yield DateChunk(begin=cursor, end=chunk_end)
        cursor = chunk_end + timedelta(days=1)


@dataclass(frozen=True)
class ChunkScanSummary:
    benchmark_model: str
    detail_product_name: str
    begin_date: date
    end_date: date
    status: str
    pages_fetched: int
    records_seen: int
    reported_total_count: int | None
    candidate_count: int
    grade_counts: dict[str, int]
    error: str | None = None

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@dataclass(frozen=True)
class CandidateIdentitySummary:
    """One row per distinct candidate title so repeated transactions do not dominate a sample."""

    benchmark_model: str
    candidate_title: str
    predicted_grade: str
    match_note: str
    transaction_count: int
    first_transaction_date: date | None
    last_transaction_date: date | None
    min_price: Decimal
    max_price: Decimal
    evidence_types: tuple[str, ...]
    source_record_ids: tuple[str, ...]


@dataclass(frozen=True)
class G2BExactModelScanResult:
    query: ProductQuery
    mapping: G2BProductMapping | None
    chunks: tuple[ChunkScanSummary, ...]
    candidates: tuple[CandidateIdentitySummary, ...]

    @property
    def complete(self) -> bool:
        return bool(self.chunks) and all(chunk.complete for chunk in self.chunks)

    @property
    def records_seen(self) -> int:
        return sum(chunk.records_seen for chunk in self.chunks)

    @property
    def transaction_count(self) -> int:
        return sum(candidate.transaction_count for candidate in self.candidates)


def summarize_candidate_identities(
    benchmark_model: str,
    prices: list[CollectedPrice] | tuple[CollectedPrice, ...],
) -> tuple[CandidateIdentitySummary, ...]:
    grouped: dict[str, list[CollectedPrice]] = {}
    for price in prices:
        title = price.original_title or price.product_name
        key = normalize_text(title)
        if not key:
            continue
        grouped.setdefault(key, []).append(price)

    summaries: list[CandidateIdentitySummary] = []
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda item: (
                item.transaction_date or date.max,
                item.source_record_id or "",
            ),
        )
        first = ordered[0]
        dates = [item.transaction_date for item in ordered if item.transaction_date is not None]
        record_ids = tuple(
            dict.fromkeys(item.source_record_id for item in ordered if item.source_record_id)
        )
        summaries.append(
            CandidateIdentitySummary(
                benchmark_model=benchmark_model,
                candidate_title=first.original_title or first.product_name,
                predicted_grade=first.match_grade.value,
                match_note=first.match_note or "",
                transaction_count=len(ordered),
                first_transaction_date=min(dates) if dates else None,
                last_transaction_date=max(dates) if dates else None,
                min_price=min(item.price for item in ordered),
                max_price=max(item.price for item in ordered),
                evidence_types=tuple(sorted({item.evidence_type.value for item in ordered})),
                source_record_ids=record_ids,
            )
        )

    summaries.sort(
        key=lambda item: (
            item.first_transaction_date or date.max,
            item.candidate_title,
        )
    )
    return tuple(summaries)


def scan_exact_model_candidates(
    collector: G2BShoppingCollector,
    query: ProductQuery,
    *,
    begin_date: date,
    end_date: date,
    mappings: tuple[G2BProductMapping, ...] | None = None,
    chunk_days: int = 31,
    num_of_rows: int = 100,
    max_pages_per_chunk: int = 20,
) -> G2BExactModelScanResult:
    """Scan a long period in bounded windows and report per-window completeness.

    Each window is a separate full pagination of the verified G2B classification. A window
    whose pagination fails (safety cap, API error) is recorded as `incomplete` with the error
    text and the scan continues; the overall result is only `complete` when every window is.
    Candidates are the F3-graded records whose title carries the query model token; the
    grades are not altered here.
    """

    benchmark_model = query.model_name or query.product_name
    chunks: list[ChunkScanSummary] = []
    prices: list[CollectedPrice] = []
    mapping: G2BProductMapping | None = None

    for window in iter_date_chunks(begin_date, end_date, max_days=chunk_days):
        try:
            result = search_mapped_g2b_candidates(
                collector,
                query,
                begin_date=window.begin,
                end_date=window.end,
                mappings=mappings,
                num_of_rows=num_of_rows,
                max_pages=max_pages_per_chunk,
            )
        except PublicDataClientError as exc:
            chunks.append(
                ChunkScanSummary(
                    benchmark_model=benchmark_model,
                    detail_product_name=mapping.detail_product_name if mapping else "",
                    begin_date=window.begin,
                    end_date=window.end,
                    status="incomplete",
                    pages_fetched=0,
                    records_seen=0,
                    reported_total_count=None,
                    candidate_count=0,
                    grade_counts={},
                    error=str(exc),
                )
            )
            continue

        mapping = result.mapping
        grade_counts = Counter(price.match_grade.value for price in result.candidate_prices)
        prices.extend(result.candidate_prices)
        chunks.append(
            ChunkScanSummary(
                benchmark_model=benchmark_model,
                detail_product_name=result.mapping.detail_product_name or "",
                begin_date=window.begin,
                end_date=window.end,
                status="complete",
                pages_fetched=result.pages_fetched,
                records_seen=result.records_seen,
                reported_total_count=result.reported_total_count,
                candidate_count=len(result.candidate_prices),
                grade_counts=dict(sorted(grade_counts.items())),
            )
        )

    return G2BExactModelScanResult(
        query=query,
        mapping=mapping,
        chunks=tuple(chunks),
        candidates=summarize_candidate_identities(benchmark_model, prices),
    )
