from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import (
    equivalent_model_keys,
    load_manufacturer_aliases,
    load_model_aliases,
)

_KOREAN_RE = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class UnifiedSearchInterpretation:
    raw_search: str
    product_name: str
    manufacturer: str
    model_name: str
    specification: str
    auto_hydrated_fields: tuple[str, ...] = ()
    mapping_status: str | None = None
    mapping_verified: bool = False
    matched_model: str | None = None
    manufacturer_source: str | None = None

    @property
    def auto_hydrated(self) -> bool:
        return bool(self.auto_hydrated_fields)

    @property
    def evidence_label(self) -> str:
        if self.mapping_verified:
            return "검증된 모델 매핑"
        if self.mapping_status:
            return "등록된 모델 검색 힌트"
        return "사용자 입력"


def _manufacturer_alias_is_safe_for_substring(alias_key: str) -> bool:
    if not alias_key:
        return False
    if _KOREAN_RE.search(alias_key):
        return len(alias_key) >= 3
    return len(alias_key) >= 4


def _manufacturer_from_text(
    raw_search: str,
    aliases: dict[str, str],
) -> tuple[str | None, str | None]:
    raw_key = normalize_text(raw_search)
    if not raw_key:
        return None, None

    matches: list[tuple[int, str, str]] = []
    for alias_key, canonical in aliases.items():
        if raw_key == alias_key:
            matches.append((10_000 + len(alias_key), canonical, alias_key))
            continue
        if not _manufacturer_alias_is_safe_for_substring(alias_key):
            continue
        if alias_key in raw_key:
            matches.append((len(alias_key), canonical, alias_key))

    if not matches:
        return None, None

    best_score = max(score for score, _, _ in matches)
    best = [(canonical, alias) for score, canonical, alias in matches if score == best_score]
    canonical_names = {canonical for canonical, _ in best}
    if len(canonical_names) != 1:
        return None, None
    canonical = next(iter(canonical_names))
    alias = next(alias for name, alias in best if name == canonical)
    return canonical, alias


def _mapping_score(
    raw_key: str,
    mapping: G2BProductMapping,
    model_aliases: dict[str, str],
) -> int:
    if not raw_key or not mapping.model_name:
        return 0

    model_keys = set(equivalent_model_keys(mapping.model_name, model_aliases))
    if raw_key in model_keys:
        return 100

    contained = [key for key in model_keys if len(key) >= 4 and key in raw_key]
    if contained:
        return 80 + min(max(len(key) for key in contained), 19)

    if len(raw_key) >= 5 and any(raw_key in key for key in model_keys):
        return 60 + min(len(raw_key), 19)

    return 0


def resolve_model_mapping_from_text(
    raw_search: str,
    *,
    mappings: Iterable[G2BProductMapping] | None = None,
    model_aliases: dict[str, str] | None = None,
) -> G2BProductMapping | None:
    raw_key = normalize_text(raw_search)
    if not raw_key:
        return None

    rows = tuple(mappings) if mappings is not None else load_g2b_product_mappings()
    aliases = model_aliases if model_aliases is not None else load_model_aliases()

    scored = [
        (_mapping_score(raw_key, mapping, aliases), mapping)
        for mapping in rows
        if mapping.model_name
    ]
    best_score = max((score for score, _ in scored), default=0)
    if best_score <= 0:
        return None

    best = [mapping for score, mapping in scored if score == best_score]
    unique_models = {normalize_text(mapping.model_name) for mapping in best}
    if len(best) != 1 or len(unique_models) != 1:
        return None
    return best[0]


def interpret_unified_search(
    *,
    search_text: str,
    product_name: str = "",
    manufacturer: str = "",
    model_name: str = "",
    specification: str = "",
    mappings: Iterable[G2BProductMapping] | None = None,
    manufacturer_aliases: dict[str, str] | None = None,
    model_aliases: dict[str, str] | None = None,
) -> UnifiedSearchInterpretation:
    raw = search_text.strip()
    resolved_product = product_name.strip()
    resolved_manufacturer = manufacturer.strip()
    resolved_model = model_name.strip()
    resolved_specification = specification.strip()
    hydrated: list[str] = []

    mapping: G2BProductMapping | None = None
    if raw and not resolved_model:
        mapping = resolve_model_mapping_from_text(
            raw,
            mappings=mappings,
            model_aliases=model_aliases,
        )
        if mapping is not None:
            resolved_model = mapping.model_name
            hydrated.append("model_name")
            if not resolved_product and mapping.product_name:
                resolved_product = mapping.product_name
                hydrated.append("product_name")

    manufacturer_source = None
    if raw and not resolved_manufacturer:
        aliases = (
            manufacturer_aliases
            if manufacturer_aliases is not None
            else load_manufacturer_aliases()
        )
        inferred_manufacturer, alias_key = _manufacturer_from_text(raw, aliases)
        if inferred_manufacturer:
            resolved_manufacturer = inferred_manufacturer
            manufacturer_source = alias_key
            hydrated.append("manufacturer")

    if not resolved_product:
        resolved_product = raw

    return UnifiedSearchInterpretation(
        raw_search=raw,
        product_name=resolved_product,
        manufacturer=resolved_manufacturer,
        model_name=resolved_model,
        specification=resolved_specification,
        auto_hydrated_fields=tuple(dict.fromkeys(hydrated)),
        mapping_status=mapping.mapping_status if mapping is not None else None,
        mapping_verified=bool(mapping and mapping.verified),
        matched_model=mapping.model_name if mapping is not None else None,
        manufacturer_source=manufacturer_source,
    )
