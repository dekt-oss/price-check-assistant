from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from purchase_price.config import get_settings
from purchase_price.services.g2b_contract_evidence import G2B_CONTRACT_BASE_URL
from purchase_price.services.g2b_contract_research import G2BContractResearchClient

DEFAULT_PRODUCT_NAME = "레이저프린터"


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:500] if text else type(exc).__name__


def build_report(
    *,
    product_name: str,
    lookback_days: int,
    timeout_seconds: float,
    max_retries: int,
    today: date | None = None,
) -> dict[str, Any]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")

    settings = get_settings()
    key = (settings.resolved_g2b_contract_service_key or "").strip()
    if not key:
        return {
            "validation_status": "not_configured",
            "key_source": settings.g2b_contract_key_source,
            "product_name": product_name,
            "lookback_days": lookback_days,
        }

    end = today or date.today()
    begin = end - timedelta(days=lookback_days - 1)
    try:
        records, request_count = G2BContractResearchClient(
            key,
            base_url=settings.g2b_contract_base_url or G2B_CONTRACT_BASE_URL,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        ).search_by_product_name(
            product_name=product_name,
            begin_date=begin,
            end_date=end,
            max_pages_per_window=1,
        )
    except Exception as exc:
        return {
            "validation_status": "environment_or_access_failure",
            "key_source": settings.g2b_contract_key_source,
            "product_name": product_name,
            "lookback_days": lookback_days,
            "coverage_start": begin.isoformat(),
            "coverage_end": end.isoformat(),
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
            "safety_contract": {
                "direct_price_promotion_performed": False,
                "contract_total_is_unit_price": False,
            },
        }

    return {
        "validation_status": "pass",
        "source_status": "success" if records else "success_0",
        "key_source": settings.g2b_contract_key_source,
        "product_name": product_name,
        "lookback_days": lookback_days,
        "coverage_start": begin.isoformat(),
        "coverage_end": end.isoformat(),
        "request_count": request_count,
        "record_count": len(records),
        "sample_records": [
            {
                "contract_no": record.contract_no,
                "bid_notice_no": record.bid_notice_no,
                "title": record.title,
                "product_name": record.product_name,
                "institution": record.institution,
                "supplier": record.supplier,
                "published_date": (
                    record.published_date.isoformat() if record.published_date else None
                ),
                "amount": str(record.amount) if record.amount is not None else None,
                "amount_type": record.amount_type.value,
                "search_term": record.search_term,
                "source_url": record.source_url,
            }
            for record in records[:5]
        ],
        "safety_contract": {
            "direct_price_promotion_performed": False,
            "contract_total_is_unit_price": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe PPS independent goods-contract search")
    parser.add_argument("--product-name", default=DEFAULT_PRODUCT_NAME)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        product_name=args.product_name,
        lookback_days=args.lookback_days,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["validation_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
