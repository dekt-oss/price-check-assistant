from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2BCatalogClient
from purchase_price.services.g2b_lifecycle import G2BLifecycleClient, G2BLifecycleInquiry

# Known identifiers are evidence fixtures, not product mappings. Apeos product id was observed in
# the live Shopping UAT; the lifecycle bid number is the request example published in PPS reference
# v1.0. Neither value is promoted to price evidence by this probe.
DEFAULT_CATALOG_PRODUCT_ID = "24888744"
DEFAULT_LIFECYCLE_BID_NOTICE = "20160234982"


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


def build_report(*, product_id: str, bid_notice_no: str) -> dict[str, Any]:
    catalog = _probe_catalog(product_id=product_id)
    lifecycle = _probe_lifecycle(bid_notice_no=bid_notice_no)
    normal = {"success", "success_0"}
    return {
        "validation_status": (
            "pass" if catalog.get("status") in normal and lifecycle.get("status") in normal else "failure"
        ),
        "catalog": catalog,
        "lifecycle": lifecycle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe PPS catalog and procurement lifecycle APIs")
    parser.add_argument("--product-id", default=DEFAULT_CATALOG_PRODUCT_ID)
    parser.add_argument("--bid-notice-no", default=DEFAULT_LIFECYCLE_BID_NOTICE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(product_id=args.product_id, bid_notice_no=args.bid_notice_no)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["validation_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
