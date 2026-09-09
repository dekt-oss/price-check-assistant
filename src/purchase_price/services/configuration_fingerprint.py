from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.product_matching import (
    ProductIdentity,
    canonical_manufacturer,
    grade_product_identity,
)
from purchase_price.services.quote_condition_comparison import (
    ConditionComparisonStatus,
    QuoteConditionProfile,
    compare_quote_to_evidence_conditions,
)


class ConfigurationAxisStatus(StrEnum):
    MATCH = "일치"
    CONFLICT = "충돌"
    UNKNOWN = "미확인"


@dataclass(frozen=True)
class ConfigurationAxisComparison:
    key: str
    label: str
    quote_value: str
    evidence_value: str
    status: ConfigurationAxisStatus
    required: bool = True


@dataclass(frozen=True)
class ConfigurationFingerprintComparison:
    axes: tuple[ConfigurationAxisComparison, ...]

    @property
    def conflict_axes(self) -> tuple[ConfigurationAxisComparison, ...]:
        return tuple(
            axis
            for axis in self.axes
            if axis.required and axis.status == ConfigurationAxisStatus.CONFLICT
        )

    @property
    def unknown_axes(self) -> tuple[ConfigurationAxisComparison, ...]:
        return tuple(
            axis
            for axis in self.axes
            if axis.required and axis.status == ConfigurationAxisStatus.UNKNOWN
        )

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        reasons = [f"{axis.label} 충돌" for axis in self.conflict_axes]
        reasons.extend(f"{axis.label} 미확인" for axis in self.unknown_axes)
        return tuple(reasons)

    @property
    def ready_for_quote_comparison(self) -> bool:
        return not self.blocking_reasons

    def axis(self, key: str) -> ConfigurationAxisComparison:
        for axis in self.axes:
            if axis.key == key:
                return axis
        raise KeyError(key)


_UNKNOWN = "미확인"

# These are deliberately tiny, high-precision mutually-exclusive families. They are not a synonym
# engine. A conflict is emitted only when both sides explicitly state different members of the same
# family. Ambiguous or missing prose remains UNKNOWN instead of being guessed.
_EXCLUSIVE_CONFIGURATION_FAMILIES: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    (
        "incubator_jacket",
        (
            ("water jacket", "water-jacket", "waterjacket", "워터 재킷", "워터재킷", "수조식"),
            ("air jacket", "air-jacket", "airjacket", "에어 재킷", "에어재킷"),
        ),
    ),
    (
        "anesthetic_agent",
        (
            ("desflurane", "데스플루란", "데스플루레인"),
            ("sevoflurane", "세보플루란", "세보플루레인"),
            ("isoflurane", "이소플루란", "이소플루레인"),
        ),
    ),
)


def _display(value: object) -> str:
    text = str(value or "").strip()
    return text or _UNKNOWN


def _normalize_phrase(value: str | None) -> str:
    return re.sub(r"[\s_./()\-]+", "", (value or "").casefold())


def _explicit_family_member(value: str | None, members: tuple[tuple[str, ...], ...]) -> int | None:
    normalized = _normalize_phrase(value)
    if not normalized:
        return None
    matches: list[int] = []
    for index, aliases in enumerate(members):
        if any(_normalize_phrase(alias) in normalized for alias in aliases):
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def _has_mutually_exclusive_configuration_conflict(
    quote_value: str | None,
    evidence_value: str | None,
) -> bool:
    for _family_name, members in _EXCLUSIVE_CONFIGURATION_FAMILIES:
        quote_member = _explicit_family_member(quote_value, members)
        evidence_member = _explicit_family_member(evidence_value, members)
        if quote_member is not None and evidence_member is not None and quote_member != evidence_member:
            return True
    return False


def _identity_axis(
    *,
    key: str,
    label: str,
    quote_value: str | None,
    evidence_value: str | None,
    canonicalize: bool = False,
) -> ConfigurationAxisComparison:
    quote_text = (quote_value or "").strip()
    evidence_text = (evidence_value or "").strip()
    required = bool(quote_text)
    if not quote_text:
        status = ConfigurationAxisStatus.UNKNOWN
    elif not evidence_text:
        status = ConfigurationAxisStatus.UNKNOWN
    else:
        if canonicalize:
            quote_key = canonical_manufacturer(quote_text)
            evidence_key = canonical_manufacturer(evidence_text)
        else:
            quote_key = normalize_text(quote_text)
            evidence_key = normalize_text(evidence_text)
        status = (
            ConfigurationAxisStatus.MATCH
            if quote_key and quote_key == evidence_key
            else ConfigurationAxisStatus.CONFLICT
        )
    return ConfigurationAxisComparison(
        key=key,
        label=label,
        quote_value=_display(quote_text),
        evidence_value=_display(evidence_text),
        status=status,
        required=required,
    )


