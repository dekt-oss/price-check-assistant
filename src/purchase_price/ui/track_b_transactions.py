from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median
from typing import Any


def comparison_candidates(track_b: Any) -> tuple[Any, ...]:
    """Return graded comparison candidates from current or older runtime objects.

    Current Track B comparison results may contain A/B direct-match candidates and C category
    references in the same legacy candidates tuple. Callers that need decision-safe counts
    must use strict_comparison_candidates rather than assuming every row is A/B.
    """

    return tuple(getattr(track_b, "candidates", ()) or ())


def _grade_value(candidate: Any) -> str:
    grade = getattr(candidate, "match_grade", None)
    value = getattr(grade, "value", grade)
    return str(value or "").strip().upper()


def strict_comparison_candidates(track_b: Any) -> tuple[Any, ...]:
    """Return only A/B candidates eligible for direct observed-price display."""

    return tuple(
        candidate
        for candidate in comparison_candidates(track_b)
        if _grade_value(candidate) in {"A", "B"}
    )


def category_reference_candidates(track_b: Any) -> tuple[Any, ...]:
    """Return non-A/B graded candidates as Research/reference evidence."""

    return tuple(
        candidate
        for candidate in comparison_candidates(track_b)
        if _grade_value(candidate) not in {"A", "B"}
    )


def reference_candidates(track_b: Any) -> tuple[Any, ...]:
    """Return Research-only references without assuming a freshly reloaded dataclass shape.

    Streamlit Cloud can briefly serve a newly reloaded page module while an imported service
    module still has the previous TrackBQuoteComparison class in memory. The previous class did
    not expose reference_candidates. Treating that field as optional keeps the page available
    during rolling deploys; once the service module reloads, the references appear normally.
    """

    return tuple(getattr(track_b, "reference_candidates", ()) or ())


def has_transaction_candidates(track_b: Any) -> bool:
    return bool(comparison_candidates(track_b) or reference_candidates(track_b))


def candidate_counts(track_b: Any) -> tuple[int, int]:
    """Return A/B direct count and all C/Research reference count."""

    direct = strict_comparison_candidates(track_b)
    references = (*category_reference_candidates(track_b), *reference_candidates(track_b))
    return len(direct), len(references)


def _money_text(value: Any) -> str:
    try:
        return f"{value:,.0f}원"
    except (TypeError, ValueError):
        return str(value)


def _quantity_unit(quantity: Any, unit: str | None) -> str:
    if quantity is None and not unit:
        return "미확인"
    if quantity is None:
        quantity_text = ""
    else:
        try:
            quantity_text = f"{quantity:g}"
        except (TypeError, ValueError):
            quantity_text = str(quantity)
    return " ".join(part for part in (quantity_text, unit or "") if part) or "미확인"



def _condition_text(candidate: Any) -> str:
    parts = [
        str(value).strip()
        for value in (
            getattr(candidate, "contract_delivery_type", None),
            getattr(candidate, "contract_type", None),
            getattr(candidate, "delivery_condition", None),
        )
        if value and str(value).strip()
    ]
    return " · ".join(dict.fromkeys(parts)) if parts else "미확인"

