from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.services import safety_support as safety_support_service
from purchase_price.services.safety_support import build_manual_safety_check_state
from purchase_price.ui.quote_review_layout import comparable_trade_stats


@dataclass(frozen=True)
class QuoteItemIntelligenceSummary:
    # Same trades the main comparison table uses: default period, same unit as most trades.
    direct_count: int
    observed_low: Decimal | None
    observed_high: Decimal | None
    other_unit_count: int
    other_units: tuple[str, ...]
    main_unit: str | None
    supplier_names: tuple[str, ...]
    identity_status: str
    permit_numbers: tuple[str, ...]
    responsible_companies: tuple[str, ...]
    business_license_status: str
    safety_status: str
    safety_message: str


def _identity_status(identity: Any) -> str:
    """식약처 허가 목록에서 같은 모델명을 찾았는지. 나라장터 거래와는 별개의 자료입니다."""

    if identity is None:
        return "아직 조회하지 않음"
    status = str(getattr(identity, "status", "") or "")
    if status in {"unavailable", "not_ingested"}:
        return "지금은 조회할 수 없음"
    if status == "success_0":
        return "허가 목록에서 같은 모델을 못 찾음"
    if status != "success":
        return "확인하지 못함"

    semantic = getattr(identity, "identity_status", None)
    if semantic == IdentityEvidenceStatus.AMBIGUOUS:
        return "같은 모델명이 여러 허가에 있어 직접 살펴봐야 함"

    match_type = str(getattr(identity, "match_type", "") or "")
    if match_type == "model":
        return "허가 목록에서 같은 모델 확인"
    if match_type == "permit":
        return "허가번호로 확인"
    if match_type == "udi":
        return "UDI 코드로 확인"
    if match_type == "product":
        return "품목 단위 허가 정보만 있음"
    if match_type == "company":
        return "업체 단위 허가 정보만 있음"
    return "확인함"


def mfds_permit_note(mfds_workspace: Any, mfds_identity: Any) -> tuple[str, str] | None:
    """식약처 허가 대조 안내문 (수준, 문장). 수준: success / warning / info.

    전체 허가 목록(R2 색인)에서 모델명을 찾은 결과를 먼저 믿는다. 식약처 API 조회는 품목명으로
    첫 몇 쪽만 가져오므로 모델명이 그 안에 없다고 해서 '같은 모델이 없다'고 말하면 안 된다.
    """

    identity_state = ""
    if mfds_identity is not None and str(getattr(mfds_identity, "status", "")) == "success":
        match_type = str(getattr(mfds_identity, "match_type", "") or "")
        if match_type in {"model", "udi", "permit"}:
            permits = " / ".join(_tuple_attr(mfds_identity, "permit_numbers")) or "허가번호 미표기"
            if getattr(mfds_identity, "identity_status", None) == IdentityEvidenceStatus.AMBIGUOUS:
                return (
                    "warning",
                    f"같은 모델명이 여러 허가에 있어 직접 확인해야 합니다 · {permits}",
                )
            identity_state = f"식약처 허가 목록에서 같은 모델 확인 · {permits}"

    workspace = mfds_workspace
    status = str(getattr(workspace, "status", "") or "")
    if workspace is not None and status in {"success", "success_0"}:
        if getattr(workspace, "exact_ambiguous", False):
            permits = " / ".join(_tuple_attr(workspace, "permit_numbers"))
            tail = f" · {permits}" if permits else ""
            return ("warning", f"같은 모델명이 여러 허가에 있어 직접 확인해야 합니다{tail}")
        if getattr(workspace, "exact_confirmed", False):
            permits = " / ".join(_tuple_attr(workspace, "permit_numbers")) or "허가번호 미표기"
            active = len(getattr(workspace, "active_records", ()) or ())
            return (
                "success",
                f"식약처 허가 목록에서 같은 모델 확인 · {permits} · "
                f"같은 품목의 국내 정상 등록 모델 {active}건",
            )
        if identity_state:
            return ("success", identity_state)
        records = getattr(workspace, "records", ()) or ()
        if records:
            return (
                "info",
                f"식약처에서 같은 품목의 모델 {len(records)}건을 살펴봤지만 "
                "견적서의 모델명과 같은 모델은 그 안에서 찾지 못했습니다. "
                "전체 허가 목록에는 있을 수 있어 식약처에서 직접 확인해 주세요.",
            )
        return None
    if identity_state:
        return ("success", identity_state)
    return None


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
    stats = comparable_trade_stats(track_b)
    direct = stats.split.kept
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
        business_license_status = f"제조·수입업 허가 {len(business_records)}건 확인"
    else:
        business_license_status = "식약처에서 직접 확인"

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
        direct_count=stats.count,
        observed_low=stats.low,
        observed_high=stats.high,
        other_unit_count=stats.other_count,
        other_units=stats.other_units,
        main_unit=stats.main_unit,
        supplier_names=suppliers,
        identity_status=_identity_status(mfds_identity),
        permit_numbers=tuple(sorted(permit_numbers)),
        responsible_companies=responsible_companies,
        business_license_status=business_license_status,
        safety_status=safety.status.value,
        safety_message=safety.message,
    )


