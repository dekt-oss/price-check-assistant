from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from purchase_price.schemas import CollectedPrice


class FreshnessStatus(StrEnum):
    WITHIN_REVIEW_WINDOW = "검토기한 이내"
    REVIEW_NEEDED = "재검토 필요"
    FUTURE_DATE = "미래일자 오류"


@dataclass(frozen=True)
class EvidenceFreshness:
    basis_date: date
    basis_kind: str
    as_of_date: date
    age_days: int
    review_window_days: int
    status: FreshnessStatus

    @property
    def needs_review(self) -> bool:
        return self.status != FreshnessStatus.WITHIN_REVIEW_WINDOW


def evaluate_evidence_freshness(
    evidence: CollectedPrice,
    *,
    as_of_date: date,
    review_window_days: int,
) -> EvidenceFreshness:
    """Describe evidence age against an explicit review policy.

    The window is supplied by the caller instead of being hard-coded as a market truth. A real
    transaction date takes precedence; otherwise the collector's verification/collection date is
    used. This helper labels age only and does not change MatchGrade, confidence, or
    ComparisonScope.
    """

    if review_window_days < 1:
        raise ValueError("review_window_days must be positive")

    if evidence.transaction_date is not None:
        basis_date = evidence.transaction_date
        basis_kind = "거래일"
    else:
        basis_date = evidence.collected_at
        basis_kind = "수집/검증일"

    age_days = (as_of_date - basis_date).days
    if age_days < 0:
        status = FreshnessStatus.FUTURE_DATE
    elif age_days <= review_window_days:
        status = FreshnessStatus.WITHIN_REVIEW_WINDOW
    else:
        status = FreshnessStatus.REVIEW_NEEDED

    return EvidenceFreshness(
        basis_date=basis_date,
        basis_kind=basis_kind,
        as_of_date=as_of_date,
        age_days=age_days,
        review_window_days=review_window_days,
        status=status,
    )
