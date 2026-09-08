from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2BShoppingCollector
from purchase_price.config import get_settings


def build_report(
    *,
    detail_product_code: str,
    lookback_days: int,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, object]:
    settings = get_settings()
    key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not key:
        return {
            "validation_status": "not_configured",
            "detail_product_code": detail_product_code,
            "record_count": 0,
        }

    end = date.today()
    begin = end - timedelta(days=lookback_days - 1)
    client = PublicDataPortalClient(
        key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    collector = G2BShoppingCollector(
        key,
        base_url=settings.g2b_shopping_base_url
        or "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService",
        client=client,
    )
    try:
        page, _ = collector.fetch_specific_item_page(
            detail_product_code=detail_product_code,
            begin_date=begin,
            end_date=end,
            page_no=1,
            num_of_rows=100,
        )
    except Exception as exc:
        return {
            "validation_status": "failure",
            "detail_product_code": detail_product_code,
            "begin_date": begin.isoformat(),
            "end_date": end.isoformat(),
            "record_count": 0,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }

    wrong_codes = sorted(
        {
            str(item.get("dtilPrdctClsfcNo") or "").strip()
            for item in page.items
            if str(item.get("dtilPrdctClsfcNo") or "").strip()
            and str(item.get("dtilPrdctClsfcNo") or "").strip() != detail_product_code
        }
    )
    return {
        "validation_status": "pass" if page.items and not wrong_codes else "unexpected_result",
        "detail_product_code": detail_product_code,
        "begin_date": begin.isoformat(),
        "end_date": end.isoformat(),
        "record_count": len(page.items),
        "reported_total_count": page.total_count,
        "wrong_detail_product_codes": wrong_codes,
        "sample_product_ids": [
            str(item.get("prdctIdntNo") or "").strip() for item in page.items[:10]
        ],
        "safety_contract": {
            "query_code_auto_verified_for_quote": False,
            "records_promoted_to_direct_price": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Live-probe targeted PPS detail-class shopping search")
    parser.add_argument("--detail-product-code", default="4110449801")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        detail_product_code=args.detail_product_code,
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
