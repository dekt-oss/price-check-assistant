from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.services import safety_support as safety_support_service
from purchase_price.services.safety_support import build_manual_safety_check_state
from purchase_price.ui.track_b_transactions import strict_comparison_candidates


@dataclass(frozen=True)
class QuoteItemIntelligenceSummary:
    direct_count: int
    observed_low: Decimal | None
    observed_high: Decimal | None
    supplier_names: tuple[str, ...]
    identity_status: str
    permit_numbers: tuple[str, ...]
    responsible_companies: tuple[str, ...]
    business_license_status: str
    safety_status: str
    safety_message: str


def _positive_prices(candidates: tuple[Any, ...]) -> list[Decimal]:
    prices: list[Decimal] = []
    for candidate in candidates:
        value = getattr(candidate, "price", None)
        if value is None:
            continue
        try:
            price = Decimal(str(value))
        except Exception:
            continue
        if price.is_finite() and price > 0:
            prices.append(price)
    return sorted(prices)


def _identity_status(identity: Any) -> str:
    if identity is None:
        return "미조회"
    status = str(getattr(identity, "status", "") or "")
    if status in {"unavailable", "not_ingested"}:
        return "조회 불가"
    if status == "success_0":
        return "일치 0건"
    if status != "success":
        return "미확인"

    semantic = getattr(identity, "identity_status", None)
    if semantic == IdentityEvidenceStatus.AMBIGUOUS:
        return "복수 identity · 확인 필요"

    match_type = str(getattr(identity, "match_type", "") or "")
    if match_type == "model":
        return "모델 exact 확인"
    if match_type == "permit":
        return "품목번호 확인"
    if match_type == "udi":
        return "UDI 확인"
    if match_type == "product":
        return "품목 기준 등록정보"
    if match_type == "company":
        return "업체 기준 등록정보"
    return "확인"


def _tuple_attr(value: Any, attr: str) -> tuple[str, ...]:
    raw = getattr(value, attr, ()) if value is not None else ()
    return tuple(str(item).strip() for item in tuple(raw or ()) if str(item).strip())


def build_quote_item_intelligence_summary(
    *,
    item: Any,
    track_b: Any,
    mfds_workspace: Any,
    mfds_identity: Any,
    safety_lookup: Any = None,
) -> QuoteItemIntelligenceSummary:
    direct = strict_comparison_candidates(track_b) if track_b is not None else ()
    prices = _positive_prices(direct)
    suppliers = tuple(
        sorted(
            {
                str(getattr(candidate, "supplier", "") or "").strip()
                for candidate in direct
                if str(getattr(candidate, "supplier", "") or "").strip()
            }
        )
    )

    permit_numbers = set(_tuple_attr(mfds_identity, "permit_numbers"))
    permit_numbers.update(_tuple_attr(mfds_workspace, "permit_numbers"))

    responsible_companies = _tuple_attr(mfds_identity, "companies")
    business_records = tuple(
        getattr(mfds_workspace, "business_records", ()) or ()
        if mfds_workspace is not None
        else ()
    )
    if business_records:
        business_license_status = f"제조사명 업허가 {len(business_records)}건"
    else:
        business_license_status = "업허가 상세 확인"

    model_name = str(getattr(item, "model_name", "") or "").strip()
    product_name = str(getattr(item, "product_name", "") or "").strip()
    safety_builder = getattr(
        safety_support_service,
        "build_safety_state_from_recall_lookup",
        None,
    )
    safety = (
        safety_builder(
            safety_lookup,
            model_name=model_name,
            product_name=product_name,
            permit_numbers=tuple(sorted(permit_numbers)),
        )
        if safety_lookup is not None and callable(safety_builder)
        else build_manual_safety_check_state(
            model_name=model_name,
            permit_numbers=tuple(sorted(permit_numbers)),
        )
    )

    return QuoteItemIntelligenceSummary(
        direct_count=len(direct),
        observed_low=prices[0] if prices else None,
        observed_high=prices[-1] if prices else None,
        supplier_names=suppliers,
        identity_status=_identity_status(mfds_identity),
        permit_numbers=tuple(sorted(permit_numbers)),
        responsible_companies=responsible_companies,
        business_license_status=business_license_status,
        safety_status=safety.status.value,
        safety_message=safety.message,
    )


def quote_item_intelligence_rows(
    summaries: list[tuple[int, str, QuoteItemIntelligenceSummary]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, item_name, summary in summaries:
        price_range = (
            f"{summary.observed_low:,.0f} ~ {summary.observed_high:,.0f}원"
            if summary.observed_low is not None and summary.observed_high is not None
            else "직접가격 없음"
        )
        rows.append(
            {
                "번호": index + 1,
                "품목": item_name,
                "직접가격": f"{summary.direct_count}건 · {price_range}",
                "식약처 Identity": summary.identity_status,
                "품목 책임주체": " / ".join(summary.responsible_companies) or "미확인",
                "업허가": summary.business_license_status,
                "실제 조달 공급업체": " / ".join(summary.supplier_names) or "0개",
                "Safety": summary.safety_status,
            }
        )
    return rows
