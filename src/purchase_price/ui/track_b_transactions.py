from __future__ import annotations

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
                "가격": float(candidate.price),
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