def _specification_axis(
    quote_identity: ProductQuery,
    evidence: CollectedPrice,
) -> ConfigurationAxisComparison:
    quote_spec = (quote_identity.specification or "").strip()
    evidence_spec = (evidence.specification or "").strip()
    required = bool(quote_spec)

    if not quote_spec or not evidence_spec:
        status = ConfigurationAxisStatus.UNKNOWN
    elif normalize_text(quote_spec) == normalize_text(evidence_spec):
        # Product matching intentionally strips model tokens from specifications. If both source
        # documents explicitly repeat the same model/configuration text, equality itself confirms
        # this fingerprint axis even when the broader matcher reports `not_provided`.
        status = ConfigurationAxisStatus.MATCH
    elif _has_mutually_exclusive_configuration_conflict(quote_spec, evidence_spec):
        status = ConfigurationAxisStatus.CONFLICT
    else:
        decision = grade_product_identity(
            quote_identity,
            ProductIdentity(
                product_name=evidence.product_name,
                manufacturer=evidence.manufacturer,
                model_name=evidence.model_name,
                specification=evidence.specification,
                source_title=evidence.original_title,
            ),
        )
        if decision.specification_state == "compatible":
            status = ConfigurationAxisStatus.MATCH
        elif decision.specification_state == "explicit_conflict":
            status = ConfigurationAxisStatus.CONFLICT
        else:
            # `different_or_incomplete` is deliberately not upgraded to conflict. It can mean a
            # partial source description. For quote-position use it is still insufficient and must
            # be resolved by the operator/source evidence first.
            status = ConfigurationAxisStatus.UNKNOWN

    return ConfigurationAxisComparison(
        key="specification",
        label="핵심 규격·구성",
        quote_value=_display(quote_spec),
        evidence_value=_display(evidence_spec),
        status=status,
        required=required,
    )


def _quantity_unit_axis(
    quote_quantity: Decimal | None,
    quote_unit: str,
    evidence: CollectedPrice,
) -> ConfigurationAxisComparison:
    quote_unit_text = (quote_unit or "").strip()
    evidence_unit_text = (evidence.unit or "").strip()
    quote_value = (
        f"{quote_quantity} {quote_unit_text}".strip() if quote_quantity is not None else quote_unit_text
    )
    evidence_value = (
        f"{evidence.quantity} {evidence_unit_text}".strip()
        if evidence.quantity is not None
        else evidence_unit_text
    )
    required = quote_quantity is not None or bool(quote_unit_text)
    if quote_quantity is None or evidence.quantity is None or not quote_unit_text or not evidence_unit_text:
        status = ConfigurationAxisStatus.UNKNOWN
    elif quote_quantity != evidence.quantity:
        status = ConfigurationAxisStatus.CONFLICT
    elif _normalize_phrase(quote_unit_text) != _normalize_phrase(evidence_unit_text):
        status = ConfigurationAxisStatus.CONFLICT
    else:
        status = ConfigurationAxisStatus.MATCH
    return ConfigurationAxisComparison(
        key="quantity_unit",
        label="수량·단위",
        quote_value=_display(quote_value),
        evidence_value=_display(evidence_value),
        status=status,
        required=required,
    )


def _commercial_axes(
    quote_conditions: QuoteConditionProfile,
    evidence: CollectedPrice,
) -> tuple[ConfigurationAxisComparison, ...]:
    comparison = compare_quote_to_evidence_conditions(
        quote_conditions,
        build_price_condition_profile(evidence),
    )
    key_by_label = {
        "VAT": "vat",
        "배송": "delivery",
        "설치": "installation",
        "옵션": "options",
        "보증": "warranty",
        "유지보수": "maintenance",
    }
    status_map = {
        ConditionComparisonStatus.MATCH: ConfigurationAxisStatus.MATCH,
        ConditionComparisonStatus.CONFLICT: ConfigurationAxisStatus.CONFLICT,
        ConditionComparisonStatus.UNKNOWN: ConfigurationAxisStatus.UNKNOWN,
    }
    return tuple(
        ConfigurationAxisComparison(
            key=key_by_label[item.label],
            label=item.label,
            quote_value=item.quote_value,
            evidence_value=item.evidence_value,
            status=status_map[item.status],
            required=True,
        )
        for item in comparison.comparisons
    )


def compare_quote_evidence_configuration(
    *,
    quote_identity: ProductQuery | None,
    quote_quantity: Decimal | None,
    quote_unit: str,
    quote_conditions: QuoteConditionProfile,
    evidence: CollectedPrice,
) -> ConfigurationFingerprintComparison:
    """Build a reviewable product/configuration fingerprint for one quote/evidence pair.

    The fingerprint does not promote evidence or change match grades. It only makes exact-model
    comparison stricter by surfacing the axes that actually define the purchased configuration.
    Missing quote identity fields are informational UNKNOWN axes; a field explicitly present on the
    quote becomes required and therefore blocks quote-position use when the public evidence cannot
    confirm it.
    """

    axes: list[ConfigurationAxisComparison] = []
    if quote_identity is not None:
        axes.extend(
            (
                _identity_axis(
                    key="manufacturer",
                    label="제조사",
                    quote_value=quote_identity.manufacturer,
                    evidence_value=evidence.manufacturer,
                    canonicalize=True,
                ),
                _identity_axis(
                    key="model",
                    label="모델",
                    quote_value=quote_identity.model_name,
                    evidence_value=evidence.model_name,
                ),
                _specification_axis(quote_identity, evidence),
            )
        )

    axes.append(_quantity_unit_axis(quote_quantity, quote_unit, evidence))
    axes.extend(_commercial_axes(quote_conditions, evidence))
    return ConfigurationFingerprintComparison(axes=tuple(axes))
