from __future__ import annotations

from dataclasses import replace

from purchase_price.services.g2b_catalog import G2BCatalogClient, G2BCatalogResult
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
    G2BUnmappedDiscoveryResult,
)


def _attribute_summary(result: G2BCatalogResult, *, limit: int = 6) -> str:
    parts: list[str] = []
    for row in result.attributes:
        value = row.attribute_value.strip()
        if not value:
            continue
        rendered = f"{row.attribute_name}={value}{row.attribute_unit}".strip()
        if rendered not in parts:
            parts.append(rendered)
        if len(parts) >= limit:
            break
    return " · ".join(parts)


def _priority(candidate: G2BDiscoveryCandidate) -> tuple[int, int]:
    relevance_rank = {
        "모델 표기 후보": 3,
        "제조사 표기 후보": 2,
        "분류 후보": 1,
    }.get(candidate.relevance, 0)
    return relevance_rank, candidate.score


def enrich_discovery_with_catalog(
    discovery: G2BUnmappedDiscoveryResult,
    *,
    service_key: str | None,
    max_candidates: int = 3,
    timeout_seconds: float = 10.0,
    max_retries: int = 1,
    base_url: str | None = None,
    client: G2BCatalogClient | None = None,
) -> G2BUnmappedDiscoveryResult:
    """Attach exact-ID official catalog attributes without changing candidate relevance.

    Shopping research has already produced a PPS `prdctIdntNo`. The catalog service may verify
    official attributes for that exact identifier, but it does not prove that the quote item is the
    same product. Therefore this enrichment never changes relevance, price-band eligibility, or
    direct-price assessment.
    """

    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    if not discovery.candidates:
        return discovery
    if client is None and not service_key:
        return discovery

    active = client or G2BCatalogClient(
        service_key or "injected",
        base_url=base_url or "https://apis.data.go.kr/1230000/ao/ThngListInfoService02",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )

    selected_ids: list[str] = []
    for candidate in sorted(discovery.candidates, key=_priority, reverse=True):
        product_id = candidate.product_id.strip()
        if not product_id or product_id in selected_ids:
            continue
        selected_ids.append(product_id)
        if len(selected_ids) >= max_candidates:
            break

    results: dict[str, G2BCatalogResult | Exception] = {}
    for product_id in selected_ids:
        try:
            results[product_id] = active.fetch_attributes(product_id=product_id)
        except Exception as exc:
            results[product_id] = exc

    enriched: list[G2BDiscoveryCandidate] = []
    for candidate in discovery.candidates:
        result = results.get(candidate.product_id)
        if result is None:
            enriched.append(candidate)
            continue
        if isinstance(result, Exception):
            enriched.append(
                replace(
                    candidate,
                    catalog_status="failure",
                    catalog_summary=f"공식 품목속성 조회 실패: {type(result).__name__}",
                )
            )
            continue

        detail_codes = set(result.detail_product_codes)
        if result.attributes:
            classification_note = ""
            if candidate.classification_code:
                if candidate.classification_code in detail_codes:
                    classification_note = "세부품명번호 일치"
                elif detail_codes:
                    classification_note = "세부품명번호 불일치 · 재검토 필요"
            details = _attribute_summary(result)
            summary = " · ".join(
                part for part in (classification_note, details) if part
            ) or "공식 품목속성 확인"
            enriched.append(
                replace(
                    candidate,
                    catalog_status="verified_exact_product_id",
                    catalog_summary=summary,
                )
            )
        else:
            enriched.append(
                replace(
                    candidate,
                    catalog_status="success_0",
                    catalog_summary="공식 품목속성 정상 0건",
                )
            )

    return replace(discovery, candidates=tuple(enriched))
