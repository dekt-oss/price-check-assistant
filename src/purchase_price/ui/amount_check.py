"""금액검증 in plain words, shared by the 가격 조사 and 견적서 검토 trade tables.

The serving index stores whether 단가 × 수량 matched the 총액 as "consistent" / "inconsistent" /
"not_checked"; the screens never show those English codes. A new module on purpose: a page that
imports it after a deploy always gets this copy, whatever older modules the process still holds.
"""

from __future__ import annotations

AMOUNT_CHECK_LABELS = {
    "consistent": "금액 일치",
    "inconsistent": "금액 확인 필요",
    "not_checked": "확인 불가",
    "unknown": "확인 불가",
}


def amount_check_label(value: object) -> str:
    """단가×수량과 총액이 맞는지 검산한 결과를 쉬운 말로. 모르는 값은 원문을 노출하지 않는다."""

    text = str(getattr(value, "value", value) or "").strip().lower()
    return AMOUNT_CHECK_LABELS.get(text, "확인 불가")
