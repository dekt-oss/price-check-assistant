from datetime import date
from decimal import Decimal

import pytest

from purchase_price.domain import EvidenceType, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.evidence_freshness import (
    FreshnessStatus,
    evaluate_evidence_freshness,
)


def _evidence(**overrides: object) -> CollectedPrice:
    values: dict[str, object] = {
        "manufacturer": "예시",
        "product_name": "제품",
        "model_name": "M-1",
        "specification": None,
        "price": Decimal("1000"),
        "evidence_type": EvidenceType.PUBLIC_SALE_PRICE,
        "source_type": SourceType.MANUFACTURER,
        "source_name": "공식가격",
        "source_url": "https://example.invalid",
        "collected_at": date(2026, 7, 1),
    }
    values.update(overrides)
    return CollectedPrice(**values)  # type: ignore[arg-type]


def test_transaction_date_takes_precedence() -> None:
    result = evaluate_evidence_freshness(
        _evidence(transaction_date=date(2026, 6, 1)),
        as_of_date=date(2026, 9, 4),
        review_window_days=180,
    )

    assert result.basis_kind == "거래일"
    assert result.basis_date == date(2026, 6, 1)
    assert result.age_days == 95
    assert result.status == FreshnessStatus.WITHIN_REVIEW_WINDOW
    assert result.needs_review is False


def test_collection_date_is_used_when_transaction_date_missing() -> None:
    result = evaluate_evidence_freshness(
        _evidence(),
        as_of_date=date(2026, 9, 4),
        review_window_days=30,
    )

    assert result.basis_kind == "수집/검증일"
    assert result.age_days == 65
    assert result.status == FreshnessStatus.REVIEW_NEEDED
    assert result.needs_review is True


def test_future_date_is_explicit_error() -> None:
    result = evaluate_evidence_freshness(
        _evidence(transaction_date=date(2026, 9, 5)),
        as_of_date=date(2026, 9, 4),
        review_window_days=365,
    )

    assert result.age_days == -1
    assert result.status == FreshnessStatus.FUTURE_DATE


def test_review_window_is_caller_policy_not_hardcoded() -> None:
    evidence = _evidence(transaction_date=date(2026, 6, 1))

    short = evaluate_evidence_freshness(
        evidence,
        as_of_date=date(2026, 9, 4),
        review_window_days=90,
    )
    long = evaluate_evidence_freshness(
        evidence,
        as_of_date=date(2026, 9, 4),
        review_window_days=180,
    )

    assert short.status == FreshnessStatus.REVIEW_NEEDED
    assert long.status == FreshnessStatus.WITHIN_REVIEW_WINDOW


def test_non_positive_review_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        evaluate_evidence_freshness(
            _evidence(),
            as_of_date=date(2026, 9, 4),
            review_window_days=0,
        )
