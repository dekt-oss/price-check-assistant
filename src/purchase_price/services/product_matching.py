from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text

DEFAULT_MANUFACTURER_ALIAS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "manufacturer_aliases.csv"
)

# G2B 목록정보 공식 품목 상세에서 상품원산지국가명 중국(CN)/베트남(VN)이
# 품목명의 모델 앞에 `(CN)`/`(VN)`으로 반복 표기되는 것을 검증했다. 이 두 값만
# G2B parser가 원산지 메타데이터로 확인한다. Generic ProductIdentity의 qualifier 문자열만으로
# 신뢰하지 않으며, 다른 qualifier는 계속 fail-closed한다.
VERIFIED_G2B_ORIGIN_QUALIFIERS = frozenset({"CN", "VN"})


@dataclass(frozen=True)
class ProductIdentity:
    product_name: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    specification: str | None = None
    source_title: str | None = None
    # Leading parenthesised qualifiers observed in live G2B titles, e.g. `(VN)NT960XHA-KG71G`
    # or `(주문자상표부착)삼성전자`. Their business meaning is interpreted only when separately
    # verified from public G2B evidence; otherwise they remain conservative blockers.
    manufacturer_qualifier: str | None = None
    model_qualifier: str | None = None
    model_qualifier_verified_as_origin: bool = False


_LEADING_QUALIFIER_PATTERN = re.compile(r"^\((?P<qualifier>[^()]{1,30})\)\s*(?P<rest>\S.*)$")


@dataclass(frozen=True)
class _SpecMeasurement:
    family: str
    value: Decimal


_SPEC_MEASUREMENT_PATTERN = re.compile(
    r"(?<![a-z0-9])(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>ml|l|kv|v|kw|w|tb|gb|개입|ea|pcs|pack|팩|세트|set)(?![a-z0-9])",
    re.IGNORECASE,
)


def split_leading_qualifier(value: str | None) -> tuple[str | None, str | None]:
    """Split `(qualifier)token` into (`qualifier`, `token`) without interpreting the qualifier."""

    if not value:
        return None, value
    text = value.strip()
    match = _LEADING_QUALIFIER_PATTERN.match(text)
    if match is None:
        return None, text
    return match.group("qualifier").strip(), match.group("rest").strip()


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


def _model_state(
    query_model: str | None,
    candidate_model: str | None,
    candidate_qualifier: str | None = None,
    *,
    candidate_qualifier_verified_as_origin: bool = False,
) -> str:
    query_key = normalize_text(query_model)
    candidate_key = normalize_text(candidate_model)
    if not query_key:
        return "not_requested"
    if not candidate_key:
        return "missing"
    if query_key == candidate_key:
        if candidate_qualifier:
            if candidate_qualifier_verified_as_origin:
                return "exact_with_verified_origin"
            return "exact_with_unverified_qualifier"
        return "exact"
    return "conflict"


def _manufacturer_state(
    query_manufacturer: str | None,
    candidate_manufacturer: str | None,
    aliases: dict[str, str],
    candidate_qualifier: str | None = None,
) -> str:
    query_key = canonical_manufacturer(query_manufacturer, aliases)
    candidate_key = canonical_manufacturer(candidate_manufacturer, aliases)
    if query_key is None:
        return "not_requested"
    if candidate_key is None:
        return "missing"
    if query_key == candidate_key:
        if candidate_qualifier:
            return "alias_with_unverified_qualifier"
        return "exact_or_alias"
    return "conflict"


def _spec_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    normalized = value.casefold()
    tokens = re.findall(
        r"[a-z]+[0-9]+[a-z0-9.-]*|[0-9]+(?:\.[0-9]+)?[a-z]*|[a-z가-힣]{2,}",
        normalized,
    )
    return tuple(dict.fromkeys(token for token in tokens if len(token) > 1))


def _measurement(unit: str, value: Decimal) -> _SpecMeasurement:
    normalized_unit = unit.casefold()
    if normalized_unit == "ml":
        return _SpecMeasurement("volume_ml", value)
    if normalized_unit == "l":
        return _SpecMeasurement("volume_ml", value * Decimal("1000"))
    if normalized_unit == "v":
        return _SpecMeasurement("voltage_v", value)
    if normalized_unit == "kv":
        return _SpecMeasurement("voltage_v", value * Decimal("1000"))
    if normalized_unit == "w":
        return _SpecMeasurement("power_w", value)
    if normalized_unit == "kw":
        return _SpecMeasurement("power_w", value * Decimal("1000"))
    # GB and TB are kept separate. A candidate listing only RAM in GB must not be treated as
    # contradictory evidence for a query's disk size in TB (or vice versa).
    if normalized_unit == "gb":
        return _SpecMeasurement("storage_gb", value)
    if normalized_unit == "tb":
        return _SpecMeasurement("storage_tb", value)
    return _SpecMeasurement("package_count", value)


def _spec_measurements(value: str | None) -> tuple[_SpecMeasurement, ...]:
    if not value:
        return ()
    measurements: list[_SpecMeasurement] = []
    for match in _SPEC_MEASUREMENT_PATTERN.finditer(value.casefold()):
        measurements.append(
            _measurement(match.group("unit"), Decimal(match.group("value")))
        )
    return tuple(measurements)


