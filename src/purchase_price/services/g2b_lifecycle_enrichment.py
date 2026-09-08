from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from purchase_price.clients.data_go_kr import PublicDataTransportError
from purchase_price.services.g2b_lifecycle import G2BLifecycleClient, G2BLifecycleInquiry
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


def _candidate_notices(bundle: MarketResearchBundle, *, limit: int) -> tuple[str, ...]:
    records = sorted(
        (
            record
            for record in bundle.records
            if record.source_type == G2BResearchSource.BID_NOTICE and record.bid_notice_no
        ),
        key=lambda row: (row.published_date is not None, row.published_date),
        reverse=True,
    )
    output: list[str] = []
    seen: set[str] = set()
    for record in records:
        notice = normalize_bid_notice_no(record.bid_notice_no or "")
        if not notice or notice in seen:
            continue
        seen.add(notice)
        output.append(notice)
        if len(output) >= limit:
            break
    return tuple(output)


def _published_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _to_research_record(row, *, search_notice: str) -> G2BResearchRecord:
    return G2BResearchRecord(
        source_type=G2BResearchSource.LIFECYCLE,
        source_record_id=f"lifecycle:{row.source_record_id}",
        title=row.bid_notice_name or row.order_business_name or row.prespec_business_name or None,
        institution=row.bid_institution or row.order_institution or None,
        published_date=_published_date(row.bid_notice_datetime),
        bid_notice_no=row.bid_notice_no or search_notice,
        bid_notice_order=row.bid_notice_order or None,
        prespec_no=row.prespec_no or None,
        amount=None,
        amount_type=ResearchAmountType.UNKNOWN,
        search_term=search_notice,
    )


def enrich_market_bundle_with_lifecycle(
    bundle: MarketResearchBundle,
    *,
    service_key: str | None,
    max_bid_notices: int = 4,
    timeout_seconds: float = 20.0,
    max_retries: int = 3,
    base_url: str | None = None,
    client: G2BLifecycleClient | None = None,
) -> MarketResearchBundle:
    """Attach integrated PPS lifecycle links by exact bid notice number."""

    if max_bid_notices < 1:
        raise ValueError("max_bid_notices must be positive")

    base_sources = tuple(
        source for source in bundle.sources if source.source != G2BResearchSource.LIFECYCLE
    )
    base_records = tuple(
        record for record in bundle.records if record.source_type != G2BResearchSource.LIFECYCLE
    )
    notices = _candidate_notices(bundle, limit=max_bid_notices)
    if not notices:
        source = ResearchSourceResult(
            source=G2BResearchSource.LIFECYCLE,
            status=ResearchSourceStatus.NOT_RUN,
            request_count=0,
        )
        return replace(bundle, sources=(*base_sources, source), records=base_records)

    if client is None and not service_key:
        source = ResearchSourceResult(
            source=G2BResearchSource.LIFECYCLE,
            status=ResearchSourceStatus.NOT_CONFIGURED,
        )
        return replace(bundle, sources=(*base_sources, source), records=base_records)

    active = client or G2BLifecycleClient(
        service_key or "injected",
        base_url=base_url or "https://apis.data.go.kr/1230000/ao/CntrctProcssIntgOpenService",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    records: list[G2BResearchRecord] = []
    seen: set[str] = set()
    errors: list[Exception] = []
    request_count = 0

    for notice in notices:
        request_count += 1
        try:
            result = active.fetch(
                inquiry=G2BLifecycleInquiry.BID_NOTICE,
                identifier=notice,
                num_of_rows=20,
            )
        except Exception as exc:
            errors.append(exc)
            if isinstance(exc, PublicDataTransportError):
                break
            continue
        for row in result.records:
            record = _to_research_record(row, search_notice=notice)
            if record.source_record_id in seen:
                continue
            seen.add(record.source_record_id)
            records.append(record)

    if errors and not records:
        first = errors[0]
        source = ResearchSourceResult(
            source=G2BResearchSource.LIFECYCLE,
            status=ResearchSourceStatus.FAILURE,
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
        )
    elif errors:
        first = errors[0]
        source = ResearchSourceResult(
            source=G2BResearchSource.LIFECYCLE,
            status=ResearchSourceStatus.PARTIAL,
            records=tuple(records),
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
        )
    else:
        source = ResearchSourceResult(
            source=G2BResearchSource.LIFECYCLE,
            status=ResearchSourceStatus.SUCCESS if records else ResearchSourceStatus.SUCCESS_0,
            records=tuple(records),
            request_count=request_count,
        )

    return replace(
        bundle,
        sources=(*base_sources, source),
        records=(*base_records, *records),
    )
