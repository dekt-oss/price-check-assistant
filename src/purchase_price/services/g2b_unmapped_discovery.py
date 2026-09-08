from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

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

_SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_ACCESSORY_MARKERS = frozenset(
    {"accessory", "accessories", "액세서리", "부속품", "부속", "부품"}
)


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
    institution: str = ""
    supplier: str = ""
    quantity: Decimal | None = None
    unit: str = ""
    item_sequence: str = ""
    original_specification: str = ""
    delivery_condition: str = ""
    record_change_order: str = ""
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
    targeted_detail_codes: tuple[str, ...] = ()

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
    translated = product_name.translate(_SUBSCRIPT_DIGITS)
    without_parenthetical = re.sub(r"\([^)]*\)", " ", translated)
    safe_text = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", without_parenthetical)
    cleaned = re.sub(r"\s+", " ", safe_text).strip()
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
    """Build recall-oriented terms without asserting a verified mapping."""

    output: list[str] = list(build_g2b_discovery_terms(query.product_name))

    translated = query.product_name.translate(_SUBSCRIPT_DIGITS)
    cleaned = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", re.sub(r"\([^)]*\)", " ", translated))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    compact = re.sub(r"\s+", "", cleaned)
    if compact and compact != cleaned and re.search(r"[가-힣]", compact):
        output.append(compact)

    for parenthetical in re.findall(r"\(([^)]*)\)", translated):
        clue = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", parenthetical)
        clue = re.sub(r"\s+", " ", clue).strip()
        if clue and re.search(r"[가-힣]", clue):
            output.append(clue)

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


def _normalize_target_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = raw.strip()
        if not code:
            continue
        if not code.isdigit() or len(code) != 10:
            raise ValueError("target detail-product codes must be 10-digit PPS codes")
        if code not in seen:
            seen.add(code)
            output.append(code)
    return tuple(output[:3])


def _identity_parts(value: str) -> tuple[str, ...]:
    return tuple(
        normalize_text(token)
        for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
        if normalize_text(token)
    )


def _model_matches_title(model_name: str, title: str) -> bool:
    """Match a complete model identity, not a prefix or accessory-labelled row."""

    model_parts = _identity_parts(model_name)
    title_parts = _identity_parts(title)
    if not model_parts or not title_parts:
        return False
    if _ACCESSORY_MARKERS.intersection(title_parts):
        return False

    model_key = "".join(model_parts)
    max_width = max(1, len(model_parts))
    for width in range(1, max_width + 1):
        for start in range(0, len(title_parts) - width + 1):
            if "".join(title_parts[start : start + width]) == model_key:
                return True
    return False


def _raw_text(record: dict, *names: str) -> str:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _raw_decimal(record: dict, *names: str) -> Decimal | None:
    text = _raw_text(record, *names)
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "").replace("원", "").strip())
    except InvalidOperation:
        return None


def _candidate_from_record(
    record: dict,
    query: ProductQuery,
    *,
    search_term: str,
    target_detail_code: str = "",
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
    classification_code = str(record.get("dtilPrdctClsfcNo") or "").strip()
    classification_exact = bool(classification_name) and (
        normalize_text(classification_name) == normalize_text(search_term)
    )
    targeted_code_match = bool(target_detail_code) and classification_code == target_detail_code

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

    if targeted_code_match:
        score += 15
        reasons.append("세부품명번호 서버필터 일치")
    elif classification_exact:
        score += 10
        reasons.append("세부품명 정확 일치")

    return G2BDiscoveryCandidate(
        title=title,
        classification_name=classification_name,
        classification_code=classification_code,
        price=parsed.price,
        transaction_date=parsed.transaction_date,
        source_record_id=parsed.source_record_id or "",
        search_term=(f"code:{target_detail_code}" if target_detail_code else search_term),
        relevance=relevance,
        score=score,
        match_reason=" · ".join(reasons),
        product_id=_raw_text(record, "prdctIdntNo"),
        institution=_raw_text(record, "dminsttNm"),
        supplier=_raw_text(record, "corpNm"),
        quantity=parsed.quantity or _raw_decimal(record, "prdctQty"),
        unit=parsed.unit or _raw_text(record, "prdctUnit"),
        item_sequence=_raw_text(record, "prdctSno"),
        original_specification=_raw_text(
            record,
            "prdctSpcfctn",
            "spcfctn",
            "krnPrdctNm",
            "prdctIdntNoNm",
        ),
        delivery_condition=_raw_text(record, "dlvryCndtnNm"),
        record_change_order=_raw_text(record, "cntrctDlvrReqChgOrd"),
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
    target_detail_product_codes: tuple[str, ...] = (),
) -> G2BUnmappedDiscoveryResult:
    """Search broad names plus targeted detail codes while remaining Research-only."""

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    if pages_per_term_window < 1 or num_of_rows < 1:
        raise ValueError("page bounds must be positive")
    if request_budget < 1:
        raise ValueError("request_budget must be positive")

    terms = build_g2b_research_terms(query, curated_terms=curated_terms)
    target_codes = _normalize_target_codes(target_detail_product_codes)
    if not terms and not target_codes:
        return G2BUnmappedDiscoveryResult(
            "success_0",
            (),
            0,
            0,
            (),
            request_budget=request_budget,
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

    selectors = tuple(("code", code) for code in target_codes) + tuple(
        ("name", term) for term in terms
    )
    for window_begin, window_end in windows:
        if budget_exhausted:
            break
        for selector_type, selector_value in selectors:
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
                    kwargs = {
                        "begin_date": window_begin,
                        "end_date": window_end,
                        "page_no": page_no,
                        "num_of_rows": num_of_rows,
                    }
                    if selector_type == "code":
                        page, _ = collector.fetch_specific_item_page(
                            detail_product_code=selector_value,
                            **kwargs,
                        )
                    else:
                        page, _ = collector.fetch_specific_item_page(
                            detail_product_name=selector_value,
                            **kwargs,
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
                    candidate = _candidate_from_record(
                        raw,
                        query,
                        search_term=selector_value,
                        target_detail_code=(selector_value if selector_type == "code" else ""),
                    )
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
        targeted_detail_codes=target_codes,
    )
