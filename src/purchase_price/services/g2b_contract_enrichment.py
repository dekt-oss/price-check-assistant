from __future__ import annotations

from dataclasses import replace

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


def enrich_market_bundle_with_contracts(
    bundle: MarketResearchBundle,
    *,
    service_key: str | None,
    max_bid_notices: int = 8,
    max_pages_per_bid: int = 1,
    timeout_seconds: float = 20.0,
    max_retries: int = 2,
    client: G2BContractResearchClient | None = None,
) -> MarketResearchBundle:
    """Attach contracts using explicit bid notice identifiers only.

    Contract lookup failures remain different from successful zero-result responses. Contract totals
    stay research-only and are not converted to item unit prices by this function.
    """

    if max_bid_notices < 1 or max_pages_per_bid < 1:
        raise ValueError("enrichment bounds must be positive")

    base_sources = tuple(source for source in bundle.sources if source.source != G2BResearchSource.CONTRACT)
    base_records = tuple(
        record for record in bundle.records if record.source_type != G2BResearchSource.CONTRACT
    )
    notices = _candidate_notices(base_records, max_bid_notices=max_bid_notices)

    if not notices:
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.NOT_RUN,
            request_count=0,
        )
        return replace(bundle, sources=(*base_sources, source), records=base_records)

    if client is None and not service_key:
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.NOT_CONFIGURED,
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

    if errors and not contract_records:
        first = errors[0]
        source = ResearchSourceResult(
            source=G2BResearchSource.CONTRACT,
            status=ResearchSourceStatus.FAILURE,
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
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
        )

    return replace(
        bundle,
        sources=(*base_sources, source),
        records=(*base_records, *contract_records),
    )
