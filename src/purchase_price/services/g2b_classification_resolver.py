from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL

G2B_DETAIL_CLASS_SEARCH_OPERATION = "getPrdctClsfcNoUnit10Info02"

_SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


class DetailClassSearchField(StrEnum):
    KOREAN_NAME = "dtilPrdctClsfcNoNm"
    ENGLISH_NAME = "dtilPrdctClsfcNoEngNm"


@dataclass(frozen=True)
class NormalizedProductLabel:
    original: str
    base_name: str
    parenthetical_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class G2BDetailClassCandidate:
    detail_product_code: str
    korean_name: str
    english_name: str = ""
    description: str = ""
    use_status: str = ""
    search_field: DetailClassSearchField = DetailClassSearchField.KOREAN_NAME
    search_term: str = ""


@dataclass(frozen=True)
class G2BDetailClassSearchResult:
    search_field: DetailClassSearchField
    search_term: str
    candidates: tuple[G2BDetailClassCandidate, ...]
    request_count: int = 1
    total_count: int | None = None


def normalize_product_label(value: str) -> NormalizedProductLabel:
    """Normalize search syntax while preserving specification-bearing parenthetical text.

    This is deliberately not an identity resolver. It prevents semantic damage such as `CO₂`
    becoming `CO`, and keeps parenthetical text such as `Water Jacket` available as a separate
    specification/search clue instead of discarding it.
    """

    original = " ".join(value.split()).strip()
    if not original:
        return NormalizedProductLabel(original="", base_name="", parenthetical_terms=())

    translated = original.translate(_SUBSCRIPT_DIGITS)
    parenthetical_terms: list[str] = []
    for raw in re.findall(r"\(([^)]*)\)", translated):
        cleaned = re.sub(r"[^0-9A-Za-z가-힣+%./\-\s]", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and cleaned not in parenthetical_terms:
            parenthetical_terms.append(cleaned)

    base = re.sub(r"\([^)]*\)", " ", translated)
    base = re.sub(r"[^0-9A-Za-z가-힣+%./\-\s]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return NormalizedProductLabel(
        original=original,
        base_name=base,
        parenthetical_terms=tuple(parenthetical_terms),
    )


def _items_from_payload(payload: Mapping[str, Any]) -> tuple[tuple[dict[str, Any], ...], int | None]:
    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise PublicDataClientError("G2B detail-class response must be an object")

    header = response.get("header")
    if isinstance(header, Mapping):
        code = str(header.get("resultCode") or "").strip()
        if code and code not in {"0", "00", "000"}:
            message = str(header.get("resultMsg") or "").strip()
            raise PublicDataClientError(
                f"G2B detail-class API error resultCode={code} resultMsg={message or '-'}"
            )

    body = response.get("body", {})
    if not isinstance(body, Mapping):
        raise PublicDataClientError("G2B detail-class response body must be an object")
    total_raw = body.get("totalCount")
    try:
        total_count = int(total_raw) if total_raw not in (None, "") else None
    except (TypeError, ValueError):
        total_count = None

    raw = body.get("items", [])
    if isinstance(raw, Mapping) and "item" in raw:
        raw = raw["item"]
    if raw is None:
        return (), total_count
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list):
        raise PublicDataClientError("G2B detail-class response items must be a list or item object")
    return tuple(dict(item) for item in raw if isinstance(item, Mapping)), total_count


def _first_text(item: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _parse_candidate(
    item: Mapping[str, Any],
    *,
    search_field: DetailClassSearchField,
    search_term: str,
) -> G2BDetailClassCandidate | None:
    code = _first_text(item, "dtilPrdctClsfcNo")
    korean_name = _first_text(item, "dtilPrdctClsfcNoNm")
    if not code or not korean_name:
        return None
    return G2BDetailClassCandidate(
        detail_product_code=code,
        korean_name=korean_name,
        english_name=_first_text(item, "dtilPrdctClsfcNoEngNm"),
        description=_first_text(item, "dtilPrdctClsfcNoExpln", "dtilPrdctClsfcNoDc", "expln"),
        use_status=_first_text(item, "useYn", "useAt", "useYnNm"),
        search_field=search_field,
        search_term=search_term,
    )


class G2BClassificationResolverClient:
    """Search official PPS 10-digit detail classes without auto-verifying quote identity.

    Returned rows are candidates only. A matching English/Korean label does not prove that the
    quoted model belongs to that class, so callers must keep them outside verified mappings and
    direct-price assessment until separate evidence/user confirmation exists.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_CATALOG_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(
            service_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def search_detail_classes(
        self,
        *,
        term: str,
        field: DetailClassSearchField,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BDetailClassSearchResult:
        term = " ".join(term.split()).strip()
        if not term:
            raise ValueError("term is required")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page bounds must be positive")

        payload = self.client.get_json(
            self.base_url,
            G2B_DETAIL_CLASS_SEARCH_OPERATION,
            pageNo=page_no,
            numOfRows=num_of_rows,
            **{field.value: term},
        )
        items, total_count = _items_from_payload(payload)
        candidates: list[G2BDetailClassCandidate] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            candidate = _parse_candidate(item, search_field=field, search_term=term)
            if candidate is None:
                continue
            key = (candidate.detail_product_code, candidate.korean_name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
        return G2BDetailClassSearchResult(
            search_field=field,
            search_term=term,
            candidates=tuple(candidates),
            total_count=total_count,
        )
