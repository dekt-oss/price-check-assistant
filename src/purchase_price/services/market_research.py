from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    MarketResearchBundle,
    ResearchSourceResult,
    ResearchSourceStatus,
)
from purchase_price.services.g2b_market_sources import (
    G2BAwardResearchClient,
    G2BBidResearchClient,
    G2BPrespecResearchClient,
)
from purchase_price.services.g2b_product_mapping import research_g2b_mapping_terms
from purchase_price.services.g2b_research_terms import research_terms_for_query


def build_market_research_terms(query: ProductQuery, *, max_terms: int = 10) -> tuple[str, ...]:
    """Build layered recall terms without treating any expansion as product identity.

    Search order is intentionally broad for Research:
    exact model -> manufacturer+model -> quote product label -> research-only filename/category
    hints -> known official G2B detail-product names -> curated synonyms. The resulting records
    remain Research and cannot enter direct-price verdicts without the normal identity gates.
    """

    if max_terms < 1:
        raise ValueError("max_terms must be positive")

    raw: list[str] = []
    model = query.model_name.strip()
    manufacturer = query.manufacturer.strip()
    product = query.product_name.strip()

    if model:
        raw.append(model)
        if manufacturer:
            raw.append(f"{manufacturer} {model}")
    if product:
        raw.append(product)

    raw.extend(query.research_hints)
    raw.extend(research_g2b_mapping_terms(query))
    raw.extend(research_terms_for_query(query))

    output: list[str] = []
    seen: set[str] = set()
    for term in raw:
        normalized_request = " ".join(term.split()).strip()
        key = normalized_request.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(normalized_request)
        if len(output) >= max_terms:
            break
    return tuple(output)


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:500] if text else type(exc).__name__


def _run_source(
    *,
    source: G2BResearchSource,
    terms: tuple[str, ...],
    begin: date,
    end: date,
    search: Callable[[str, date, date], tuple[tuple[G2BResearchRecord, ...], int]],
) -> ResearchSourceResult:
    records: list[G2BResearchRecord] = []
    seen: set[str] = set()
    request_count = 0
    errors: list[Exception] = []

    for term in terms:
        try:
            found, requests = search(term, begin, end)
        except Exception as exc:  # source isolation is intentional; callers still see failure.
            errors.append(exc)
            continue
        request_count += requests
        for record in found:
            if record.source_record_id in seen:
                continue
            seen.add(record.source_record_id)
            records.append(record)

    if errors and not records:
        first = errors[0]
        return ResearchSourceResult(
            source=source,
            status=ResearchSourceStatus.FAILURE,
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
        )
    if errors:
        first = errors[0]
        return ResearchSourceResult(
            source=source,
            status=ResearchSourceStatus.PARTIAL,
            records=tuple(records),
            request_count=request_count,
            error_type=type(first).__name__,
            error_message=_safe_error(first),
        )
    return ResearchSourceResult(
        source=source,
        status=ResearchSourceStatus.SUCCESS if records else ResearchSourceStatus.SUCCESS_0,
        records=tuple(records),
        request_count=request_count,
    )


def research_g2b_market(
    query: ProductQuery,
    *,
    service_key: str | None,
    lookback_days: int = 90,
    today: date | None = None,
    timeout_seconds: float = 20.0,
    max_retries: int = 2,
    max_terms: int = 10,
    max_pages_per_window: int = 1,
    bid_base_url: str | None = None,
    award_base_url: str | None = None,
    prespec_base_url: str | None = None,
    bid_client: G2BBidResearchClient | None = None,
    award_client: G2BAwardResearchClient | None = None,
    prespec_client: G2BPrespecResearchClient | None = None,
) -> MarketResearchBundle:
    """Research bid, award and pre-spec sources even when no verified mapping exists.

    The returned records are research-only. This function never returns CollectedPrice and never
    calls assess_prices; evidence promotion remains a separate strict-verdict responsibility.
    """

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    terms = build_market_research_terms(query, max_terms=max_terms)
    if not terms:
        empty = tuple(
            ResearchSourceResult(source=source, status=ResearchSourceStatus.SUCCESS_0)
            for source in (
                G2BResearchSource.BID_NOTICE,
                G2BResearchSource.AWARD,
                G2BResearchSource.PRESPEC,
            )
        )
        return MarketResearchBundle(query_terms=(), sources=empty, records=())

    if not service_key and not (bid_client and award_client and prespec_client):
        missing = tuple(
            ResearchSourceResult(source=source, status=ResearchSourceStatus.NOT_CONFIGURED)
            for source in (
                G2BResearchSource.BID_NOTICE,
                G2BResearchSource.AWARD,
                G2BResearchSource.PRESPEC,
            )
        )
        return MarketResearchBundle(query_terms=terms, sources=missing, records=())

    if bid_client is None:
        bid_client = G2BBidResearchClient(
            service_key or "injected",
            base_url=bid_base_url or "https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    if award_client is None:
        award_client = G2BAwardResearchClient(
            service_key or "injected",
            base_url=award_base_url or "https://apis.data.go.kr/1230000/as/ScsbidInfoService",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    if prespec_client is None:
        prespec_client = G2BPrespecResearchClient(
            service_key or "injected",
            base_url=prespec_base_url
            or "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    end = today or date.today()
    begin = end - timedelta(days=lookback_days - 1)

    sources = (
        _run_source(
            source=G2BResearchSource.BID_NOTICE,
            terms=terms,
            begin=begin,
            end=end,
            search=lambda term, start, finish: bid_client.search(
                keyword=term,
                begin=start,
                end=finish,
                max_pages_per_window=max_pages_per_window,
            ),
        ),
        _run_source(
            source=G2BResearchSource.AWARD,
            terms=terms,
            begin=begin,
            end=end,
            search=lambda term, start, finish: award_client.search(
                keyword=term,
                begin=start,
                end=finish,
                max_pages_per_window=max_pages_per_window,
            ),
        ),
        _run_source(
            source=G2BResearchSource.PRESPEC,
            terms=terms,
            begin=begin,
            end=end,
            search=lambda term, start, finish: prespec_client.search(
                keyword=term,
                begin=start,
                end=finish,
                max_pages_per_window=max_pages_per_window,
            ),
        ),
    )
    records = tuple(record for source in sources for record in source.records)
    return MarketResearchBundle(query_terms=terms, sources=sources, records=records)
