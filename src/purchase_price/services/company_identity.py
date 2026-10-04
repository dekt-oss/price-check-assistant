from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from purchase_price.services.matching import normalize_text


class CompanyIdentityStatus(StrEnum):
    CONFIRMED_SAME = "CONFIRMED_SAME"
    NAME_SIMILAR_UNCONFIRMED = "NAME_SIMILAR_UNCONFIRMED"
    DIFFERENT = "DIFFERENT"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class CompanyIdentityDecision:
    status: CompanyIdentityStatus
    reason: str
    left_name: str
    right_name: str
    left_business_id: str | None = None
    right_business_id: str | None = None

    @property
    def confirmed_same(self) -> bool:
        return self.status == CompanyIdentityStatus.CONFIRMED_SAME


_COMPANY_PREFIXES = (
    "주식회사",
    "(주)",
    "㈜",
)


def normalize_business_id(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _valid_business_id(value: str) -> bool:
    return len(value) == 10 and value.isdigit()


def normalize_company_name_candidate(value: str | None) -> str:
    """Normalize a name only for candidate discovery, never for identity confirmation."""

    text = str(value or "").strip()
    for prefix in _COMPANY_PREFIXES:
        text = text.replace(prefix, "")
    return normalize_text(text)


def compare_company_identity(
    *,
    left_name: str | None,
    right_name: str | None,
    left_business_id: str | None = None,
    right_business_id: str | None = None,
) -> CompanyIdentityDecision:
    left = str(left_name or "").strip()
    right = str(right_name or "").strip()
    left_id = normalize_business_id(left_business_id)
    right_id = normalize_business_id(right_business_id)

    left_id_valid = _valid_business_id(left_id)
    right_id_valid = _valid_business_id(right_id)

    if left_id_valid and right_id_valid:
        if left_id == right_id:
            return CompanyIdentityDecision(
                status=CompanyIdentityStatus.CONFIRMED_SAME,
                reason="official_business_identifier_match",
                left_name=left,
                right_name=right,
                left_business_id=left_id,
                right_business_id=right_id,
            )
        return CompanyIdentityDecision(
            status=CompanyIdentityStatus.DIFFERENT,
            reason="official_business_identifier_conflict",
            left_name=left,
            right_name=right,
            left_business_id=left_id,
            right_business_id=right_id,
        )

    left_key = normalize_company_name_candidate(left)
    right_key = normalize_company_name_candidate(right)
    if not left_key or not right_key:
        return CompanyIdentityDecision(
            status=CompanyIdentityStatus.INSUFFICIENT,
            reason="company_name_or_official_identifier_missing",
            left_name=left,
            right_name=right,
            left_business_id=left_id or None,
            right_business_id=right_id or None,
        )

    if left_key == right_key:
        return CompanyIdentityDecision(
            status=CompanyIdentityStatus.NAME_SIMILAR_UNCONFIRMED,
            reason="normalized_name_match_without_official_identifier",
            left_name=left,
            right_name=right,
            left_business_id=left_id or None,
            right_business_id=right_id or None,
        )

    return CompanyIdentityDecision(
        status=CompanyIdentityStatus.DIFFERENT,
        reason="normalized_name_differs",
        left_name=left,
        right_name=right,
        left_business_id=left_id or None,
        right_business_id=right_id or None,
    )
