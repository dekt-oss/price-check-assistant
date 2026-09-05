from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import get_settings
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_MODEL_INFO_BASE_URL,
    MedicalDeviceBusinessRecord,
    MedicalDeviceModelRecord,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
    resolve_exact_model_identity,
)

EXPECTATIONS = ("api-only", "exact-active", "exact-ambiguous", "exact-inactive")


def build_validation_report(
    *,
    product_name: str,
    model_name: str,
    company_name: str,
    model_records: tuple[MedicalDeviceModelRecord, ...],
    business_records: tuple[MedicalDeviceBusinessRecord, ...],
    expectation: str,
) -> dict[str, Any]:
    """Build a secret-free MFDS validation summary from official response records."""

    resolution = resolve_exact_model_identity(model_records, model_name) if model_name else None
    exact_matches = resolution.exact_matches if resolution is not None else ()
    active_exact = tuple(item for item in exact_matches if item.active_for_domestic_candidate)
    inactive_exact = tuple(item for item in exact_matches if not item.active_for_domestic_candidate)
    active_businesses = tuple(item for item in business_records if item.is_active)

    expectation_met = True
    expectation_reason = "공식 API 호출 성공"
    if expectation != "api-only" and not model_name:
        expectation_met = False
        expectation_reason = "exact expectation에는 model_name이 필요함"
    elif expectation == "exact-active":
        expectation_met = bool(exact_matches) and not bool(resolution and resolution.ambiguous) and bool(
            active_exact
        )
        expectation_reason = (
            "exact 모델이 단일 permit identity로 확인되고 국내 신규구매 후보 상태임"
            if expectation_met
            else "exact active identity 조건을 충족하지 못함"
        )
    elif expectation == "exact-ambiguous":
        expectation_met = bool(resolution and resolution.ambiguous)
        expectation_reason = (
            "exact 모델이 서로 다른 복수 permit에 연결되어 ambiguous임"
            if expectation_met
            else "ambiguous exact permit 조건을 충족하지 못함"
        )
    elif expectation == "exact-inactive":
        expectation_met = bool(inactive_exact) and not bool(active_exact)
        expectation_reason = (
            "exact 모델이 확인됐지만 취소·취하 또는 수출전용으로 국내 신규구매 후보가 아님"
            if expectation_met
            else "inactive/export-only exact identity 조건을 충족하지 못함"
        )

    exact_rows = [
        {
            "permit_number": item.permit_number,
            "product_name": item.product_name,
            "model_name": item.model_name,
            "company_name": item.industry_name,
            "cancellation_status": item.cancellation_status,
            "export_only": item.export_only,
            "active_for_domestic_candidate": item.active_for_domestic_candidate,
        }
        for item in exact_matches
    ]
    business_rows = [
        {
            "company_name": item.company_name,
            "industry_type": item.industry_type,
            "business_status": item.business_status,
            "business_permit_number": item.business_permit_number,
            "is_active": item.is_active,
        }
        for item in business_records
    ]

    return {
        "source": "MFDS official public API via data.go.kr",
        "product_name": product_name,
        "model_name": model_name,
        "company_name": company_name,
        "expectation": expectation,
        "expectation_met": expectation_met,
        "expectation_reason": expectation_reason,
        "model_lookup_status": "success" if model_records else "success_0",
        "model_record_count": len(model_records),
        "exact_match_count": len(exact_matches),
        "exact_identity_confirmed": bool(exact_matches),
        "exact_identity_ambiguous": bool(resolution and resolution.ambiguous),
        "active_exact_count": len(active_exact),
        "inactive_or_export_exact_count": len(inactive_exact),
        "business_lookup_status": (
            "not_requested" if not company_name else "success" if business_records else "success_0"
        ),
        "business_record_count": len(business_records),
        "active_business_record_count": len(active_businesses),
        "exact_matches": exact_rows,
        "business_matches": business_rows,
        "safety_note": (
            "이 검증은 등록 identity/업허가 상태 확인이며 회수·판매중지 자동조회가 아니다. "
            "no-hit를 안전으로 해석하지 않는다."
        ),
    }


def _error_report(
    *, product_name: str, model_name: str, company_name: str, error: Exception
) -> dict[str, Any]:
    return {
        "source": "MFDS official public API via data.go.kr",
        "product_name": product_name,
        "model_name": model_name,
        "company_name": company_name,
        "model_lookup_status": "failure",
        "error_type": type(error).__name__,
        "error": str(error),
        "safety_note": "API 실패를 검색결과 0건 또는 안전으로 해석하지 않는다.",
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an official MFDS live validation lookup.")
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--model-name", default="")
    parser.add_argument("--company-name", default="")
    parser.add_argument("--expectation", choices=EXPECTATIONS, default="api-only")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/mfds-live-validation/report.json"),
    )
    args = parser.parse_args()

    product_name = args.product_name.strip()
    model_name = args.model_name.strip()
    company_name = args.company_name.strip()
    settings = get_settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if not service_key:
        report = _error_report(
            product_name=product_name,
            model_name=model_name,
            company_name=company_name,
            error=RuntimeError("MFDS_SERVICE_KEY or legacy DATA_GO_KR_SERVICE_KEY is not configured"),
        )
        _write_report(args.output, report)
        return 2

    try:
        model_client = MfdsModelInfoClient(
            service_key,
            base_url=settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL,
            timeout_seconds=settings.mfds_request_timeout_seconds,
            max_retries=settings.mfds_max_retries,
        )
        model_records = model_client.search_models(product_name)
        business_records: tuple[MedicalDeviceBusinessRecord, ...] = ()
        if company_name:
            business_client = MfdsBusinessLicenseClient(
                service_key,
                base_url=settings.mfds_business_license_base_url or MFDS_BUSINESS_LICENSE_BASE_URL,
                timeout_seconds=settings.mfds_request_timeout_seconds,
                max_retries=settings.mfds_max_retries,
            )
            business_records = business_client.search_company(company_name)
    except (PublicDataClientError, ValueError) as exc:
        report = _error_report(
            product_name=product_name,
            model_name=model_name,
            company_name=company_name,
            error=exc,
        )
        _write_report(args.output, report)
        return 2

    report = build_validation_report(
        product_name=product_name,
        model_name=model_name,
        company_name=company_name,
        model_records=model_records,
        business_records=business_records,
        expectation=args.expectation,
    )
    _write_report(args.output, report)

    print(f"model_lookup_status={report['model_lookup_status']}")
    print(f"model_record_count={report['model_record_count']}")
    print(f"exact_match_count={report['exact_match_count']}")
    print(f"exact_identity_ambiguous={report['exact_identity_ambiguous']}")
    print(f"active_exact_count={report['active_exact_count']}")
    print(f"inactive_or_export_exact_count={report['inactive_or_export_exact_count']}")
    print(f"business_lookup_status={report['business_lookup_status']}")
    print(f"expectation_met={report['expectation_met']}")
    print(f"report={args.output}")
    return 0 if report["expectation_met"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
