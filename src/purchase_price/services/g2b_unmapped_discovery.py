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
from purchase_price.services.g2b_classification_resolver import G2BDetailClassCandidate
from purchase_price.services.g2b_research_terms import research_terms_for_query
from purchase_price.services.matching import normalize_text


@dataclass(frozen=True)
class G2BDiscoveryCandidate:
    title: str
    classification_name: str
    classification_code: str
    price: Decimal
    transaction_date: date | None
    source_record_id: str
    search_term: str = ""
    relevance: str = "분류 후보"
    score: int = 0
    match_reason: str = ""
    product_id: str = ""
    catalog_status: str = ""
    catalog_summary: str = ""


@dataclass(frozen=True)
class G2BUnmappedDiscoveryResult:
    status: str
    terms: tuple[str, ...]
    request_count: int
    records_seen: int
    candidates: tuple[G2BDiscoveryCandidate, ...]
    error_type: str = ""
    request_budget: int = 0
    failed_query_count: int = 0
    truncated_query_count: int = 0
    error_types: tuple[str, ...] = ()
    error_messages: tuple[str, ...] = ()
    classification_resolution_status: str = ""
    classification_lookup_terms: tuple[str, ...] = ()
    classification_candidates: tuple[G2BDetailClassCandidate, ...] = ()
    classification_specification_clues: tuple[str, ...] = ()
    classification_error_types: tuple[str, ...] = ()
    classification_error_messages: tuple[str, ...] = ()

    @property
    def status_label(self) -> str:
        if self.status == "success":
            return f"후보 {len(self.candidates)}건"
        if self.status == "partial":
            return f"부분완료 · 후보 {len(self.candidates)}건"
        if self.status == "success_0":
            return "정상 0건"
        return "실패"

    @property
    def complete(self) -> bool:
        return self.status in {"success", "success_0"}


def build_g2b_discovery_terms(product_name: str) -> tuple[str, ...]:
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


