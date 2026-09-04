from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from urllib.parse import quote_plus

from purchase_price.schemas import CollectedPrice


class SupplierPriority(IntEnum):
    G2B = 10
    MFDS = 20
    WEB = 30


class SupplierSource(StrEnum):
    G2B = "나라장터"
    MFDS = "식약처"
    WEB = "웹"


@dataclass(frozen=True)
class SupplierCandidate:
    name: str
    source: SupplierSource
    evidence: str
    source_url: str | None = None
    priority: SupplierPriority = SupplierPriority.WEB


@dataclass(frozen=True)
class AlternativeResearchGate:
    enabled: bool
    message: str


_SUPPLIER_PATTERN = re.compile(r"(?:^|;)\s*공급업체\s*=\s*([^;]+)")


def extract_g2b_supplier_candidates(items: list[CollectedPrice]) -> tuple[SupplierCandidate, ...]:
    """Extract actual public-procurement suppliers from existing G2B evidence.

    G2B shopping records already preserve the supplier in the normalized `conditions` field as
    `공급업체=<name>`. This helper intentionally uses only that explicit evidence. It does not infer
    a supplier from a manufacturer name, website mention, or product similarity.
    """

    seen: set[str] = set()
    candidates: list[SupplierCandidate] = []
    for item in items:
        conditions = item.conditions or ""
        match = _SUPPLIER_PATTERN.search(conditions)
        if not match:
            continue
        name = match.group(1).strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        candidates.append(
            SupplierCandidate(
                name=name,
                source=SupplierSource.G2B,
                evidence="나라장터 공개 납품/구매실적에서 공급업체명 확인",
                source_url=item.source_url,
                priority=SupplierPriority.G2B,
            )
        )
    return tuple(sorted(candidates, key=lambda item: (item.priority, item.name.casefold())))


def alternative_research_gate(active_domestic_count: int) -> AlternativeResearchGate:
    """Open broader alternative research only when official same-item candidates are zero."""

    if active_domestic_count > 0:
        return AlternativeResearchGate(
            enabled=False,
            message=(
                "식약처 동일 품목의 국내 후보가 있으므로 사용목적·주요사양 기반의 광범위한 "
                "대체탐색은 기본적으로 열지 않습니다."
            ),
        )
    return AlternativeResearchGate(
        enabled=True,
        message=(
            "식약처 동일 품목의 국내 후보가 0건입니다. 이 경우에만 사용목적·주요사양을 이용한 "
            "보조 대체탐색을 확인할 수 있습니다. 결과는 대체 가능 판정이 아니라 조사 후보입니다."
        ),
    )


def build_web_supplier_search_links(product_name: str, model_name: str = "") -> tuple[tuple[str, str], ...]:
    """Return transparent outbound web-search entry points without claiming discovered suppliers."""

    subject = " ".join(part.strip() for part in (product_name, model_name) if part.strip())
    if not subject:
        return ()
    queries = (
        ("웹 · 국내 공급사 검색", f'"{subject}" 의료기기 공급 업체'),
        ("웹 · 공식 대리점 검색", f'"{subject}" 공식 대리점 총판'),
    )
    return tuple(
        (label, f"https://www.google.com/search?q={quote_plus(query)}") for label, query in queries
    )


def build_alternative_web_search_links(
    *,
    product_name: str,
    intended_use: str,
    key_specification: str,
) -> tuple[tuple[str, str], ...]:
    """Build a zero-result-only research fallback; this is not a substitutability score."""

    terms = [product_name.strip(), intended_use.strip(), key_specification.strip(), "의료기기"]
    query = " ".join(term for term in terms if term)
    if not query.strip():
        return ()
    return (
        (
            "웹 · 대체장비 후보 조사",
            f"https://www.google.com/search?q={quote_plus(query)}",
        ),
    )
