from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from purchase_price.domain import (
    DIRECT_PRICE_EVIDENCE_TYPES,
    ComparisonScope,
    MatchGrade,
)
from purchase_price.schemas import CollectedPrice

SUPPORTED_COMPARISON_CURRENCY = "KRW"


@dataclass(frozen=True)
class PriceAssessment:
    observed_count: int
    source_count: int
    low: Decimal | None
    median: Decimal | None
    high: Decimal | None
    quote_comparable_count: int
    quote_comparable_low: Decimal | None
    quote_comparable_median: Decimal | None
    quote_comparable_high: Decimal | None
    confidence: str
    quote_position: str | None
    difference_rate: Decimal | None
    message: str

    @property
    def comparable_count(self) -> int:
        """Backward-compatible alias for the number of observed direct price records."""

        return self.observed_count


def _is_valid_positive_price(item: CollectedPrice) -> bool:
    return item.price.is_finite() and item.price > 0


def _is_observed_direct(item: CollectedPrice) -> bool:
    return (
        item.match_grade in {MatchGrade.A, MatchGrade.B}
        and item.evidence_type in DIRECT_PRICE_EVIDENCE_TYPES
        and item.currency.strip().upper() == SUPPORTED_COMPARISON_CURRENCY
        and item.comparison_scope
        in {ComparisonScope.OBSERVED_ONLY, ComparisonScope.QUOTE_COMPARABLE}
        and _is_valid_positive_price(item)
    )


def _is_quote_comparable(item: CollectedPrice) -> bool:
    return _is_observed_direct(item) and item.comparison_scope == ComparisonScope.QUOTE_COMPARABLE


def _prices(items: list[CollectedPrice], *, quote_comparable: bool) -> list[Decimal]:
    predicate = _is_quote_comparable if quote_comparable else _is_observed_direct
    return [item.price for item in items if predicate(item)]


def _source_key(item: CollectedPrice) -> tuple[str, str]:
    return item.source_type.value, item.source_name.strip().casefold()


def _confidence(items: list[CollectedPrice]) -> tuple[str, int]:
    direct_items = [item for item in items if _is_observed_direct(item)]
    source_count = len({_source_key(item) for item in direct_items})
    a_count = sum(item.match_grade == MatchGrade.A for item in direct_items)
    direct = len(direct_items)

    # Repeated transactions from one source are useful evidence, but they are not independent
    # corroboration. High confidence therefore requires at least two independent sources.
    if a_count >= 2 and direct >= 3 and source_count >= 2:
        return "높음", source_count
    if (direct >= 2 and source_count >= 2) or a_count >= 1:
        return "보통", source_count
    if direct >= 1 or any(item.match_grade in {MatchGrade.C, MatchGrade.D} for item in items):
        return "낮음", source_count
    return "산정불가", source_count


def _range(values: list[Decimal]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if not values:
        return None, None, None
    ordered = sorted(values)
    return ordered[0], Decimal(str(median(ordered))), ordered[-1]


def assess_prices(
    items: list[CollectedPrice], current_quote: Decimal | None = None
) -> PriceAssessment:
    observed = _prices(items, quote_comparable=False)
    observed_low, observed_median, observed_high = _range(observed)
    quote_comparable = _prices(items, quote_comparable=True)
    quote_low, quote_median, quote_high = _range(quote_comparable)
    confidence, source_count = _confidence(items)

    if not observed:
        return PriceAssessment(
            observed_count=0,
            source_count=source_count,
            low=None,
            median=None,
            high=None,
            quote_comparable_count=0,
            quote_comparable_low=None,
            quote_comparable_median=None,
            quote_comparable_high=None,
            confidence=confidence,
            quote_position=None,
            difference_rate=None,
            message="직접 비교 가능한 가격자료가 충분하지 않아 관측가격대 산정 불가.",
        )

    if current_quote is None:
        return PriceAssessment(
            observed_count=len(observed),
            source_count=source_count,
            low=observed_low,
            median=observed_median,
            high=observed_high,
            quote_comparable_count=len(quote_comparable),
            quote_comparable_low=quote_low,
            quote_comparable_median=quote_median,
            quote_comparable_high=quote_high,
            confidence=confidence,
            quote_position=None,
            difference_rate=None,
            message="직접 가격근거의 확인 가능한 관측범위를 표시함. 거래조건 동일성은 별도 확인 필요.",
        )

    if not quote_comparable or quote_low is None or quote_high is None:
        return PriceAssessment(
            observed_count=len(observed),
            source_count=source_count,
            low=observed_low,
            median=observed_median,
            high=observed_high,
            quote_comparable_count=0,
            quote_comparable_low=None,
            quote_comparable_median=None,
            quote_comparable_high=None,
            confidence=confidence,
            quote_position=None,
            difference_rate=None,
            message=(
                "직접 가격근거는 관측됐지만 VAT·단위·배송·설치·옵션·보증 등 비교조건이 "
                "충분히 검증되지 않아 현재 견적의 높고 낮음을 판정하지 않음."
            ),
        )

    if current_quote > quote_high:
        rate = (current_quote - quote_high) / quote_high * Decimal(100)
        message = f"현재 견적은 조건비교 가능한 가격자료 상단보다 {rate:.1f}% 높음."
        position = "상단 초과"
    elif current_quote < quote_low:
        rate = (quote_low - current_quote) / quote_low * Decimal(100)
        message = f"현재 견적은 조건비교 가능한 가격자료 하단보다 {rate:.1f}% 낮음."
        position = "하단 미만"
    else:
        rate = Decimal(0)
        message = "현재 견적은 조건비교 가능한 가격자료 범위 내에 위치함."
        position = "범위 내"

    return PriceAssessment(
        observed_count=len(observed),
        source_count=source_count,
        low=observed_low,
        median=observed_median,
        high=observed_high,
        quote_comparable_count=len(quote_comparable),
        quote_comparable_low=quote_low,
        quote_comparable_median=quote_median,
        quote_comparable_high=quote_high,
        confidence=confidence,
        quote_position=position,
        difference_rate=rate,
        message=message,
    )