QUOTE_REVIEW_ACCEPTANCE_V3 = True

ROW_LABELS = {
    "number": "번호",
    "item": "품목",
    "trades": "나라장터 같은 모델 거래",
    "other_unit": "단위가 다른 거래",
    "permit": "식약처 허가 대조",
    "makers": "제조·수입업체(식약처)",
    "license": "업체 허가",
    "suppliers": "납품업체(나라장터)",
    "safety": "회수·판매중지",
}

PERMIT_VS_TRADES_NOTE = (
    "'식약처 허가 대조'는 의료기기 허가 목록에서 같은 모델명을 찾아본 결과이고, "
    "'나라장터 같은 모델 거래'는 나라장터에서 그 모델이 실제로 거래된 기록입니다. 서로 다른 자료라서 "
    "허가 목록에서 못 찾아도 나라장터 거래는 있을 수 있습니다. 견적 단가 판정은 나라장터 거래로만 합니다."
)


def _trade_text(summary: QuoteItemIntelligenceSummary) -> str:
    if not summary.direct_count:
        return "거래 없음"
    unit = f"1{summary.main_unit} 기준 " if summary.main_unit else ""
    if summary.observed_low is not None and summary.observed_low == summary.observed_high:
        return f"{summary.direct_count}건 · {unit}{summary.observed_low:,.0f}원"
    if summary.observed_low is not None and summary.observed_high is not None:
        return (
            f"{summary.direct_count}건 · {unit}"
            f"{summary.observed_low:,.0f} ~ {summary.observed_high:,.0f}원"
        )
    return f"{summary.direct_count}건"


def _other_unit_text(summary: QuoteItemIntelligenceSummary) -> str:
    if not summary.other_unit_count:
        return "없음"
    units = "·".join(summary.other_units)
    return f"{summary.other_unit_count}건({units}) · 따로 셈" if units else f"{summary.other_unit_count}건 · 따로 셈"


def quote_item_intelligence_rows(
    summaries: list[tuple[int, str, QuoteItemIntelligenceSummary]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, item_name, summary in summaries:
        rows.append(
            {
                ROW_LABELS["number"]: index + 1,
                ROW_LABELS["item"]: item_name,
                ROW_LABELS["trades"]: _trade_text(summary),
                ROW_LABELS["other_unit"]: _other_unit_text(summary),
                ROW_LABELS["permit"]: summary.identity_status,
                ROW_LABELS["makers"]: " / ".join(summary.responsible_companies) or "확인 못함",
                ROW_LABELS["license"]: summary.business_license_status,
                ROW_LABELS["suppliers"]: " / ".join(summary.supplier_names) or "없음",
                ROW_LABELS["safety"]: summary.safety_status,
            }
        )
    return rows
