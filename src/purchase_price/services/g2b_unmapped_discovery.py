from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingCollector,
    G2BShoppingOperation,
    parse_official_report_record,
)
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text


@dataclass(frozen=True)
class G2BDiscoveryCandidate:
    title: str
    classification_name: str
    classification_code: str
    price: Decimal
    transaction_date: date | None
    source_record_id: str


@dataclass(frozen=True)
class G2BUnmappedDiscoveryResult:
    status: str
    terms: tuple[str, ...]
    request_count: int
    records_seen: int
    candidates: tuple[G2BDiscoveryCandidate, ...]
    error_type: str = ""

    @property
    def status_label(self) -> str:
        if self.status == "success":
            return f"후보 {len(self.candidates)}건"
        if self.status == "success_0":
            return "정상 0건"
        return "실패"


def build_g2b_discovery_terms(product_name: str) -> tuple[str, ...]:
    """Build at most two conservative classification-name discovery terms.

    Terms are discovery inputs only. They never establish a verified G2B classification mapping.
    English/parenthetical quote descriptions are removed first, then the final Korean token is
    used as a broader fallback (e.g. `가스 마취기` -> `마취기`).
    """

    without_parenthetical = re.sub(r"\([^)]*\)", " ", product_name)
    korean_and_space = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", without_parenthetical)
    cleaned = re.sub(r"\s+", " ", korean_and_space).strip()
    if not cleaned:
        return ()

    terms: list[str] = [cleaned]
    korean_tokens = re.findall(r"[가-힣]{2,}", cleaned)
    if korean_tokens:
        fallback = korean_tokens[-1]
        if normalize_text(fallback) != normalize_text(cleaned):
            terms.append(fallback)
    return tuple(dict.fromkeys(terms))[:2]


def _candidate_from_record(record: dict, query: ProductQuery) -> G2BDiscoveryCandidate | None:
    parsed = parse_official_report_record(
        record,
        operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
    )
    if parsed is None:
        return None

    title = parsed.original_title or parsed.product_name
    model_key = normalize_text(query.model_name)
    if model_key and model_key not in normalize_text(title):
        return None

    manufacturer_key = normalize_text(query.manufacturer)
    if not model_key and manufacturer_key and manufacturer_key not in normalize_text(title):
        return None

    return G2BDiscoveryCandidate(
        title=title,
        classification_name=str(record.get("dtilPrdctClsfcNoNm") or ""),
        classification_code=str(record.get("dtilPrdctClsfcNo") or ""),
        price=parsed.price,
        transaction_date=parsed.transaction_date,
        source_record_id=parsed.source_record_id or "",
    )


def discover_unmapped_g2b_candidates(
    query: ProductQuery,
    *,
    service_key: str,
    lookback_days: int,
    base_url: str = G2B_SHOPPING_BASE_URL,
    timeout_seconds: float = 20.0,
    max_retries: int = 3,
    pages_per_term_window: int = 2,
    num_of_rows: int = 100,
    today: date | None = None,
) -> G2BUnmappedDiscoveryResult:
    """Search unverified classifications without promoting candidates to direct-price evidence.

    The official specific-item endpoint substring-matches classification names. This function is
    therefore intentionally a discovery surface only: it returns sanitized candidate metadata and
    never emits `CollectedPrice`, MatchGrade A/B, or a verified mapping.

    Long lookbacks are searched newest-first in windows of at most one year. Each term/window is
    bounded to a small number of pages to keep interactive traffic predictable.
    """

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    if pages_per_term_window < 1 or num_of_rows < 1:
        raise ValueError("page bounds must be positive")

    terms = build_g2b_discovery_terms(query.product_name)
    if not terms:
        return G2BUnmappedDiscoveryResult(
            status="success_0",
            terms=(),
            request_count=0,
            records_seen=0,
            candidates=(),
        )

    client = PublicDataPortalClient(
        service_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    collector = G2BShoppingCollector(service_key, base_url=base_url, client=client)

    end = today or date.today()
    start = end - timedelta(days=lookback_days - 1)
    windows: list[tuple[date, date]] = []
    cursor_end = end
    while cursor_end >= start:
        cursor_start = max(start, cursor_end - timedelta(days=364))
        windows.append((cursor_start, cursor_end))
        cursor_end = cursor_start - timedelta(days=1)

    request_count = 0
    records_seen = 0
    candidates: list[G2BDiscoveryCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    try:
        for window_begin, window_end in windows:
            for term in terms:
                fetched_for_query = 0
                for page_no in range(1, pages_per_term_window + 1):
                    page, _ = collector.fetch_specific_item_page(
                        detail_product_name=term,
                        begin_date=window_begin,
                        end_date=window_end,
                        page_no=page_no,
                        num_of_rows=num_of_rows,
                    )
                    request_count += 1
                    records_seen += len(page.items)
                    fetched_for_query += len(page.items)

                    for raw in page.items:
                        candidate = _candidate_from_record(raw, query)
                        if candidate is None:
                            continue
                        key = (
                            candidate.source_record_id,
                            candidate.title,
                            candidate.transaction_date.isoformat()
                            if candidate.transaction_date
                            else "",
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append(candidate)

                    if not page.items:
                        break
                    if page.total_count is not None and fetched_for_query >= page.total_count:
                        break
                    if len(page.items) < num_of_rows:
                        break
    except (PublicDataClientError, ValueError) as exc:
        return G2BUnmappedDiscoveryResult(
            status="failure",
            terms=terms,
            request_count=request_count,
            records_seen=records_seen,
            candidates=tuple(candidates),
            error_type=type(exc).__name__,
        )

    candidates.sort(
        key=lambda item: (
            item.transaction_date or date.min,
            item.title,
            item.source_record_id,
        ),
        reverse=True,
    )
    return G2BUnmappedDiscoveryResult(
        status="success" if candidates else "success_0",
        terms=terms,
        request_count=request_count,
        records_seen=records_seen,
        candidates=tuple(candidates[:50]),
    )
