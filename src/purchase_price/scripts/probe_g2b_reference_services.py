from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2BCatalogClient
from purchase_price.services.g2b_classification_resolver import (
    DetailClassSearchField,
    G2BClassificationResolverClient,
)
from purchase_price.services.g2b_lifecycle import G2BLifecycleClient, G2BLifecycleInquiry

# Known identifiers are evidence fixtures, not product mappings. Apeos product id was observed in
# the live Shopping UAT; the lifecycle bid number is the request example published in PPS reference
# v1.0. The CO2-incubator detail class is a known official classification fixture used only to
# validate the classification-search operation. None is promoted to quote identity or price evidence.
DEFAULT_CATALOG_PRODUCT_ID = "24888744"
DEFAULT_LIFECYCLE_BID_NOTICE = "20160234982"
DEFAULT_DETAIL_CLASS_ENGLISH_NAME = "Carbon dioxide incubators"
DEFAULT_DETAIL_CLASS_CODE = "4110449801"


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:500] if text else type(exc).__name__


def _probe_catalog(*, product_id: str) -> dict[str, Any]:
    settings = get_settings()
    key = (settings.resolved_g2b_catalog_service_key or "").strip()
    if not key:
        return {
            "status": "not_configured",
            "key_source": settings.g2b_catalog_key_source,
            "product_id": product_id,
        }
    try:
        result = G2BCatalogClient(
            key,
            base_url=settings.g2b_catalog_base_url
            or "https://apis.data.go.kr/1230000/ao/ThngListInfoService02",
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
        ).fetch_attributes(product_id=product_id)
    except Exception as exc:
        return {
            "status": "failure",
            "key_source": settings.g2b_catalog_key_source,
            "product_id": product_id,
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
        }
    return {
        "status": "success" if result.attributes else "success_0",
        "key_source": settings.g2b_catalog_key_source,
        "product_id": product_id,
        "attribute_count": len(result.attributes),
        "detail_product_codes": list(result.detail_product_codes),
        "sample_attributes": [
            {
                "product_name": row.product_name,
                "detail_product_code": row.detail_product_code,
                "attribute_name": row.attribute_name,
                "attribute_value": row.attribute_value,
                "attribute_unit": row.attribute_unit,
            }
            for row in result.attributes[:10]
        ],
    }


def _probe_detail_classification(*, english_name: str, expected_code: str) -> dict[str, Any]:
    settings = get_settings()
    key = (settings.resolved_g2b_catalog_service_key or "").strip()
    if not key:
        return {
            "status": "not_configured",
            "key_source": settings.g2b_catalog_key_source,
            "english_name": english_name,
            "expected_code": expected_code,
        }
    try:
        result = G2BClassificationResolverClient(
            key,
            base_url=settings.g2b_catalog_base_url
            or "https://apis.data.go.kr/1230000/ao/ThngListInfoService02",
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
        ).search_detail_classes(
            term=english_name,
            field=DetailClassSearchField.ENGLISH_NAME,
            num_of_rows=100,
        )
    except Exception as exc:
        return {
            "status": "failure",
            "key_source": settings.g2b_catalog_key_source,
            "english_name": english_name,
            "expected_code": expected_code,
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
        }

    codes = [candidate.detail_product_code for candidate in result.candidates]
    return {
        "status": "success" if expected_code in codes else "unexpected_result",
        "key_source": settings.g2b_catalog_key_source,
        "english_name": english_name,
        "expected_code": expected_code,
        "candidate_count": len(result.candidates),
        "total_count": result.total_count,
        "candidate_codes": codes[:20],
        "sample_candidates": [
            {
                "detail_product_code": candidate.detail_product_code,
                "korean_name": candidate.korean_name,
                "english_name": candidate.english_name,
                "use_status": candidate.use_status,
            }
            for candidate in result.candidates[:10]
        ],
        "safety_contract": {
            "candidate_auto_verified": False,
            "mapping_file_written": False,
            "direct_price_promotion_performed": False,
        },
    }


def _probe_lifecycle(*, bid_notice_no: str) -> dict[str, Any]:
    settings = get_settings()
    key = (settings.resolved_g2b_lifecycle_service_key or "").strip()
    if not key:
        return {
            "status": "not_configured",
            "key_source": settings.g2b_lifecycle_key_source,
            "bid_notice_no": bid_notice_no,
        }
    try:
        result = G2BLifecycleClient(
            key,
            base_url=settings.g2b_lifecycle_base_url
            or "https://apis.data.go.kr/1230000/ao/CntrctProcssIntgOpenService",
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
        ).fetch(
            inquiry=G2BLifecycleInquiry.BID_NOTICE,
            identifier=bid_notice_no,
            num_of_rows=5,
        )
    except Exception as exc:
        return {
            "status": "failure",
            "key_source": settings.g2b_lifecycle_key_source,
            "bid_notice_no": bid_notice_no,
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
        }
    return {
        "status": "success" if result.records else "success_0",
        "key_source": settings.g2b_lifecycle_key_source,
        "bid_notice_no": bid_notice_no,
        "record_count": len(result.records),
        "sample_records": [
            {
                "order_plan_no": row.order_plan_no,
                "prespec_no": row.prespec_no,
                "bid_notice_no": row.bid_notice_no,
                "bid_notice_name": row.bid_notice_name,
                "procurement_request_no": row.procurement_request_no,
                "has_award_info": bool(row.award_info_list),
                "has_contract_info": bool(row.contract_info_list),
            }
            for row in result.records[:5]
        ],
        "safety_contract": {
            "award_list_promoted_to_unit_price": False,
            "contract_list_promoted_to_unit_price": False,
        },
    }


def build_report(
    *,
    product_id: str,
    bid_notice_no: str,
    detail_class_english_name: str = DEFAULT_DETAIL_CLASS_ENGLISH_NAME,
    expected_detail_class_code: str = DEFAULT_DETAIL_CLASS_CODE,
) -> dict[str, Any]:
    catalog = _probe_catalog(product_id=product_id)
    classification = _probe_detail_classification(
        english_name=detail_class_english_name,
        expected_code=expected_detail_class_code,
    )
    lifecycle = _probe_lifecycle(bid_notice_no=bid_notice_no)
    normal = {"success", "success_0"}
    return {
        "validation_status": (
            "pass"
            if catalog.get("status") in normal
            and classification.get("status") == "success"
            and lifecycle.get("status") in normal
            else "failure"
        ),
        "catalog": catalog,
        "classification": classification,
        "lifecycle": lifecycle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe PPS catalog, classification and lifecycle APIs")
    parser.add_argument("--product-id", default=DEFAULT_CATALOG_PRODUCT_ID)
    parser.add_argument("--bid-notice-no", default=DEFAULT_LIFECYCLE_BID_NOTICE)
    parser.add_argument("--detail-class-english-name", default=DEFAULT_DETAIL_CLASS_ENGLISH_NAME)
    parser.add_argument("--expected-detail-class-code", default=DEFAULT_DETAIL_CLASS_CODE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        product_id=args.product_id,
        bid_notice_no=args.bid_notice_no,
        detail_class_english_name=args.detail_class_english_name,
        expected_detail_class_code=args.expected_detail_class_code,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["validation_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
