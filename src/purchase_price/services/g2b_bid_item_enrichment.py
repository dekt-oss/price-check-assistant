from __future__ import annotations

from dataclasses import replace

from purchase_price.clients.data_go_kr import PublicDataTransportError
from purchase_price.services.g2b_bid_items import G2BBidItemClient
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchAmountType,
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
) -> tuple[tuple[str, str | None], ...]:
    bids = [
        record
        for record in records
        if record.source_type == G2BResearchSource.BID_NOTICE and record.bid_notice_no
    ]
    bids.sort(
        key=lambda item: (item.published_date is not None, item.published_date),
        reverse=True,
    )
    output: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for record in bids:
        notice = normalize_bid_notice_no(record.bid_notice_no)
        order = (record.bid_notice_order or "").strip()
        key = (notice, order)
        if not notice or key in seen:
            continue
        seen.add(key)
        output.append((notice, order or None))
        if len(output) >= max_bid_notices:
            break
    return tuple(output)


def enrich_market_bundle_with_bid_items(
    bundle: MarketResearchBundle,
    *,
    service_key: str | None,
    max_bid_notices: int = 8,
    max_pages_per_bid: int = 1,
    timeout_seconds: float = 20.0,
    max_retries: int = 2,
    client: G2BBidItemClient | None = None,
) -> MarketResearchBundle:
    """Add bounded purchase-object details for explicit bid notices in a research bundle."""

    if max_bid_notices < 1 or max_pages_per_bid < 1:
        raise ValueError("enrichment bounds must be positive")

    base_sources = tuple(
        source for source in bundle.sources if source.source != G2BResearchSource.BID_ITEM
    )
    base_records = tuple(
        record for record in bundle.records if record.source_type != G2BResearchSource.BID_ITEM
    )
    notices = _candidate_notices(base_records, max_bid_notices=max_bid_notices)

    if not notices:
        item_source = ResearchSourceResult(
            source=G2BResearchSource.BID_ITEM,
            status=ResearchSourceStatus.NOT_RUN,
            request_count=0,
        )
        return replace(bundle, sources=(*base_sources, item_source), records=base_records)

    if client is None and not service_key:
        item_source = ResearchSourceResult(
            source=G2BResearchSource.BID_ITEM,
            status=ResearchSourceStatus.NOT_CONFIGURED,
        )
        return replace(bundle, sources=(*base_sources, item_source), records=base_records)

    active_client = client or G2BBidItemClient(
        service_key or "injected",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    item_records: list[G2BResearchRecord] = []
    seen: set[str] = set()
    errors: list[Exception] = []
    request_count = 0

    for notice, order in notices:
        request_count += 1
        try:
            found, requests = active_client.fetch_items(
                bid_notice_no=notice,
                bid_notice_order=order,
                max_pages=max_pages_per_bid,
            )
        except Exception as exc:
            errors.append(exc)
            if isinstance(exc, PublicDataTransportError):
                break
            continue
        request_count += max(0, requests - 1)
        for record in found:
            if record.source_record_id in seen:
                continue
            seen.add(record.source_record_id)
            item_records.append(record)

    if errors and not item_records:
        first = errors[0]
        item_source = ResearchSourceResult(
            source=G2BResearchSource.BID_ITEM,
            status=ResearchSourceStatus.FAILURE,
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
        )
    elif errors:
        first = errors[0]
        item_source = ResearchSourceResult(
            source=G2BResearchSource.BID_ITEM,
            status=ResearchSourceStatus.PARTIAL,
            records=tuple(item_records),
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
        )
    else:
        item_source = ResearchSourceResult(
            source=G2BResearchSource.BID_ITEM,
            status=(
                ResearchSourceStatus.SUCCESS
                if item_records
                else ResearchSourceStatus.SUCCESS_0
            ),
            records=tuple(item_records),
            request_count=request_count,
        )

    return replace(
        bundle,
        sources=(*base_sources, item_source),
        records=(*base_records, *item_records),
    )
