from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    ResearchSourceStatus,
)
from purchase_price.services.market_research import research_g2b_market


def _record_summary(record: G2BResearchRecord) -> dict[str, Any]:
    return {
        "source_type": record.source_type.value,
        "source_record_id": record.source_record_id,
        "title": record.title,
        "institution": record.institution,
        "published_date": record.published_date.isoformat() if record.published_date else None,
        "bid_notice_no": record.bid_notice_no,
        "prespec_no": record.prespec_no,
        "amount": str(record.amount) if record.amount is not None else None,
        "amount_type": record.amount_type.value,
        "supplier": record.supplier,
        "source_url": record.source_url,
        "attachment_count": len(record.attachments),
        "search_term": record.search_term,
    }


def build_report(
    *,
    keyword: str,
    lookback_days: int,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, Any]:
    settings = get_settings()
    key = (settings.resolved_g2b_research_service_key or "").strip()
    key_source = settings.g2b_research_key_source
    if not key:
        return {
            "validation_status": "not_configured",
            "keyword": keyword,
            "lookback_days": lookback_days,
            "key_source": key_source,
            "sources": [],
            "message": "G2B research service key is not configured.",
        }

    bundle = research_g2b_market(
        ProductQuery(product_name=keyword),
        service_key=key,
        lookback_days=lookback_days,
        today=date.today(),
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_terms=1,
        max_pages_per_window=1,
    )
    source_rows = []
    for source in bundle.sources:
        source_rows.append(
            {
                "source": source.source.value,
                "status": source.status.value,
                "record_count": len(source.records),
                "request_count": source.request_count,
                "error_type": source.error_type,
                "error_message": source.error_message,
                "sample_records": [_record_summary(record) for record in source.records[:5]],
            }
        )

    statuses = {source.status for source in bundle.sources}
    normal_statuses = {ResearchSourceStatus.SUCCESS, ResearchSourceStatus.SUCCESS_0}
    if statuses and statuses.issubset(normal_statuses):
        validation_status = "pass"
    elif ResearchSourceStatus.NOT_AUTHORIZED in statuses:
        validation_status = "not_authorized"
    else:
        validation_status = "environment_or_access_failure"

    return {
        "validation_status": validation_status,
        "keyword": keyword,
        "lookback_days": lookback_days,
        "key_source": key_source,
        "query_terms": list(bundle.query_terms),
        "research_record_count": len(bundle.records),
        "sources": source_rows,
        "safety_contract": {
            "research_only": True,
            "direct_price_promotion_performed": False,
            "award_total_is_unit_price": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded live G2B bid/award/prespec research probe")
    parser.add_argument("--keyword", default="마취")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        keyword=args.keyword,
        lookback_days=args.lookback_days,
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
