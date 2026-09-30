from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from purchase_price.evidence_domain import SafetyEvidenceStatus


class SafetyDisplayStatus(StrEnum):
    NOT_CONNECTED = "자동조회 미연결"
    NOT_AUTHORIZED = "공식 API 인증 미승인"
    CHECK_REQUIRED = "공식 확인 필요"
    MATCH = "공식 안전조치 일치"
    NO_MATCH = "공식 안전정보 일치 미확인"
    ERROR = "공식 안전정보 조회 실패"


@dataclass(frozen=True)
class SafetyStateCompat:
    status: SafetyDisplayStatus
    evidence_status: SafetyEvidenceStatus
    message: str
    model_name: str = ""
    permit_numbers: tuple[str, ...] = ()
    checked_at: str | None = None
    source_url: str | None = None
    search_keys: tuple[str, ...] = ()


def _unique_text(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return tuple(output)


def _search_keys(model_name: str, permits: tuple[str, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    if model_name:
        keys.append(f"모델명: {model_name}")
    keys.extend(f"식약처 품목번호: {permit}" for permit in permits)
    return tuple(keys)


def _fallback_from_lookup(
    lookup: Any,
    *,
    model_name: str,
    product_name: str,
    permit_numbers: Iterable[str],
) -> SafetyStateCompat:
    """Preserve Safety semantics when Streamlit retains an older safety-support module.

    This translator intentionally never creates RED from Service04 model/product results because
    that response does not prove the exact MFDS permit scope. Positive rows remain AMBER until an
    exact product/permit relationship is verified.
    """

    model = str(model_name or "").strip()
    product = str(product_name or "").strip()
    permits = _unique_text(permit_numbers)
    keys = _search_keys(model, permits)
    status = str(getattr(lookup, "status", "") or "")
    checked_at = getattr(lookup, "checked_at", None)
    source_url = getattr(lookup, "source_url", None)

    if status == "not_authorized":
        return SafetyStateCompat(
            status=SafetyDisplayStatus.NOT_AUTHORIZED,
            evidence_status=SafetyEvidenceStatus.NOT_CONNECTED,
            message=(
                "식약처 회수·판매중지 API 활용승인이 현재 서비스키에 등록되지 않았습니다. "
                "공공데이터포털에서 해당 서비스 활용신청 승인 후 자동조회가 활성화됩니다."
            ),
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            search_keys=keys,
        )

    if status == "failure":
        return SafetyStateCompat(
            status=SafetyDisplayStatus.ERROR,
            evidence_status=SafetyEvidenceStatus.CHECK_FAILED,
            message=(
                "식약처 회수·판매중지 API 조회가 실패했습니다. "
                "0건으로 해석하지 말고 공식 페이지에서 직접 확인해야 합니다."
            ),
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            search_keys=keys,
        )

    if status == "success_0":
        basis = f"형명 '{model}'" if model else f"품목명 '{product}'"
        return SafetyStateCompat(
            status=SafetyDisplayStatus.NO_MATCH,
            evidence_status=SafetyEvidenceStatus.CHECKED_NONE,
            message=(
                "식약처 회수·판매중지 API를 정상 조회했으며 "
                f"{basis} exact 일치 기록을 확인하지 못했습니다. "
                "이는 제품이 안전하다는 판정이 아니며 다른 안전정보 Source는 별도 확인합니다."
            ),
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            search_keys=keys,
        )

    records = tuple(getattr(lookup, "records", ()) or ())
    if status == "success" and records:
        return SafetyStateCompat(
            status=SafetyDisplayStatus.CHECK_REQUIRED,
            evidence_status=SafetyEvidenceStatus.AMBER,
            message=(
                "식약처 공식 회수·판매중지 API에서 관련 기록 "
                f"{len(records)}건을 확인했습니다. 현재 Service04 형명/품목 응답에는 exact "
                "식약처 품목번호가 없어 해당 허가제품 대상인지 원문에서 추가 확인해야 합니다."
            ),
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            search_keys=keys,
        )

    if status == "not_configured":
        return SafetyStateCompat(
            status=SafetyDisplayStatus.NOT_CONNECTED,
            evidence_status=SafetyEvidenceStatus.NOT_CONNECTED,
            message=(
                "식약처 회수·판매중지 API 서비스키가 연결되지 않았습니다. "
                "자동조회 미연결 상태는 공식 안전정보 확인 결과가 아닙니다."
            ),
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            search_keys=keys,
        )

    if model or permits:
        return SafetyStateCompat(
            status=SafetyDisplayStatus.CHECK_REQUIRED,
            evidence_status=SafetyEvidenceStatus.NOT_CONNECTED,
            message=(
                "회수·판매중지 자동조회 상태를 확정하지 못했습니다. 아래 exact 모델/식약처 "
                "품목번호로 공식 회수·판매중지, 행정처분, 안전성서한을 직접 확인하세요."
            ),
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            search_keys=keys,
        )

    return SafetyStateCompat(
        status=SafetyDisplayStatus.NOT_CONNECTED,
        evidence_status=SafetyEvidenceStatus.NOT_CONNECTED,
        message=(
            "회수·판매중지 자동조회 상태를 확정하지 못했고 exact 모델/식약처 품목번호도 "
            "확보되지 않았습니다. 제품 identity를 먼저 확인해야 합니다."
        ),
        checked_at=checked_at,
        source_url=source_url,
    )


def build_safety_state_compat(
    *,
    safety_support_module: Any,
    lookup: Any,
    model_name: str = "",
    product_name: str = "",
    permit_numbers: Iterable[str] = (),
) -> Any:
    """Use the current Safety builder when present, otherwise preserve the same semantics locally."""

    builder = getattr(
        safety_support_module,
        "build_safety_state_from_recall_lookup",
        None,
    )
    if lookup is not None and callable(builder):
        return builder(
            lookup,
            model_name=model_name,
            product_name=product_name,
            permit_numbers=permit_numbers,
        )
    return _fallback_from_lookup(
        lookup,
        model_name=model_name,
        product_name=product_name,
        permit_numbers=permit_numbers,
    )
