from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Any

from purchase_price.ui.track_b_transactions import (
    category_reference_candidates,
    reference_candidates,
    strict_comparison_candidates,
)


@dataclass(frozen=True)
class PurchaseWorkspaceStats:
    direct_count: int
    reference_count: int
    research_count: int
    supplier_count: int
    demand_institution_count: int
    min_price: Decimal | None
    median_price: Decimal | None
    max_price: Decimal | None
    latest_transaction_date: str | None
    quote_vs_median_percent: Decimal | None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _distinct_text(candidates: tuple[Any, ...], attr: str) -> set[str]:
    values: set[str] = set()
    for candidate in candidates:
        value = str(getattr(candidate, attr, "") or "").strip()
        if value:
            values.add(value)
    return values


def build_purchase_workspace_stats(
    *,
    track_b: Any,
    market_bundle: Any,
    quote_unit_price: Decimal | None,
) -> PurchaseWorkspaceStats:
    direct = strict_comparison_candidates(track_b)
    references = (*category_reference_candidates(track_b), *reference_candidates(track_b))
    prices = sorted(
        value
        for value in (_decimal(getattr(candidate, "price", None)) for candidate in direct)
        if value is not None and value > 0
    )
    dates = sorted(
        str(getattr(candidate, "transaction_date", "") or "")
        for candidate in direct
        if getattr(candidate, "transaction_date", None)
    )
    median_price = Decimal(str(median(prices))) if prices else None
    quote_delta = None
    if (
        quote_unit_price is not None
        and quote_unit_price > 0
        and median_price is not None
        and median_price > 0
    ):
        quote_delta = ((quote_unit_price - median_price) / median_price * 100).quantize(
            Decimal("0.1")
        )

    return PurchaseWorkspaceStats(
        direct_count=len(direct),
        reference_count=len(references),
        research_count=len(tuple(getattr(market_bundle, "records", ()) or ())),
        supplier_count=len(_distinct_text(direct, "supplier")),
        demand_institution_count=len(_distinct_text(direct, "demand_institution")),
        min_price=prices[0] if prices else None,
        median_price=median_price,
        max_price=prices[-1] if prices else None,
        latest_transaction_date=dates[-1] if dates else None,
        quote_vs_median_percent=quote_delta,
    )


def supplier_rows(track_b: Any) -> list[dict[str, object]]:
    """Summarize suppliers from A/B direct evidence only."""

    groups: dict[str, list[Any]] = {}
    for candidate in strict_comparison_candidates(track_b):
        supplier = str(getattr(candidate, "supplier", "") or "").strip()
        if not supplier:
            continue
        groups.setdefault(supplier, []).append(candidate)

    rows: list[dict[str, object]] = []
    for supplier, candidates in groups.items():
        prices = sorted(
            value
            for value in (_decimal(getattr(candidate, "price", None)) for candidate in candidates)
            if value is not None and value > 0
        )
        institutions = {
            str(getattr(candidate, "demand_institution", "") or "").strip()
            for candidate in candidates
            if str(getattr(candidate, "demand_institution", "") or "").strip()
        }
        dates = [
            str(getattr(candidate, "transaction_date", "") or "")
            for candidate in candidates
            if getattr(candidate, "transaction_date", None)
        ]
        rows.append(
            {
                "공급업체": supplier,
                "직접거래건수": len(candidates),
                "수요기관수": len(institutions),
                "최저단가": prices[0] if prices else None,
                "최고단가": prices[-1] if prices else None,
                "최근거래일": max(dates) if dates else None,
                "근거": "나라장터 실제 납품요구 · A/B 직접근거",
            }
        )
    return sorted(rows, key=lambda row: (-int(row["직접거래건수"]), str(row["공급업체"])))
