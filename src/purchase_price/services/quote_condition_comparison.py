from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from purchase_price.services.price_conditions import PriceConditionProfile, UNKNOWN


class ConditionComparisonStatus(StrEnum):
    MATCH = "일치"
    CONFLICT = "충돌"
    UNKNOWN = "미확인"


@dataclass(frozen=True)
class QuoteConditionProfile:
    vat: str = UNKNOWN
    delivery: str = UNKNOWN
    installation: str = UNKNOWN
    options: str = UNKNOWN
    warranty: str = UNKNOWN
    maintenance: str = UNKNOWN


@dataclass(frozen=True)
class ConditionComparison:
    label: str
    quote_value: str
    evidence_value: str
    status: ConditionComparisonStatus


@dataclass(frozen=True)
class QuoteEvidenceConditionComparison:
    comparisons: tuple[ConditionComparison, ...]

    @property
    def match_count(self) -> int:
        return sum(item.status == ConditionComparisonStatus.MATCH for item in self.comparisons)

    @property
    def conflict_count(self) -> int:
        return sum(item.status == ConditionComparisonStatus.CONFLICT for item in self.comparisons)

    @property
    def unknown_count(self) -> int:
        return sum(item.status == ConditionComparisonStatus.UNKNOWN for item in self.comparisons)

    @property
    def status_label(self) -> str:
        if self.conflict_count:
            return "조건 충돌"
        if self.unknown_count:
            return "조건 확인 필요"
        return "조건 일치"

    @property
    def fully_aligned(self) -> bool:
        return bool(self.comparisons) and self.conflict_count == 0 and self.unknown_count == 0


def _clean(value: object) -> str:
    if value is None:
        return UNKNOWN
    text = str(value).strip()
    return text or UNKNOWN


def build_quote_condition_profile(
    *,
    vat: object = None,
    delivery: object = None,
    installation: object = None,
    options: object = None,
    warranty: object = None,
    maintenance: object = None,
) -> QuoteConditionProfile:
    return QuoteConditionProfile(
        vat=_clean(vat),
        delivery=_clean(delivery),
        installation=_clean(installation),
        options=_clean(options),
        warranty=_clean(warranty),
        maintenance=_clean(maintenance),
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"[\s,./()_-]+", "", value.casefold())


def _explicit_binary_state(value: str) -> str | None:
    normalized = _normalize_text(value)
    if not normalized or normalized == _normalize_text(UNKNOWN):
        return None
    # Negative expressions must be checked before the positive '포함' token.
    if any(token in normalized for token in ("미포함", "불포함", "해당없음", "없음")):
        return "none"
    if "별도" in normalized:
        return "separate"
    if any(token in normalized for token in ("무료", "무상")):
        return "free"
    if "포함" in normalized:
        return "included"
    return None


def _duration_months(value: str) -> int | None:
    normalized = value.casefold().replace(" ", "")
    year_match = re.search(r"(?P<value>\d+)년", normalized)
    if year_match:
        return int(year_match.group("value")) * 12
    month_match = re.search(r"(?P<value>\d+)개월", normalized)
    if month_match:
        return int(month_match.group("value"))
    return None


def _compare_value(label: str, quote_value: str, evidence_value: str) -> ConditionComparisonStatus:
    if UNKNOWN in quote_value or UNKNOWN in evidence_value:
        return ConditionComparisonStatus.UNKNOWN

    quote_binary = _explicit_binary_state(quote_value)
    evidence_binary = _explicit_binary_state(evidence_value)
    if quote_binary is not None and evidence_binary is not None:
        return (
            ConditionComparisonStatus.MATCH
            if quote_binary == evidence_binary
            else ConditionComparisonStatus.CONFLICT
        )

    if label == "보증":
        quote_months = _duration_months(quote_value)
        evidence_months = _duration_months(evidence_value)
        if quote_months is not None and evidence_months is not None:
            return (
                ConditionComparisonStatus.MATCH
                if quote_months == evidence_months
                else ConditionComparisonStatus.CONFLICT
            )

    quote_normalized = _normalize_text(quote_value)
    evidence_normalized = _normalize_text(evidence_value)
    if not quote_normalized or not evidence_normalized:
        return ConditionComparisonStatus.UNKNOWN
    return (
        ConditionComparisonStatus.MATCH
        if quote_normalized == evidence_normalized
        else ConditionComparisonStatus.CONFLICT
    )


def compare_quote_to_evidence_conditions(
    quote: QuoteConditionProfile,
    evidence: PriceConditionProfile,
) -> QuoteEvidenceConditionComparison:
    pairs = (
        ("VAT", quote.vat, evidence.vat),
        ("배송", quote.delivery, evidence.delivery),
        ("설치", quote.installation, evidence.installation),
        ("옵션", quote.options, evidence.options),
        ("보증", quote.warranty, evidence.warranty),
        ("유지보수", quote.maintenance, evidence.maintenance),
    )
    comparisons = tuple(
        ConditionComparison(
            label=label,
            quote_value=quote_value,
            evidence_value=evidence_value,
            status=_compare_value(label, quote_value, evidence_value),
        )
        for label, quote_value, evidence_value in pairs
    )
    return QuoteEvidenceConditionComparison(comparisons=comparisons)
