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


def build_quote_position_message(
    *,
    quote_unit_price: Decimal | None,
    stats: PurchaseWorkspaceStats,
    unit: str = "",
    vat_status: str = "",
    conditions: str = "",
) -> str:
    """Describe a quote's observed position without making an adequacy verdict."""

    if quote_unit_price is None or quote_unit_price <= 0:
        return "내 견적가를 입력하면 A/B 직접비교 자료에서 관측된 위치를 확인할 수 있습니다."

    qualifiers = []
    if unit.strip():
        qualifiers.append(f"단위 {unit.strip()}")
    else:
        qualifiers.append("단위 미확인")
    if vat_status.strip():
        qualifiers.append(f"VAT {vat_status.strip()}")
    else:
        qualifiers.append("VAT 미확인")
    if conditions.strip():
        qualifiers.append(f"조건 {conditions.strip()}")
    else:
        qualifiers.append("설치·운송 조건 미확인")
    qualifier_text = " · ".join(qualifiers)

    if stats.direct_count == 0 or stats.min_price is None or stats.max_price is None:
        return f"직접 비교자료가 없어 가격 위치를 계산하지 않습니다. {qualifier_text}."

    if stats.direct_count == 1:
        only = stats.min_price
        delta = ((quote_unit_price - only) / only * 100).quantize(Decimal("0.1"))
        return (
            f"직접 비교자료 1건 대비 {delta:+.1f}%입니다. "
            f"1건뿐으로 가격대 판단근거가 부족합니다. {qualifier_text}."
        )

    if quote_unit_price > stats.max_price:
        delta = ((quote_unit_price - stats.max_price) / stats.max_price * 100).quantize(
            Decimal("0.1")
        )
        position = f"직접 비교자료 상단 대비 {delta:+.1f}%"
    elif quote_unit_price < stats.min_price:
        delta = ((quote_unit_price - stats.min_price) / stats.min_price * 100).quantize(
            Decimal("0.1")
        )
        position = f"직접 비교자료 하단 대비 {delta:+.1f}%"
    else:
        position = "직접 비교자료 관측 범위 안"

    return f"내 견적가는 {position}에 위치합니다. {qualifier_text}. 조건 동일성을 별도로 확인하세요."


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
        raw_keys = sorted(
            {
                str(getattr(candidate, "raw_object_key", "") or "").strip()
                for candidate in candidates
                if str(getattr(candidate, "raw_object_key", "") or "").strip()
            }
        )
        rows.append(
            {
                "공급업체": supplier,
                "직접거래건수": len(candidates),
                "수요기관수": len(institutions),
                "최저단가": prices[0] if prices else None,
                "최고단가": prices[-1] if prices else None,
                "최근거래일": max(dates) if dates else None,
                "근거": "나라장터 실제 납품요구 · A/B 직접근거",
                "Source": "나라장터 납품요구",
                "원문근거키": " / ".join(raw_keys[:3]) or "미확인",
            }
        )
    return sorted(rows, key=lambda row: (-int(row["직접거래건수"]), str(row["공급업체"])))
