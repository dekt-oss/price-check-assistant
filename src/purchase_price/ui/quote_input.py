"""The 내 견적 단가 box: what a buyer types ("250만", "2억 5천만", "1,800,000원") and how far a
quote is from a trade price, in words that stay readable for absurd inputs.

New module, so a Streamlit process that keeps older modules after a deploy imports it fresh.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

# Above this a typed price is almost certainly a typo (an extra digit or two), not a quote.
MAX_QUOTE = Decimal("100000000000")  # 1,000억 원
# From this far above a price, "N배 넘게 높습니다" reads better than a five-digit percentage.
TIMES_FROM_PERCENT = Decimal("1000")

_BIG_UNITS = (("조", Decimal("1000000000000")), ("억", Decimal("100000000")), ("만", Decimal("10000")))
_SMALL_UNITS = {"천": Decimal("1000"), "백": Decimal("100"), "십": Decimal("10")}
_NUMBER = r"\d+(?:\.\d+)?"
_CLEAN_RE = re.compile(r"[\s,_원₩]|krw|won", re.IGNORECASE)
_ALLOWED_RE = re.compile(r"^-?[\d.조억만천백십]+$")

MSG_NOT_NUMBER = "숫자로 넣으세요. 예: 1,800,000 · 180만 · 2억 5천만"
MSG_NOT_POSITIVE = "견적 단가는 0보다 큰 금액으로 넣으세요."
MSG_TOO_LARGE = "1,000억 원이 넘는 금액이라 비교하지 않았습니다. 자릿수를 확인하세요."


@dataclass(frozen=True)
class QuoteInput:
    value: Decimal | None
    error: str | None = None

    @property
    def empty(self) -> bool:
        return self.value is None and self.error is None


def _small_group(text: str) -> Decimal:
    """'2천5백', '2500', '천', '1.5천' -> the number below 10,000 (or any plain number)."""

    if not text:
        return Decimal(0)
    total = Decimal(0)
    rest = text
    for unit, size in _SMALL_UNITS.items():
        if unit in rest:
            head, rest = rest.split(unit, 1)
            total += (Decimal(head) if head else Decimal(1)) * size
    if rest:
        if not re.fullmatch(_NUMBER, rest):
            raise InvalidOperation(rest)
        total += Decimal(rest)
    return total


def _korean_amount(text: str) -> Decimal:
    total = Decimal(0)
    rest = text
    used_big = False
    last_size: Decimal | None = None
    for unit, size in _BIG_UNITS:
        if unit in rest:
            head, rest = rest.split(unit, 1)
            total += (_small_group(head) if head else Decimal(1)) * size
            used_big = True
            last_size = size
    if rest:
        tail = _small_group(rest)
        # "1억 5천" is said for 1억 5천만: a bare 천/백 right after 억 counts in 만.
        if used_big and last_size == Decimal("100000000") and any(u in rest for u in _SMALL_UNITS) and tail < 10000:
            tail *= Decimal("10000")
        total += tail
    return total


def parse_quote_input(text: object) -> QuoteInput:
    """Parse the 내 견적 단가 box. Empty -> no quote; anything unusable -> a plain error."""

    raw = str(text or "").strip()
    if not raw:
        return QuoteInput(None)
    cleaned = _CLEAN_RE.sub("", raw)
    if not cleaned or not _ALLOWED_RE.match(cleaned):
        return QuoteInput(None, MSG_NOT_NUMBER)
    negative = cleaned.startswith("-")
    body = cleaned.lstrip("-")
    try:
        value = _korean_amount(body) if re.search(r"[조억만천백십]", body) else Decimal(body)
    except (InvalidOperation, ValueError):
        return QuoteInput(None, MSG_NOT_NUMBER)
    if negative or value <= 0:
        return QuoteInput(None, MSG_NOT_POSITIVE)
    if value > MAX_QUOTE:
        return QuoteInput(None, MSG_TOO_LARGE)
    return QuoteInput(value.quantize(Decimal(1)) if value == value.to_integral_value() else value)


def quote_error_message(error: str, previous: Decimal | None) -> str:
    """The warning under the box; it names the earlier value only when there is one."""

    if previous is not None and previous > 0:
        return f"{error} 직전에 넣은 {previous:,.0f}원으로 비교합니다."
    return f"{error} 견적 위치는 표시하지 않습니다."


def percent_delta(quote: Decimal, base: Decimal) -> Decimal:
    return ((quote - base) / base * 100).quantize(Decimal("0.1"))


def difference_phrase(quote: Decimal, base: Decimal) -> str:
    """'9.1% 낮습니다', '1,234.5% 높습니다' or, far above, '50,505배 넘게 높습니다'."""

    if base <= 0:
        return ""
    delta = percent_delta(quote, base)
    if delta >= TIMES_FROM_PERCENT:
        times = (quote / base).to_integral_value(rounding=ROUND_FLOOR)
        return f"{times:,.0f}배 넘게 높습니다"
    if delta > 0:
        return f"{delta:,.1f}% 높습니다"
    if delta < 0:
        return f"{abs(delta):,.1f}% 낮습니다"
    return "같습니다"
