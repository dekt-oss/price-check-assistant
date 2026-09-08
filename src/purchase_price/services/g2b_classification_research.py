from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_classification_resolver import (
    DetailClassSearchField,
    G2BClassificationResolverClient,
    G2BDetailClassCandidate,
    NormalizedProductLabel,
    normalize_product_label,
)


class ClassificationResearchStatus(StrEnum):
    SUCCESS = "success"
    SUCCESS_0 = "success_0"
    PARTIAL = "partial"
    FAILURE = "failure"
    NOT_CONFIGURED = "not_configured"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class ClassificationLookupRequest:
    field: DetailClassSearchField
    term: str
    rationale: str


@dataclass(frozen=True)
class G2BClassificationResearchResult:
    status: ClassificationResearchStatus
    normalized_label: NormalizedProductLabel
    lookup_requests: tuple[ClassificationLookupRequest, ...] = ()
    candidates: tuple[G2BDetailClassCandidate, ...] = ()
    request_count: int = 0
    failed_request_count: int = 0
    error_types: tuple[str, ...] = ()
    error_messages: tuple[str, ...] = ()

    @property
    def research_terms(self) -> tuple[str, ...]:
        """Return official candidate names for Research recall only."""
        output: list[str] = []
        seen: set[str] = set()
        for candidate in self.candidates:
            for term in (candidate.korean_name, candidate.english_name):
                normalized = " ".join(term.split()).strip()
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    output.append(normalized)
        return tuple(output)

    @property
    def specification_clues(self) -> tuple[str, ...]:
        return self.normalized_label.parenthetical_terms


def _dedupe_lookup_requests(
    requests: list[ClassificationLookupRequest],
) -> tuple[ClassificationLookupRequest, ...]:
    output: list[ClassificationLookupRequest] = []
    seen: set[tuple[DetailClassSearchField, str]] = set()
    for request in requests:
        term = " ".join(request.term.split()).strip()
        key = (request.field, term.casefold())
        if not term or key in seen:
            continue
        seen.add(key)
        output.append(
            ClassificationLookupRequest(field=request.field, term=term, rationale=request.rationale)
        )
    return tuple(output)


def build_classification_lookup_requests(product_label: str) -> tuple[ClassificationLookupRequest, ...]:
    normalized = normalize_product_label(product_label)
    base = normalized.base_name
    if not base:
        return ()
    requests: list[ClassificationLookupRequest] = []
    has_korean = bool(re.search(r"[가-힣]", base))
    has_latin = bool(re.search(r"[A-Za-z]", base))
    if has_korean:
        korean_term = " ".join(re.findall(r"[0-9A-Za-z가-힣+%./\-]+", base))
        requests.append(
            ClassificationLookupRequest(
                field=DetailClassSearchField.KOREAN_NAME,
                term=korean_term,
                rationale="견적 품명 의미보존 정규화",
            )
        )
    if has_latin:
        requests.append(
            ClassificationLookupRequest(
                field=DetailClassSearchField.ENGLISH_NAME,
                term=base,
                rationale="견적 영문 품명 의미보존 정규화",
            )
        )
        if re.search(r"\bCO2\b", base, flags=re.IGNORECASE):
            expanded = re.sub(r"\bCO2\b", "Carbon dioxide", base, flags=re.IGNORECASE)
            requests.append(
                ClassificationLookupRequest(
                    field=DetailClassSearchField.ENGLISH_NAME,
                    term=expanded,
                    rationale="CO2 공식 영문명 탐색용 chemical wording 확장",
                )
            )
            if re.search(r"\bIncubator$", expanded, flags=re.IGNORECASE):
                plural = re.sub(r"\bIncubator$", "incubators", expanded, flags=re.IGNORECASE)
                requests.append(
                    ClassificationLookupRequest(
                        field=DetailClassSearchField.ENGLISH_NAME,
                        term=plural,
                        rationale="PPS 세부품명 영문 복수형 탐색 확장",
                    )
                )
    return _dedupe_lookup_requests(requests)


def _safe_error_message(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:500] if text else type(exc).__name__


def resolve_classification_research(
    query: ProductQuery,
    *,
    service_key: str | None,
    base_url: str | None = None,
    timeout_seconds: float = 20.0,
    max_retries: int = 2,
    client: G2BClassificationResolverClient | None = None,
) -> G2BClassificationResearchResult:
    label = query.product_name.strip()
    normalized = normalize_product_label(label)
    lookup_requests = build_classification_lookup_requests(label)
    if not lookup_requests:
        return G2BClassificationResearchResult(
            status=ClassificationResearchStatus.NOT_RUN,
            normalized_label=normalized,
        )
    if client is None and not (service_key or "").strip():
        return G2BClassificationResearchResult(
            status=ClassificationResearchStatus.NOT_CONFIGURED,
            normalized_label=normalized,
            lookup_requests=lookup_requests,
        )
    resolver = client or G2BClassificationResolverClient(
        service_key or "injected",
        base_url=base_url or "https://apis.data.go.kr/1230000/ao/ThngListInfoService02",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    candidates: list[G2BDetailClassCandidate] = []
    seen: set[tuple[str, str]] = set()
    errors: list[Exception] = []
    successful_requests = 0
    for request in lookup_requests:
        try:
            result = resolver.search_detail_classes(term=request.term, field=request.field)
        except Exception as exc:
            errors.append(exc)
            continue
        successful_requests += 1
        for candidate in result.candidates:
            key = (candidate.detail_product_code, candidate.korean_name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    if successful_requests == 0 and errors:
        status = ClassificationResearchStatus.FAILURE
    elif errors:
        status = ClassificationResearchStatus.PARTIAL
    elif candidates:
        status = ClassificationResearchStatus.SUCCESS
    else:
        status = ClassificationResearchStatus.SUCCESS_0
    return G2BClassificationResearchResult(
        status=status,
        normalized_label=normalized,
        lookup_requests=lookup_requests,
        candidates=tuple(candidates),
        request_count=len(lookup_requests),
        failed_request_count=len(errors),
        error_types=tuple(sorted({type(exc).__name__ for exc in errors})),
        error_messages=tuple(sorted({_safe_error_message(exc) for exc in errors}))[:5],
    )
