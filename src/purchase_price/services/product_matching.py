from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text

DEFAULT_MANUFACTURER_ALIAS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "manufacturer_aliases.csv"
)


@dataclass(frozen=True)
class ProductIdentity:
    product_name: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    specification: str | None = None
    source_title: str | None = None


@dataclass(frozen=True)
class MatchDecision:
    grade: MatchGrade
    note: str
    model_state: str
    manufacturer_state: str
    specification_state: str


class ManufacturerAliasError(RuntimeError):
    pass


def load_manufacturer_aliases(
    path: Path = DEFAULT_MANUFACTURER_ALIAS_PATH,
) -> dict[str, str]:
    if not path.exists():
        raise ManufacturerAliasError(f"manufacturer alias registry not found: {path}")

    aliases: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"canonical_name", "alias"}.issubset(reader.fieldnames):
            raise ManufacturerAliasError("manufacturer alias registry is missing required columns")

        for row in reader:
            canonical = (row.get("canonical_name") or "").strip()
            alias = (row.get("alias") or "").strip()
            if not canonical or not alias:
                continue
            key = normalize_text(alias)
            existing = aliases.get(key)
            if existing is not None and existing != canonical:
                raise ManufacturerAliasError(
                    f"manufacturer alias maps to multiple canonical names: {alias!r}"
                )
            aliases[key] = canonical
    return aliases


def canonical_manufacturer(
    value: str | None,
    aliases: dict[str, str] | None = None,
) -> str | None:
    key = normalize_text(value)
    if not key:
        return None
    registry = aliases if aliases is not None else load_manufacturer_aliases()
    return registry.get(key, key)


def _model_state(query_model: str | None, candidate_model: str | None) -> str:
    query_key = normalize_text(query_model)
    candidate_key = normalize_text(candidate_model)
    if not query_key:
        return "not_requested"
    if not candidate_key:
        return "missing"
    if query_key == candidate_key:
        return "exact"
    return "conflict"


def _manufacturer_state(
    query_manufacturer: str | None,
    candidate_manufacturer: str | None,
    aliases: dict[str, str],
) -> str:
    query_key = canonical_manufacturer(query_manufacturer, aliases)
    candidate_key = canonical_manufacturer(candidate_manufacturer, aliases)
    if query_key is None:
        return "not_requested"
    if candidate_key is None:
        return "missing"
    if query_key == candidate_key:
        return "exact_or_alias"
    return "conflict"


def _spec_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    normalized = value.casefold()
    tokens = re.findall(r"[0-9]+(?:\.[0-9]+)?[a-z]*|[a-z가-힣]{2,}", normalized)
    return tuple(dict.fromkeys(token for token in tokens if len(token) > 1))


def _informative_query_spec_tokens(query: ProductQuery) -> tuple[str, ...]:
    specification_key = normalize_text(query.specification)
    model_key = normalize_text(query.model_name)
    if not specification_key:
        return ()
    if model_key and specification_key == model_key:
        return ()

    tokens = list(_spec_tokens(query.specification))
    if not model_key:
        return tuple(tokens)
    return tuple(token for token in tokens if normalize_text(token) != model_key)


def _specification_state(query: ProductQuery, candidate: ProductIdentity) -> str:
    query_tokens = _informative_query_spec_tokens(query)
    if not query_tokens:
        return "not_provided"

    candidate_text = " ".join(
        value for value in (candidate.specification, candidate.source_title) if value
    )
    candidate_tokens = set(_spec_tokens(candidate_text))
    if not candidate_tokens:
        return "missing"
    if all(token in candidate_tokens for token in query_tokens):
        return "compatible"
    return "different_or_incomplete"


def _product_class_state(query_name: str | None, candidate_name: str | None) -> str:
    query_key = normalize_text(query_name)
    candidate_key = normalize_text(candidate_name)
    if not query_key:
        return "not_requested"
    if not candidate_key:
        return "missing"
    if query_key == candidate_key or query_key in candidate_key or candidate_key in query_key:
        return "compatible"
    return "different"


def grade_product_identity(
    query: ProductQuery,
    candidate: ProductIdentity,
    *,
    manufacturer_aliases: dict[str, str] | None = None,
    functional_alternative: bool = False,
) -> MatchDecision:
    """Assign A/B/C/D/X conservatively.

    A/B require an exact normalized model match. A additionally requires verified manufacturer
    compatibility and informative specification evidence from the query to be present in the
    candidate. Missing manufacturer or specification evidence downgrades the same model to B.
    Any explicit manufacturer/model conflict fails closed to X. C is a reference-only class match
    and requires more than a bare class label when the query asks for a specific model. D is emitted
    only for an explicit curated functional alternative.
    """

    aliases = manufacturer_aliases if manufacturer_aliases is not None else load_manufacturer_aliases()
    model_state = _model_state(query.model_name, candidate.model_name)
    manufacturer_state = _manufacturer_state(query.manufacturer, candidate.manufacturer, aliases)
    specification_state = _specification_state(query, candidate)
    product_state = _product_class_state(query.product_name, candidate.product_name)

    if model_state == "conflict" or manufacturer_state == "conflict":
        grade = MatchGrade.X
    elif model_state == "exact":
        if manufacturer_state == "exact_or_alias" and specification_state == "compatible":
            grade = MatchGrade.A
        else:
            grade = MatchGrade.B
    elif functional_alternative:
        grade = MatchGrade.D
    elif product_state == "compatible" and (
        model_state == "not_requested" or manufacturer_state == "exact_or_alias"
    ):
        grade = MatchGrade.C
    else:
        grade = MatchGrade.X

    note = (
        f"grade={grade.value}; model={model_state}; manufacturer={manufacturer_state}; "
        f"specification={specification_state}; product_class={product_state}"
    )
    return MatchDecision(
        grade=grade,
        note=note,
        model_state=model_state,
        manufacturer_state=manufacturer_state,
        specification_state=specification_state,
    )


def parse_g2b_identity(title: str | None) -> ProductIdentity:
    """Parse the common comma-separated G2B product-identification title conservatively.

    Live examples observed in F1 use `제품군, 제조사, 모델, 사양...`. Records with fewer than
    three comma-separated components keep manufacturer/model unknown rather than guessing.
    """

    if not title:
        return ProductIdentity(source_title=title)

    parts = [part.strip() for part in title.split(",") if part.strip()]
    if not parts:
        return ProductIdentity(source_title=title)

    product_name = parts[0]
    manufacturer = parts[1] if len(parts) >= 3 else None
    model_name = parts[2] if len(parts) >= 3 else None
    specification = ", ".join(parts[3:]) if len(parts) >= 4 else None
    return ProductIdentity(
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
        source_title=title,
    )
