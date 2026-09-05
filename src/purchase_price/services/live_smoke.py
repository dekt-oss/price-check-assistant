from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from time import perf_counter
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, G2BShoppingOperation, unwrap_g2b_page
from purchase_price.config import Settings, get_settings
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
)

LIVE_SUCCESS = "success"
LIVE_SUCCESS_0 = "success_0"
LIVE_FAILURE = "failure"
LIVE_NOT_READY = "not_ready"
LIVE_INVALID = "invalid"


@dataclass(frozen=True)
class LiveSmokeResult:
    source_key: str
    label: str
    status: str
    record_count: int | None
    total_count: int | None
    elapsed_ms: float
    detail: str

    @property
    def ok(self) -> bool:
        return self.status in {LIVE_SUCCESS, LIVE_SUCCESS_0}

    def to_public_dict(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "label": self.label,
            "status": self.status,
            "ok": self.ok,
            "record_count": self.record_count,
            "total_count": self.total_count,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "detail": self.detail,
        }


def _elapsed_ms(started: float) -> float:
    return max(0.0, (perf_counter() - started) * 1000)


def _not_ready(*, source_key: str, label: str) -> LiveSmokeResult:
    return LiveSmokeResult(source_key, label, LIVE_NOT_READY, None, None, 0.0, "사용 가능한 service key가 설정되지 않아 호출하지 않았습니다.")


def _invalid(*, source_key: str, label: str, field_label: str) -> LiveSmokeResult:
    return LiveSmokeResult(source_key, label, LIVE_INVALID, None, None, 0.0, f"{field_label} 입력이 없어 호출하지 않았습니다.")


def _failure(*, source_key: str, label: str, started: float, error: Exception) -> LiveSmokeResult:
    return LiveSmokeResult(source_key, label, LIVE_FAILURE, None, None, _elapsed_ms(started), f"외부 API 요청 실패 ({type(error).__name__}). 0건 조회와 구분됩니다.")


def _success_result(*, source_key: str, label: str, started: float, record_count: int, total_count: int | None) -> LiveSmokeResult:
    has_records = record_count > 0 or bool(total_count and total_count > 0)
    status = LIVE_SUCCESS if has_records else LIVE_SUCCESS_0
    detail = "공식 API가 정상 응답했고 조회 결과가 있습니다." if has_records else "공식 API가 정상 응답했지만 조회 결과는 0건입니다."
    return LiveSmokeResult(source_key, label, status, record_count, total_count, _elapsed_ms(started), detail)


def run_g2b_live_smoke(detail_product_name: str, *, lookback_days: int = 30, settings: Settings | None = None, portal_client: PublicDataPortalClient | None = None, today: date | None = None) -> LiveSmokeResult:
    label, source_key = "G2B Shopping", "g2b_shopping"
    query = detail_product_name.strip()
    if not query:
        return _invalid(source_key=source_key, label=label, field_label="세부품명")
    if lookback_days not in {30, 90, 180, 365}:
        return _invalid(source_key=source_key, label=label, field_label="조회기간")
    settings = settings or get_settings()
    service_key = (settings.resolved_g2b_service_key or "").strip()
    if not service_key:
        return _not_ready(source_key=source_key, label=label)
    end_date = today or date.today()
    begin_date = end_date - timedelta(days=lookback_days)
    client = portal_client or PublicDataPortalClient(service_key, timeout_seconds=settings.g2b_request_timeout_seconds, max_retries=settings.g2b_max_retries)
    started = perf_counter()
    try:
        payload = client.get_json(settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL, G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value, pageNo=1, numOfRows=1, inqryDiv=1, inqryBgnDate=begin_date.strftime("%Y%m%d"), inqryEndDate=end_date.strftime("%Y%m%d"), inqryPrdctDiv=2, fnlCntrctDlvrReqChgOrdYn="Y", dtilPrdctClsfcNoNm=query)
        page = unwrap_g2b_page(payload)
    except (PublicDataClientError, ValueError, OSError) as exc:
        return _failure(source_key=source_key, label=label, started=started, error=exc)
    return _success_result(source_key=source_key, label=label, started=started, record_count=len(page.items), total_count=page.total_count)


def run_mfds_model_live_smoke(product_name: str, *, settings: Settings | None = None, model_client: MfdsModelInfoClient | None = None) -> LiveSmokeResult:
    label, source_key = "MFDS 품목/모델", "mfds_model"
    query = product_name.strip()
    if not query:
        return _invalid(source_key=source_key, label=label, field_label="공식 품목명")
    settings = settings or get_settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if not service_key:
        return _not_ready(source_key=source_key, label=label)
    client = model_client or MfdsModelInfoClient(service_key, base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL, timeout_seconds=settings.mfds_request_timeout_seconds, max_retries=settings.mfds_max_retries)
    started = perf_counter()
    try:
        page = client.fetch_page(product_name=query, page_no=1, num_of_rows=1)
    except (PublicDataClientError, ValueError, OSError) as exc:
        return _failure(source_key=source_key, label=label, started=started, error=exc)
    return _success_result(source_key=source_key, label=label, started=started, record_count=len(page.items), total_count=page.total_count)


def run_mfds_business_live_smoke(company_name: str, *, settings: Settings | None = None, business_client: MfdsBusinessLicenseClient | None = None) -> LiveSmokeResult:
    label, source_key = "MFDS 업체", "mfds_business"
    query = company_name.strip()
    if not query:
        return _invalid(source_key=source_key, label=label, field_label="업체명")
    settings = settings or get_settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if not service_key:
        return _not_ready(source_key=source_key, label=label)
    client = business_client or MfdsBusinessLicenseClient(service_key, base_url=settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL, timeout_seconds=settings.mfds_request_timeout_seconds, max_retries=settings.mfds_max_retries)
    started = perf_counter()
    try:
        records = client.search_company(query, page_no=1, num_of_rows=1)
    except (PublicDataClientError, ValueError, OSError) as exc:
        return _failure(source_key=source_key, label=label, started=started, error=exc)
    return _success_result(source_key=source_key, label=label, started=started, record_count=len(records), total_count=None)


def result_from_public_dict(payload: dict[str, Any]) -> LiveSmokeResult:
    return LiveSmokeResult(source_key=str(payload["source_key"]), label=str(payload["label"]), status=str(payload["status"]), record_count=None if payload.get("record_count") is None else int(payload["record_count"]), total_count=None if payload.get("total_count") is None else int(payload["total_count"]), elapsed_ms=float(payload.get("elapsed_ms") or 0.0), detail=str(payload["detail"]))