def _has_explicit_measurement_conflict(query_spec: str | None, candidate_text: str) -> bool:
    """Return true only for an unambiguous numeric/unit contradiction.

    A query with multiple measurement families (for example `32GB 1TB`) can describe several
    different components, so a partial candidate specification must not be promoted to an explicit
    conflict without role-aware parsing. The strict X path is therefore opened only when the query
    contains one safely-normalized measurement family. The candidate must state the same family and
    all its stated values must contradict the query value(s). Missing measurements remain incomplete.
    """

    query_measurements = _spec_measurements(query_spec)
    candidate_measurements = _spec_measurements(candidate_text)
    if not query_measurements or not candidate_measurements:
        return False

    query_families = {measurement.family for measurement in query_measurements}
    if len(query_families) != 1:
        return False
    family = next(iter(query_families))

    query_values = {
        measurement.value for measurement in query_measurements if measurement.family == family
    }
    candidate_values = {
        measurement.value for measurement in candidate_measurements if measurement.family == family
    }
    return bool(candidate_values and query_values.isdisjoint(candidate_values))


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
    if _has_explicit_measurement_conflict(query.specification, candidate_text):
        return "explicit_conflict"
    if all(token in candidate_tokens for token in query_tokens):
        return "compatible"
    return "different_or_incomplete"


def _product_class_state(query_name: str | None, candidate_name: str | None) -> str:
    """Only a normalized exact product-class match counts as compatible.

    A substring relation (`모니터` in `심전도모니터`, `프린터` in `레이저프린터`) is not evidence
    that two products belong to the same class: the longer label is usually a narrower or simply
    unrelated class that happens to share a suffix. Treating it as compatible would let a
    model-less query promote an unrelated product to a reference-only C candidate. Such pairs are
    reported as `related_unverified` so a reviewer can see the near miss, but they never satisfy
    the C requirement. Genuine hierarchy/synonym relations must come from a separately verified
    alias registry, not from string containment.
    """

    query_key = normalize_text(query_name)
    candidate_key = normalize_text(candidate_name)
    if not query_key:
        return "not_requested"
    if not candidate_key:
        return "missing"
    if query_key == candidate_key:
        return "compatible"
    if query_key in candidate_key or candidate_key in query_key:
        return "related_unverified"
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
    candidate. Missing or merely incomplete specification evidence downgrades the same model to B,
    but an explicit numeric/unit specification contradiction fails closed to X because B evidence
    can enter the observed direct-price range. Any explicit manufacturer/model conflict also fails
    closed to X. C is a reference-only class match and requires more than a bare class label when
    the query asks for a specific model, plus a normalized *exact* product-class match; a mere
    substring relation between the two class labels never satisfies C. D is emitted only for an
    explicit curated functional alternative.

    A model token that matches only after removing an unverified leading qualifier stays X. The
    qualifier is surfaced for human review instead of being reported as a model conflict. The G2B
    parser can mark `(CN)` and `(VN)` as verified origin-country metadata after official evidence;
    only that parser-derived flag preserves model identity. A generic qualifier string alone cannot
    unlock A/B. A manufacturer that matches only after removing a qualifier such as
    `(주문자상표부착)` counts as incomplete manufacturer evidence and caps the grade at B.
    """

    aliases = (
        manufacturer_aliases
        if manufacturer_aliases is not None
        else load_manufacturer_aliases()
    )
    model_state = _model_state(
        query.model_name,
        candidate.model_name,
        candidate.model_qualifier,
        candidate_qualifier_verified_as_origin=candidate.model_qualifier_verified_as_origin,
    )
    manufacturer_state = _manufacturer_state(
        query.manufacturer,
        candidate.manufacturer,
        aliases,
        candidate.manufacturer_qualifier,
    )
    specification_state = _specification_state(query, candidate)
    product_state = _product_class_state(query.product_name, candidate.product_name)

    if (
        model_state == "conflict"
        or manufacturer_state == "conflict"
        or specification_state == "explicit_conflict"
    ):
        grade = MatchGrade.X
    elif model_state == "exact_with_unverified_qualifier":
        grade = MatchGrade.X
    elif model_state in {"exact", "exact_with_verified_origin"}:
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
    if candidate.model_qualifier:
        note += f"; model_qualifier={candidate.model_qualifier}"
    if candidate.manufacturer_qualifier:
        note += f"; manufacturer_qualifier={candidate.manufacturer_qualifier}"
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

    Leading parenthesised qualifiers seen in live titles (`(VN)NT960XHA-KG71G`,
    `(주문자상표부착)삼성전자`) are split off. Only model qualifiers whose G2B meaning has been
    independently verified as origin metadata are marked trusted by this G2B-specific parser.
    """

    if not title:
        return ProductIdentity(source_title=title)

    parts = [part.strip() for part in title.split(",") if part.strip()]
    if not parts:
        return ProductIdentity(source_title=title)

    product_name = parts[0]
    manufacturer_qualifier, manufacturer = (
        split_leading_qualifier(parts[1]) if len(parts) >= 3 else (None, None)
    )
    model_qualifier, model_name = (
        split_leading_qualifier(parts[2]) if len(parts) >= 3 else (None, None)
    )
    verified_origin = bool(
        model_qualifier
        and model_qualifier.strip().upper() in VERIFIED_G2B_ORIGIN_QUALIFIERS
    )
    specification = ", ".join(parts[3:]) if len(parts) >= 4 else None
    return ProductIdentity(
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
        source_title=title,
        manufacturer_qualifier=manufacturer_qualifier,
        model_qualifier=model_qualifier,
        model_qualifier_verified_as_origin=verified_origin,
    )