def transaction_rows(track_b: Any) -> list[dict[str, object]]:
    """Build the purchase-facing transaction table from direct and Research-only evidence.

    Optional transaction metadata is accessed defensively so a rolling deploy cannot turn a
    harmless schema difference into a full-page AttributeError.
    """

    rows: list[dict[str, object]] = []
    for candidate in comparison_candidates(track_b):
        grade_value = _grade_value(candidate)
        rows.append(
            {
                "가격": _money_text(candidate.price),
                "총액": _money_text(getattr(candidate, "total_amount", None))
                if getattr(candidate, "total_amount", None) is not None
                else "미확인",
                "금액검증": getattr(candidate, "amount_check", None) or "미확인",
                "제조사": getattr(candidate, "manufacturer", None) or "미확인",
                "모델": getattr(candidate, "model_name", None) or "미확인",
                "규격": getattr(candidate, "specification", None) or "미확인",
                "품목식별번호": getattr(candidate, "product_id", None) or "미확인",
                "세부품명번호": getattr(candidate, "detail_code", None) or "미확인",
                "거래조건": _condition_text(candidate),
                "판매처": getattr(candidate, "supplier", None) or "미확인",
                "구매처": getattr(candidate, "demand_institution", None) or "미확인",
                "거래일": getattr(candidate, "transaction_date", None) or "미확인",
                "수량/단위": _quantity_unit(
                    getattr(candidate, "quantity", None),
                    getattr(candidate, "unit", None),
                ),
                "거래기록": getattr(candidate, "transaction_type", None)
                or "나라장터 납품요구",
                "품목/모델": candidate.product_title,
                "비교수준": "동일 모델" if grade_value in {"A", "B"} else "동일 품목 참고",
            }
        )

    for candidate in reference_candidates(track_b):
        rows.append(
            {
                "가격": _money_text(candidate.price),
                "총액": _money_text(getattr(candidate, "total_amount", None))
                if getattr(candidate, "total_amount", None) is not None
                else "미확인",
                "금액검증": getattr(candidate, "amount_check", None) or "미확인",
                "제조사": getattr(candidate, "manufacturer", None) or "미확인",
                "모델": getattr(candidate, "model_name", None) or "미확인",
                "규격": getattr(candidate, "specification", None) or "미확인",
                "품목식별번호": getattr(candidate, "product_id", None) or "미확인",
                "세부품명번호": getattr(candidate, "detail_code", None) or "미확인",
                "거래조건": _condition_text(candidate),
                "판매처": getattr(candidate, "supplier", None) or "미확인",
                "구매처": getattr(candidate, "demand_institution", None) or "미확인",
                "거래일": getattr(candidate, "transaction_date", None) or "미확인",
                "수량/단위": _quantity_unit(
                    getattr(candidate, "quantity", None),
                    getattr(candidate, "unit", None),
                ),
                "거래기록": getattr(candidate, "transaction_type", None)
                or "나라장터 납품요구",
                "품목/모델": candidate.product_title,
                "비교수준": getattr(candidate, "reference_reason", None) or "검색 참고",
            }
        )
    return rows



def _decimal_sum(values: list[Any]) -> Decimal | None:
    total = Decimal("0")
    found = False
    for value in values:
        if value is None:
            continue
        try:
            total += Decimal(str(value))
            found = True
        except Exception:
            continue
    return total if found else None


def model_price_group_rows(track_b: Any) -> list[dict[str, object]]:
    """Summarize only A/B direct evidence by model and specification.

    Reference-only C/Research evidence is intentionally excluded so the grouped
    band cannot be mistaken for a fair-price range.
    """

    groups: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for candidate in strict_comparison_candidates(track_b):
        model = getattr(candidate, "model_name", None) or "모델 미확인"
        specification = getattr(candidate, "specification", None) or "규격 미확인"
        condition = _condition_text(candidate)
        groups[(model, specification, condition)].append(candidate)

    rows: list[dict[str, object]] = []
    for (model, specification, condition), candidates in groups.items():
        prices = sorted(Decimal(str(candidate.price)) for candidate in candidates)
        quantities = [getattr(candidate, "quantity", None) for candidate in candidates]
        dates = [
            str(getattr(candidate, "transaction_date", "") or "")
            for candidate in candidates
            if getattr(candidate, "transaction_date", None)
        ]
        rows.append(
            {
                "모델": model,
                "규격": specification,
                "거래조건": condition,
                "거래건수": len(candidates),
                "최저단가": _money_text(prices[0]),
                "중앙값": _money_text(median(prices)),
                "최고단가": _money_text(prices[-1]),
                "총수량": str(_decimal_sum(quantities) or "미확인"),
                "최근거래일": max(dates) if dates else "미확인",
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -int(row["거래건수"]),
            str(row["모델"]),
            str(row["규격"]),
            str(row["거래조건"]),
        ),
    )
