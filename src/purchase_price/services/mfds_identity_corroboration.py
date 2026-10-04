"""Decide when an exact MFDS model match is too weak to confirm identity on its own.

The MFDS identity index matches models by normalized key (case and punctuation removed). The
2026-10-04 recall audit showed that short or numeric keys collide across unrelated products,
e.g. Heine ``G5`` -> a dental impression tray or Ferno ``125`` -> orthodontic forceps. For those
weak keys an exact match only confirms identity when the manufacturer/importer or the product
name agrees. Otherwise the match is shown as a candidate for the user to confirm instead of
silently rewriting the search.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import (
    canonical_manufacturer,
    load_manufacturer_aliases,
)

WEAK_KEY_SHAPES = frozenset({"digits_only", "unit_like", "short"})
_UNIT_KEY = re.compile(r"^\d+(ml|cc|cm|mm|g|kg|l|ea|oz|매|개|본)$")
_MIN_PRODUCT_KEY_LENGTH = 3
DEFAULT_IMPORTER_RELATIONS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "mfds_importer_relations.csv"
)


def model_key_shape(key: str) -> str:
    if key.isdigit():
        return "digits_only"
    if _UNIT_KEY.match(key):
        return "unit_like"
    if len(key) <= 4:
        return "short"
    if len(key) <= 6:
        return "length_5_6"
    return "distinctive"


def is_weak_model_key(value: str | None) -> bool:
    key = normalize_text(value)
    return bool(key) and model_key_shape(key) in WEAK_KEY_SHAPES


@lru_cache(maxsize=1)
def _manufacturer_aliases() -> dict[str, str]:
    return load_manufacturer_aliases()


@lru_cache(maxsize=1)
def load_importer_relations(
    path: Path = DEFAULT_IMPORTER_RELATIONS_PATH,
) -> frozenset[tuple[str, str]]:
    """(maker key, MFDS registered-company key) pairs with recorded evidence.

    These are kept separate from manufacturer aliases on purpose: an importer is a different
    legal entity and must not become a Track B manufacturer-matching alias.
    """

    if not path.exists():
        return frozenset()
    pairs: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            maker = normalize_text(row.get("manufacturer"))
            company = normalize_text(row.get("mfds_registered_company"))
            if maker and company:
                pairs.add((maker, company))
    return frozenset(pairs)


def _contains(left: str, right: str) -> bool:
    return bool(left and right and (left in right or right in left))


def company_corroborates(manufacturer: str | None, registered_company: str | None) -> bool:
    maker = normalize_text(manufacturer)
    company = normalize_text(registered_company)
    if len(maker) < 2 or not company:
        return False
    if _contains(maker, company):
        return True
    aliases = _manufacturer_aliases()
    maker_canonical = normalize_text(canonical_manufacturer(manufacturer, aliases))
    company_canonical = normalize_text(canonical_manufacturer(registered_company, aliases))
    if _contains(maker_canonical, company_canonical):
        return True
    return any(
        _contains(maker, related_maker) and _contains(company, related_company)
        for related_maker, related_company in load_importer_relations()
    )


def product_corroborates(product_name: str | None, mfds_product_name: str | None) -> bool:
    query = normalize_text(product_name)
    mfds = normalize_text(mfds_product_name)
    if len(query) < _MIN_PRODUCT_KEY_LENGTH or len(mfds) < _MIN_PRODUCT_KEY_LENGTH:
        return False
    return _contains(query, mfds)


def record_corroborated(
    record: Any,
    *,
    manufacturer: str | None,
    product_name: str | None,
) -> bool:
    return company_corroborates(
        manufacturer, getattr(record, "registered_company", None)
    ) or product_corroborates(product_name, getattr(record, "product_name", None))


def corroborated_records(
    records: Iterable[Any],
    *,
    manufacturer: str | None,
    product_name: str | None,
) -> tuple[Any, ...]:
    return tuple(
        record
        for record in records
        if record_corroborated(record, manufacturer=manufacturer, product_name=product_name)
    )


def identity_needs_review(
    identity: Any,
    *,
    manufacturer: str | None = None,
    product_name: str | None = None,
) -> bool:
    """True when a single-source exact *model* match rests only on a weak key.

    Works on old and new ``MfdsIdentityLookup`` objects (attribute access only), because
    Streamlit can keep a pre-change lookup class alive across hot reloads.
    """

    if str(getattr(identity, "status", "") or "") != "success":
        return False
    if str(getattr(identity, "match_type", "") or "") != "model":
        return False
    records = tuple(getattr(identity, "records", ()) or ())
    if not records:
        return False
    if not is_weak_model_key(str(getattr(identity, "query", "") or "")):
        return False
    return not corroborated_records(records, manufacturer=manufacturer, product_name=product_name)