def build_g2b_research_terms(
    query: ProductQuery,
    *,
    curated_terms: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Build recall-oriented detail-product search terms without asserting a mapping.

    The server-side operation accepts a detail-product-name substring, not a model-name search.
    Therefore model/manufacturer strings are used for local ranking, while request terms stay
    product/classification-oriented. Curated terms are research-only aliases and never become a
    verified mapping through this function.
    """

    output: list[str] = list(build_g2b_discovery_terms(query.product_name))

    cleaned = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", re.sub(r"\([^)]*\)", " ", query.product_name))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    compact = re.sub(r"\s+", "", cleaned)
    if compact and compact != cleaned and re.search(r"[가-힣]", compact):
        output.append(compact)

    for parenthetical in re.findall(r"\(([^)]*)\)", query.product_name):
        parenthetical = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", parenthetical)
        parenthetical = re.sub(r"\s+", " ", parenthetical).strip()
        if parenthetical and re.search(r"[가-힣]", parenthetical):
            output.append(parenthetical)

    output.extend(curated_terms if curated_terms is not None else research_terms_for_query(query))

    deduped: list[str] = []
    seen: set[str] = set()
    for term in output:
        request_term = re.sub(r"\s+", " ", term).strip()
        key = request_term.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(request_term)
    return tuple(deduped[:8])


def _normalized_identity_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        normalize_text(token)
        for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
        if token
    )


def _model_matches_title(model_name: str, title: str) -> bool:
    """Require a bounded model identity instead of accepting arbitrary short substrings."""

    model_key = normalize_text(model_name)
    if not model_key:
        return False
    if len(model_key) <= 3:
        return model_key in _normalized_identity_tokens(title)
    return model_key in normalize_text(title)


def _candidate_from_record(
    record: dict,
    query: ProductQuery,
    *,
    search_term: str,
) -> G2BDiscoveryCandidate | None:
    parsed = parse_official_report_record(
        record,
        operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
    )
    if parsed is None:
        return None

    title = parsed.original_title or parsed.product_name
    title_key = normalize_text(title)
    model_hit = bool(query.model_name.strip()) and _model_matches_title(query.model_name, title)
    manufacturer_key = normalize_text(query.manufacturer)
    manufacturer_hit = bool(manufacturer_key) and manufacturer_key in title_key

    classification_name = str(record.get("dtilPrdctClsfcNoNm") or "")
    classification_exact = bool(classification_name) and (
        normalize_text(classification_name) == normalize_text(search_term)
    )

    if model_hit:
        relevance = "모델 표기 후보"
        score = 100
        reasons = ["모델 토큰 일치"]
        if manufacturer_hit:
            score += 20
            reasons.append("제조사 표기 일치")
    elif manufacturer_hit:
        relevance = "제조사 표기 후보"
        score = 70
        reasons = ["제조사 표기 일치", "모델 미확인"]
    else:
        relevance = "분류 후보"
        score = 30
        reasons = ["검색 세부품명 범주", "모델·제조사 미확인"]

    if classification_exact:
        score += 10
        reasons.append("세부품명 정확 일치")

    return G2BDiscoveryCandidate(
        title=title,
        classification_name=classification_name,
        classification_code=str(record.get("dtilPrdctClsfcNo") or ""),
        price=parsed.price,
        transaction_date=parsed.transaction_date,
        source_record_id=parsed.source_record_id or "",
        search_term=search_term,
        relevance=relevance,
        score=score,
        match_reason=" · ".join(reasons),
        product_id=str(record.get("prdctIdntNo") or "").strip(),
    )


def _year_bounded_windows(start: date, end: date) -> tuple[tuple[date, date], ...]:
    windows: list[tuple[date, date]] = []
    cursor_end = end
    while cursor_end >= start:
        cursor_start = max(start, cursor_end - timedelta(days=364))
        windows.append((cursor_start, cursor_end))
        cursor_end = cursor_start - timedelta(days=1)
    return tuple(windows)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip().replace("\n", " ")
    return message[:500] if message else type(exc).__name__


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
    request_budget: int = 80,
    today: date | None = None,
    curated_terms: tuple[str, ...] | None = None,
) -> G2BUnmappedDiscoveryResult:
    """Search broadly for research candidates without promoting them to direct-price evidence.

    Query terms may be broad or curated. Every returned row remains a G2BDiscoveryCandidate and is
    kept outside CollectedPrice. Model/manufacturer matches only affect research ranking.
    Individual term/window failures are isolated so one weak research query does not erase useful
    candidates from other terms. A partial result is explicitly labelled and never enters pricing.
    """

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    if pages_per_term_window < 1 or num_of_rows < 1:
        raise ValueError("page bounds must be positive")
    if request_budget < 1:
        raise ValueError("request_budget must be positive")

    terms = build_g2b_research_terms(query, curated_terms=curated_terms)
    if not terms:
        return G2BUnmappedDiscoveryResult(
            "success_0", (), 0, 0, (), request_budget=request_budget
        )

    client = PublicDataPortalClient(
        service_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    collector = G2BShoppingCollector(service_key, base_url=base_url, client=client)

    end = today or date.today()
    start = end - timedelta(days=lookback_days - 1)
    windows = _year_bounded_windows(start, end)

    request_count = 0
    records_seen = 0
    successful_fetches = 0
    failed_query_count = 0
    truncated_query_count = 0
    error_types: set[str] = set()
    error_messages: set[str] = set()
    budget_exhausted = False
    candidates_by_key: dict[tuple[str, str, str], G2BDiscoveryCandidate] = {}

    for window_begin, window_end in windows:
        if budget_exhausted:
            break
        for term in terms:
            if budget_exhausted:
                break
            fetched_for_query = 0
            query_failed = False
            query_complete = False
            last_total_count: int | None = None
            for page_no in range(1, pages_per_term_window + 1):
                if request_count >= request_budget:
                    budget_exhausted = True
                    break
                request_count += 1
                try:
                    page, _ = collector.fetch_specific_item_page(
                        detail_product_name=term,
                        begin_date=window_begin,
                        end_date=window_end,
                        page_no=page_no,
                        num_of_rows=num_of_rows,
                    )
                except (PublicDataClientError, ValueError) as exc:
                    failed_query_count += 1
                    error_types.add(type(exc).__name__)
                    error_messages.add(_safe_error_message(exc))
                    query_failed = True
                    break

                successful_fetches += 1
                records_seen += len(page.items)
                fetched_for_query += len(page.items)
                last_total_count = page.total_count
                for raw in page.items:
                    candidate = _candidate_from_record(raw, query, search_term=term)
                    if candidate is None:
                        continue
                    key = (
                        candidate.source_record_id,
                        candidate.title,
                        candidate.transaction_date.isoformat()
                        if candidate.transaction_date
                        else "",
                    )
                    previous = candidates_by_key.get(key)
                    if previous is None or candidate.score > previous.score:
                        candidates_by_key[key] = candidate
                if not page.items:
                    query_complete = True
                    break
                if page.total_count is not None and fetched_for_query >= page.total_count:
                    query_complete = True
                    break
                if len(page.items) < num_of_rows:
                    query_complete = True
                    break
            if query_failed or budget_exhausted:
                continue
            if not query_complete and (
                last_total_count is None or fetched_for_query < last_total_count
            ):
                truncated_query_count += 1

    candidates = sorted(
        candidates_by_key.values(),
        key=lambda item: (
            item.score,
            item.transaction_date or date.min,
            item.title,
            item.source_record_id,
        ),
        reverse=True,
    )

    incomplete = budget_exhausted or failed_query_count > 0 or truncated_query_count > 0
    if successful_fetches == 0 and failed_query_count > 0:
        status = "failure"
    elif incomplete:
        status = "partial"
    else:
        status = "success" if candidates else "success_0"

    ordered_errors = tuple(sorted(error_types))
    ordered_messages = tuple(sorted(error_messages))[:5]
    return G2BUnmappedDiscoveryResult(
        status,
        terms,
        request_count,
        records_seen,
        tuple(candidates[:100]),
        error_type=ordered_errors[0] if ordered_errors else "",
        request_budget=request_budget,
        failed_query_count=failed_query_count,
        truncated_query_count=truncated_query_count,
        error_types=ordered_errors,
        error_messages=ordered_messages,
    )
