from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from purchase_price.scripts.collect_g2b_track_b_r2 import TARGET_SEGMENTS
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
)


@dataclass(frozen=True)
class SupplementalTarget:
    detail_product_code: str
    detail_product_name: str
    models: tuple[str, ...]
    segment: str


def supplemental_verified_targets(
    mappings: Iterable[G2BProductMapping] | None = None,
    *,
    base_segments: tuple[str, ...] = TARGET_SEGMENTS,
) -> tuple[SupplementalTarget, ...]:
    """Return verified G2B detail codes outside the pinned base Track B segments.

    This does not expand the 5,208-code historical snapshot. It only identifies explicit,
    evidence-backed detail codes that need a separate supplemental collection lane.
    """

    rows = tuple(mappings) if mappings is not None else load_g2b_product_mappings()
    grouped: dict[str, dict[str, object]] = {}
    for mapping in rows:
        if not mapping.verified or not mapping.detail_product_code or not mapping.detail_product_name:
            continue
        code = mapping.detail_product_code.strip()
        if len(code) != 10 or not code.isdigit():
            continue
        segment = code[:2]
        if segment in base_segments:
            continue
        entry = grouped.setdefault(
            code,
            {
                "detail_product_name": mapping.detail_product_name,
                "models": set(),
                "segment": segment,
            },
        )
        if entry["detail_product_name"] != mapping.detail_product_name:
            raise ValueError(f"supplemental code has conflicting names: {code}")
        models = entry["models"]
        assert isinstance(models, set)
        if mapping.model_name:
            models.add(mapping.model_name)

    return tuple(
        SupplementalTarget(
            detail_product_code=code,
            detail_product_name=str(grouped[code]["detail_product_name"]),
            models=tuple(sorted(grouped[code]["models"])),  # type: ignore[arg-type]
            segment=str(grouped[code]["segment"]),
        )
        for code in sorted(grouped)
    )


def supplemental_verified_codes(
    mappings: Iterable[G2BProductMapping] | None = None,
    *,
    base_segments: tuple[str, ...] = TARGET_SEGMENTS,
) -> tuple[str, ...]:
    return tuple(
        target.detail_product_code
        for target in supplemental_verified_targets(mappings, base_segments=base_segments)
    )
