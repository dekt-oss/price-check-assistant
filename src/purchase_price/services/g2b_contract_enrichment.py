from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from purchase_price.services.g2b_contract_research import G2BContractResearchClient
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchSourceResult,
    ResearchSourceStatus,
)
from purchase_price.services.g2b_research_linking import normalize_bid_notice_no


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:500] if text else type(exc).__name__


def _candidate_notices(
    records: tuple[G2BResearchRecord, ...],
    *,
    max_bid_notices: int,
) -> tuple[str, ...]:
    bids = [
        record
        for record in records
        if record.source_type == G2BResearchSource.BID_NOTICE and record.bid_notice_no
    ]
    bids.sort(
        key=lambda item: (item.published_date is not None, item.published_date),
        reverse=True,
    )
    output: list[str] = []
    seen: set[str] = set()
    for record in bids:
        notice = normalize_bid_notice_no(record.bid_notice_no)
        if not notice or notice in seen:
            continue
        seen.add(notice)
        output.append(notice)
        if len(output) >= max_bid_notices:
            break
    return tuple(output)


def build_contract_lookback_stages(requested_lookback_days: int) -> tuple[int, ...]:
    """Return staged coverage targets: short -> 1y -> 3y -> explicit requested maximum."""

    if requested_lookback_days < 1:
        raise ValueError("requested_lookback_days must be positive")

    anchors = (90, 365, 1095)
    stages: list[int] = []
    for anchor in anchors:
        if requested_lookback_days <= anchor:
            stages.append(requested_lookback_days)
            break
        stages.append(anchor)
    if not stages or stages[-1] != requested_lookback_days:
        stages.append(requested_lookback_days)
    return tuple(dict.fromkeys(stages))


def _dedupe_terms(terms: tuple[str, ...], *, max_terms: int) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = " ".join(term.split()).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        output.append(normalized)
        if len(output) >= max_terms:
            break
    return tuple(output)


def enrich_market_bundle_with_contracts(
    bundle: MarketResearchBundle,
    *,
    service_key: str | None,
    max_bid_notices: int = 8,
    max_pages_per_bid: int = 1,
    timeout_seconds: float = 20.0,
    max_retries: int = 2,
    client: G2BContractResearchClient | None = None,
    independent_terms: tuple[str, ...] = (),
    requested_lookback_days: int = 365,
    today: date | None = None,
    minimum_records_before_stop: int = 3,
    max_independent_terms: int = 1,
    max_pages_per_window: int = 1,
) -> MarketResearchBundle:
    """Attach contracts by bid identifier and, when sparse, by independent PPS product search.

    The first path preserves exact bid linkage. If there is no bid seed or linked lookup returns a
    normal sparse result, the second path uses official PPSSrch product-name/date fields and expands
    coverage in stages. Contract totals remain research-only and are never converted to item unit
    prices. API failures remain failures rather than becoming normal zero results.
    """

    if max_bid_notices < 1 or max_pages_per_bid < 1:
        raise ValueError("enrichment bounds must be positive")
    if requested_lookback_days < 1:
        raise ValueError("requested_lookback_days must be positive")
    if minimum_records_before_stop < 1 or max_independent_terms < 1 or max_pages_per_window < 1:
        raise ValueError("independent-search bounds must be positive")

    base_sources = tuple(
        source for source in bundle.sources if source.source != G2BResearchSource.CONTRACT
    )
    base_records = tuple(
        record for record in bundle.records if record.source_type != G2BResearchSource.CONTRACT
    )
    notices = _candidate_notices(base_records, max_bid_notices=max_bid_notices)
    terms = _dedupe_terms(independent_terms, max_terms=max_independent_terms)

    if client is None and not service_key:
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.NOT_CONFIGURED,
            requested_lookback_days=requested_lookback_days,
            search_strategy="bid-linked + independent-product-name",
        )
        return replace(bundle, sources=(*base_sources, source), records=base_records)

    if not notices and not terms:
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.NOT_RUN,
            request_count=0,
            requested_lookback_days=requested_lookback_days,
            search_strategy="no bid seed and no independent product term",
        )
        return replace(bundle, sources=(*base_sources, source), records=base_records)

    active_client = client or G2BContractResearchClient(
        service_key or "injected",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    contract_records: list[G2BResearchRecord] = []
    seen: set[str] = set()
    errors: list[Exception] = []
    request_count = 0
    independent_ran = False
    coverage_start: date | None = None
    coverage_end: date | None = None

    for notice in notices:
        request_count += 1
        try:
            found, requests = active_client.search_by_bid_notice(
                bid_notice_no=notice,
                max_pages=max_pages_per_bid,
            )
        except Exception as exc:
            errors.append(exc)
            continue
        request_count += max(0, requests - 1)
        for record in found:
            if record.source_record_id in seen:
                continue
            seen.add(record.source_record_id)
            contract_records.append(record)

    # Do not amplify a transport/auth failure by immediately hammering the same endpoint with a
    # broad fallback. Independent search is for missing/sparse evidence after normal responses.
    can_expand = not errors and len(contract_records) < minimum_records_before_stop and bool(terms)
    if can_expand:
        end = today or date.today()
        previous_days = 0
        for stage_days in build_contract_lookback_stages(requested_lookback_days):
            interval_begin = end - timedelta(days=stage_days - 1)
            interval_end = end - timedelta(days=previous_days)
            if interval_begin > interval_end:
                previous_days = stage_days
                continue

            independent_ran = True
            coverage_start = interval_begin
            coverage_end = end
            for term in terms:
                try:
                    found, requests = active_client.search_by_product_name(
                        product_name=term,
                        begin_date=interval_begin,
                        end_date=interval_end,
                        max_pages_per_window=max_pages_per_window,
                    )
                except Exception as exc:
                    errors.append(exc)
                    continue
                request_count += requests
                for record in found:
                    if record.source_record_id in seen:
                        continue
                    seen.add(record.source_record_id)
                    contract_records.append(record)
            previous_days = stage_days
            if errors or len(contract_records) >= minimum_records_before_stop:
                break

    if errors and not contract_records:
        first = errors[0]
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.FAILURE,
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            requested_lookback_days=requested_lookback_days,
            search_strategy=(
                "bid-linked + adaptive independent product-name"
                if independent_ran
                else "bid-linked"
            ),
        )
    elif errors:
        first = errors[0]
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.PARTIAL,
            records=tuple(contract_records),
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            requested_lookback_days=requested_lookback_days,
            search_strategy=(
                "bid-linked + adaptive independent product-name"
                if independent_ran
                else "bid-linked"
            ),
        )
    else:
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=(
                ResearchSourceStatus.SUCCESS
                if contract_records
                else ResearchSourceStatus.SUCCESS_0
            ),
            records=tuple(contract_records),
            request_count=request_count,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            requested_lookback_days=requested_lookback_days,
            search_strategy=(
                "bid-linked + adaptive independent product-name"
                if independent_ran
                else "bid-linked"
            ),
        )

    return replace(
        bundle,
        sources=(*base_sources, source),
        records=(*base_records, *contract_records),
    )
