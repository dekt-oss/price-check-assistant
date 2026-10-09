"""입력 오류 의심 거래: one rule for "the unit price in this 나라장터 line cannot be a real price".

나라장터 납품요구 lines are typed in by the ordering institution. Some are entered with the 단가
and 수량 swapped (HeartOn A16-DS, 2024-08-20, 속초시: 단가 1원 · 수량 1,731,000대 · 총액 1,731,000원,
while the purchase was 1대 × 1,731,000원). A "최저 1원" then ends up on the price rail.

The rule flags such lines so every price statistic (median, range, year table, unit groups,
supplier ranges, quote verdicts, 같은 품목 시세) can leave them out while the screen still lists
them with the reason. It never rewrites the numbers: the swapped value is a guess, the 원문 is
the proof.

A line is flagged when the unit price is 0 or below, or at most 10원 (``TINY_UNIT_PRICE``). When
the quantity is also at least 1,000 and quantity x unit price equals the total, the reason says
the 단가 and 수량 look swapped (the real price was typed as the quantity).

Why not also "unit price up to 100원 with a huge quantity": in the 2026-10 index that pattern
(627 current lines at 11~100원) is almost all real bulk buying of cheap goods (봉투 24.75원 x 80,000,
감응테이프 90원 x 14,000), indistinguishable from a swap by the numbers alone. A cheap consumable
at 3,000원 is not flagged either. Pure functions over plain values; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Runtime marker for callers that may hold an older copy of this module.
ENTRY_CHECK_V1 = True

TINY_UNIT_PRICE = Decimal("10")
# The swap wording needs a tiny price too (see the module note); it is a message, not a wider net.
SWAP_MAX_UNIT_PRICE = TINY_UNIT_PRICE
SWAP_MIN_QUANTITY = Decimal("1000")
# quantity x unit price may differ from the total by this share (or 1원) and still "match".
TOTAL_TOLERANCE = Decimal("0.01")

KIND_SWAPPED = "swapped"
KIND_TINY_PRICE = "tiny_price"
KIND_ZERO_PRICE = "zero_price"

SHORT_LABEL = "입력 오류 의심"
CHECK_SOURCE = "원문 확인"


@dataclass(frozen=True)
class EntryError:
    kind: str
    reason: str
    unit_price: Decimal
    quantity: Decimal | None = None


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).replace(",", "").replace("원", "").strip())
    except Exception:
        return None
    return number if number.is_finite() else None


def _number(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value.normalize():,}"


def _unit_text(unit: object) -> str:
    text = " ".join(str(unit or "").split())
    return "" if text == "미확인" else text


# Digits read with a final consonant other than ㄹ: 영(0) 삼(3) 육(6) take 으로, the rest take 로.
_DIGITS_WITH_FINAL = "036"


def _with_ro(text: str) -> str:
    """'대' -> '대로', '식' -> '식으로', '1,731,000' -> '1,731,000으로' (로 / 으로 by the last sound)."""

    last = text[-1:] if text else ""
    if last.isdigit():
        return text + ("으로" if last in _DIGITS_WITH_FINAL else "로")
    if "가" <= last <= "힣":
        final = (ord(last) - ord("가")) % 28
        return text + ("로" if final in (0, 8) else "으로")
    return text + "로"


def _quantity_phrase(quantity: Decimal | None, unit: str) -> str:
    return f"{_number(quantity)}{unit}" if quantity is not None else ""


def is_swap_pattern(unit_price: Decimal, quantity: Decimal | None, total_amount: Decimal | None) -> bool:
    """A tiny unit price times a huge quantity that reproduces the total."""

    if quantity is None or total_amount is None:
        return False
    if not (0 < unit_price <= SWAP_MAX_UNIT_PRICE) or quantity < SWAP_MIN_QUANTITY:
        return False
    allowed = max(Decimal(1), abs(total_amount) * TOTAL_TOLERANCE)
    return abs(quantity * unit_price - total_amount) <= allowed


def entry_error(
    unit_price: object,
    quantity: object = None,
    total_amount: object = None,
    unit: object = None,
) -> EntryError | None:
    """The reason this line looks mistyped, or None. A missing unit price is not judged here."""

    price = _decimal(unit_price)
    if price is None:
        return None
    qty = _decimal(quantity)
    if qty is not None and qty <= 0:
        qty = None
    total = _decimal(total_amount)
    unit_name = _unit_text(unit)

    if price <= 0:
        kind = KIND_ZERO_PRICE
    elif is_swap_pattern(price, qty, total):
        kind = KIND_SWAPPED
    elif price <= TINY_UNIT_PRICE:
        kind = KIND_TINY_PRICE
    else:
        return None

    parts = [f"단가 {_number(price)}원"]
    if qty is not None:
        parts.append(f"수량 {_quantity_phrase(qty, unit_name)}")
    written = _with_ro(" · ".join(parts))
    if kind == KIND_SWAPPED:
        reason = f"{written} 적혀 있어 단가와 수량이 뒤바뀐 입력 오류로 보입니다 — {CHECK_SOURCE}"
    else:
        reason = f"{written} 적혀 있어 입력 오류로 보입니다 — {CHECK_SOURCE}"
    return EntryError(kind, reason, price, qty)


def candidate_entry_error(candidate: Any) -> EntryError | None:
    """The same rule for a Track B candidate (price, quantity, total_amount, unit)."""

    return entry_error(
        getattr(candidate, "price", None),
        getattr(candidate, "quantity", None),
        getattr(candidate, "total_amount", None),
        getattr(candidate, "unit", None),
    )


def is_entry_error(candidate: Any) -> bool:
    return candidate_entry_error(candidate) is not None
