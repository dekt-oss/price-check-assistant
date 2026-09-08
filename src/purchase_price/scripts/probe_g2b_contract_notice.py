from __future__ import annotations

import argparse
import json
from pathlib import Path

from purchase_price.config import get_settings
from purchase_price.services.g2b_contract_research import G2BContractResearchClient


def build_report(
    *,
    bid_notice_no: str,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, object]:
    settings = get_settings()
    key = (settings.resolved_g2b_research_service_key or "").strip()
    if not key:
        return {
            "validation_status": "not_configured",
            "bid_notice_no": bid_notice_no,
            "record_count": 0,
            "message": "G2B research service key is not configured.",
        }

    client = G2BContractResearchClient(
        key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    try:
        records, request_count = client.search_by_bid_notice(
            bid_notice_no=bid_notice_no,
            max_pages=1,
        )
    except Exception as exc:
        return {
            "validation_status": "failure",
            "bid_notice_no": bid_notice_no,
            "record_count": 0,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }

    matching = [record for record in records if record.bid_notice_no == bid_notice_no]
    return {
        "validation_status": "pass" if matching else "unexpected_zero_or_unlinked",
        "bid_notice_no": bid_notice_no,
        "request_count": request_count,
        "record_count": len(records),
        "matching_notice_count": len(matching),
        "contract_numbers": [record.contract_no for record in matching[:5]],
        "safety_contract": {
            "contract_totals_are_research_only": True,
            "direct_unit_price_promotion_performed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate PPS goods-contract lookup by notice number")
    parser.add_argument("--bid-notice-no", default="20160234982")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        bid_notice_no=args.bid_notice_no,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
