from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from purchase_price.domain import MatchGrade
from purchase_price.schemas import CollectedPrice


@dataclass(frozen=True)
class PriceAssessment:
    comparable_count: int
    low: Decimal | None
    median: Decimal | None
    high: Decimal | None
    confidence: str
    quote_position: str | None
    difference_rate: Decimal | None
    message: str


def _direct_prices(items: list[CollectedPrice]) -> list[Decimal]:
    return [x.price for x in items if x.match_grade in {MatchGrade.A, MatchGrade.B}]


def _confidence(items: list[CollectedPrice]) -> str:
    a_count = sum(x.match_grade == MatchGrade.A for x in items)
    b_count = sum(x.match_grade == MatchGrade.B for x in items)
    direct = a_count + b_count
    if a_count >= 2 and direct >= 3:
        return "높음"
    if direct >= 2 or a_count >= 1:
        return "보통"
    if any(x.match_grade in {MatchGrade.C, MatchGrade.D} for x in items):
        return "낮음"
    return "산정불가"


def assess_prices(items: list[CollectedPrice], current_quote: Decimal | None = None) -> PriceAssessment:
    direct = sorted(_direct_prices(items))
    confidence = _confidence(items)
    if not direct:
        return PriceAssessment(
            comparable_count=0,
            low=None,
            median=None,
            high=None,
            confidence=confidence,
            quote_position=None,
            difference_rate=None,
            message="직접 비교 가능한 가격자료가 충분하지 않아 참고가격대 산정 불가.",
        )

    low = direct[0]
    high = direct[-1]
    med = Decimal(str(median(direct)))

    if current_quote is None:
        return PriceAssessment(
            comparable_count=len(direct), low=low, median=med, high=high,
            confidence=confidence, quote_position=None, difference_rate=None,
            message="직접 비교자료의 확인 가능한 가격범위를 표시함.",
        )

    if current_quote > high:
        rate = (current_quote - high) / high * Decimal("100")
        message = f"현재 견적은 확보된 직접 비교자료 상단보다 {rate:.1f}% 높음. 조건 확인 필요."
        position = "상단 초과"
    elif current_quote < low:
        rate = (low - current_quote) / low * Decimal("100")
        message = f"현재 견적은 확보된 직접 비교자료 하단보다 {rate:.1f}% 낮음. 구성·조건 동일 여부 확인 필요."
        position = "하단 미만"
    else:
        rate = Decimal("0")
        message = "현재 견적은 확보된 직접 비교자료 가격범위 내에 위치함."
        position = "범위 내"

    return PriceAssessment(
        comparable_count=len(direct), low=low, median=med, high=high,
        confidence=confidence, quote_position=position, difference_rate=rate,
        message=message,
    )
