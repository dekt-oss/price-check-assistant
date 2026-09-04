from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from purchase_price.schemas import CollectedPrice

UNKNOWN = "미확인"


def _is_complete_value(value: str) -> bool:
    return bool(value) and UNKNOWN not in value


@dataclass(frozen=True)
class PriceConditionProfile:
    vat: str
    quantity_unit: str
    delivery: str
    installation: str
    options: str
    warranty: str
    maintenance: str
    basis_date: str

    @property
    def known_count(self) -> int:
        return sum(
            _is_complete_value(value)
            for value in (
                self.vat,
                self.quantity_unit,
                self.delivery,
                self.installation,
                self.options,
                self.warranty,
                self.maintenance,
                self.basis_date,
            )
        )

    @property
    def total_count(self) -> int:
        return 8

    @property
    def completeness_percent(self) -> int:
        return round(self.known_count / self.total_count * 100)

    @property
    def missing_labels(self) -> tuple[str, ...]:
        values = (
            ("VAT", self.vat),
            ("수량·단위", self.quantity_unit),
            ("배송", self.delivery),
            ("설치", self.installation),
            ("옵션", self.options),
            ("보증", self.warranty),
            ("유지보수", self.maintenance),
            ("거래/기준일", self.basis_date),
        )
        return tuple(label for label, value in values if not _is_complete_value(value))


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _explicit_condition(conditions: str | None, labels: tuple[str, ...]) -> str:
    text = (conditions or "").strip()
    if not text:
        return UNKNOWN

    # Prefer structured `label=value` evidence already preserved by collectors.
    for label in labels:
        pattern = re.compile(rf"(?:^|;)\s*{re.escape(label)}\s*=\s*([^;]+)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if value:
                return value

    # Accept only explicit commercial-condition phrases. Do not infer from generic prose.
    lowered = text.casefold()
    for keyword in labels:
        keyword_lower = keyword.casefold()
        for suffix in (" 포함", " 별도", " 없음", " 무료"):
            phrase = keyword_lower + suffix
            if phrase in lowered:
                return phrase.strip()
    return UNKNOWN


def build_price_condition_profile(item: CollectedPrice) -> PriceConditionProfile:
    if item.quantity is not None and item.unit:
        quantity_unit = f"{_format_decimal(item.quantity)} {item.unit}"
    elif item.quantity is not None:
        quantity_unit = f"수량 {_format_decimal(item.quantity)} · 단위 미확인"
    elif item.unit:
        quantity_unit = f"수량 미확인 · {item.unit}"
    else:
        quantity_unit = UNKNOWN

    if item.transaction_date is not None:
        basis_date = f"거래일 {item.transaction_date.isoformat()}"
    elif item.collected_at is not None:
        basis_date = f"수집/검증일 {item.collected_at.isoformat()}"
    else:
        basis_date = UNKNOWN

    return PriceConditionProfile(
        vat=(item.vat_status or "").strip() or UNKNOWN,
        quantity_unit=quantity_unit,
        delivery=_explicit_condition(item.conditions, ("배송비", "배송", "납품조건")),
        installation=_explicit_condition(item.conditions, ("설치비", "설치")),
        options=_explicit_condition(item.conditions, ("옵션", "부속품", "구성")),
        warranty=_explicit_condition(item.conditions, ("보증", "보증기간", "무상보증")),
        maintenance=_explicit_condition(
            item.conditions,
            ("유지보수", "서비스계약", "서비스", "maintenance"),
        ),
        basis_date=basis_date,
    )
