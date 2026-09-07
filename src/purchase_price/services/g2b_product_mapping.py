from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parents[3] / "data" / "g2b_product_mappings.csv"


class G2BMappingError(RuntimeError):
    pass


@dataclass(frozen=True)
class G2BProductMapping:
    model_name: str
    product_name: str
    detail_product_name: str | None
    detail_product_code: str | None
    mapping_status: str
    evidence_url: str | None = None
    notes: str | None = None

    @property
    def verified(self) -> bool:
        return self.mapping_status.casefold() == "verified"


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_g2b_product_mappings(path: Path = DEFAULT_MAPPING_PATH) -> tuple[G2BProductMapping, ...]:
    if not path.exists():
        raise G2BMappingError(f"G2B mapping registry not found: {path}")

    mappings: list[G2BProductMapping] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "model_name",
            "product_name",
            "g2b_detail_product_name",
            "g2b_detail_product_code",
            "mapping_status",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise G2BMappingError("G2B mapping registry is missing required columns")

        for row in reader:
            mapping = G2BProductMapping(
                model_name=(row.get("model_name") or "").strip(),
                product_name=(row.get("product_name") or "").strip(),
                detail_product_name=_optional(row.get("g2b_detail_product_name")),
                detail_product_code=_optional(row.get("g2b_detail_product_code")),
                mapping_status=(row.get("mapping_status") or "").strip(),
                evidence_url=_optional(row.get("evidence_url")),
                notes=_optional(row.get("notes")),
            )
            if mapping.verified and not mapping.detail_product_name:
                raise G2BMappingError(
                    f"verified mapping has no G2B detail product name: {mapping.model_name!r}"
                )
            # The live service matches `dtilPrdctClsfcNoNm` as a substring, so the name alone
            # cannot pin a classification. The code is what makes the mapping enforceable.
            if mapping.verified and not mapping.detail_product_code:
                raise G2BMappingError(
                    f"verified mapping has no G2B detail product code: {mapping.model_name!r}"
                )
            mappings.append(mapping)

    verified_model_keys: set[str] = set()
    for mapping in mappings:
        if not mapping.verified or not mapping.model_name:
            continue
        key = normalize_text(mapping.model_name)
        if key in verified_model_keys:
            raise G2BMappingError(f"duplicate verified model mapping: {mapping.model_name!r}")
        verified_model_keys.add(key)

    return tuple(mappings)


def resolve_verified_g2b_mapping(
    query: ProductQuery,
    mappings: Iterable[G2BProductMapping] | None = None,
) -> G2BProductMapping | None:
    """Resolve only explicitly verified mappings; ambiguous/unverified rows fail closed."""

    rows = tuple(mappings) if mappings is not None else load_g2b_product_mappings()
    verified = tuple(row for row in rows if row.verified and row.detail_product_name)

    model_key = normalize_text(query.model_name)
    if model_key:
        matches = [row for row in verified if normalize_text(row.model_name) == model_key]
        return matches[0] if len(matches) == 1 else None

    product_key = normalize_text(query.product_name)
    if product_key:
        matches = [row for row in verified if normalize_text(row.product_name) == product_key]
        return matches[0] if len(matches) == 1 else None

    return None


def research_g2b_mapping_terms(
    query: ProductQuery,
    mappings: Iterable[G2BProductMapping] | None = None,
) -> tuple[str, ...]:
    """Return known official/detail-product names for Research recall only.

    Unlike `resolve_verified_g2b_mapping`, this may use an unverified registry row when it already
    carries a detail-product name. The returned strings are search aliases only: they never supply
    a classification code, never establish identity and never promote MatchGrade.
    """

    rows = tuple(mappings) if mappings is not None else load_g2b_product_mappings()
    model_key = normalize_text(query.model_name)
    product_key = normalize_text(query.product_name)

    selected: list[G2BProductMapping] = []
    if model_key:
        selected = [
            row
            for row in rows
            if row.detail_product_name and normalize_text(row.model_name) == model_key
        ]
    if not selected and product_key:
        candidates: list[tuple[int, G2BProductMapping]] = []
        for row in rows:
            if not row.detail_product_name:
                continue
            row_key = normalize_text(row.product_name)
            if not row_key:
                continue
            if row_key == product_key or row_key in product_key or product_key in row_key:
                candidates.append((len(row_key), row))
        if candidates:
            longest = max(length for length, _ in candidates)
            selected = [row for length, row in candidates if length == longest]

    output: list[str] = []
    seen: set[str] = set()
    for row in selected:
        term = (row.detail_product_name or "").strip()
        key = normalize_text(term)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(term)
    return tuple(output)


_RECORD_TITLE_FIELDS = (
    "prdctIdntNoNm",
    "물품식별명",
    "품명",
    "세부품명(명칭)",
    "세부품명",
)


def g2b_record_title(record: Mapping[str, Any]) -> str:
    for field in _RECORD_TITLE_FIELDS:
        value = record.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def g2b_record_is_query_candidate(record: Mapping[str, Any], query: ProductQuery) -> bool:
    """Low-risk local candidate filter; this does not assign MatchGrade A/B/C/D."""

    title = normalize_text(g2b_record_title(record))
    if not title:
        return False

    model = normalize_text(query.model_name)
    if model:
        return model in title

    manufacturer = normalize_text(query.manufacturer)
    if manufacturer:
        return manufacturer in title

    return True


def filter_g2b_query_candidates(
    records: Iterable[Mapping[str, Any]],
    query: ProductQuery,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(record for record in records if g2b_record_is_query_candidate(record, query))


def records_in_mapped_classification(
    records: Iterable[Mapping[str, Any]],
    mapping: G2BProductMapping,
) -> list[dict[str, Any]]:
    """Keep only records that really belong to the mapped classification.

    The specific-item API matches `dtilPrdctClsfcNoNm` as a substring server-side: querying
    `냉장고` also returns 김치냉장고, 대형냉장고 and 시신보관냉장고, and `프린터` returns
    잉크젯프린터 alongside 레이저프린터. A verified mapping names one classification, so
    records carrying a different `dtilPrdctClsfcNo` are a broader query artefact and are dropped
    here rather than being narrowed later by model tokens alone.

    A record without a classification code cannot be shown to belong to the mapping, so it is
    dropped too.
    """

    expected = (mapping.detail_product_code or "").strip()
    if not expected:
        raise G2BMappingError(
            f"cannot enforce classification without a mapped code: {mapping.model_name!r}"
        )
    return [
        dict(record)
        for record in records
        if str(record.get("dtilPrdctClsfcNo") or "").strip() == expected
    ]
