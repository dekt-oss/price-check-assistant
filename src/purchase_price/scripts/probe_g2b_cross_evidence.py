from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingCollector,
    G2BShoppingOperation,
)
from purchase_price.config import get_settings
from purchase_price.services.g2b_contract_evidence import G2B_CONTRACT_BASE_URL
from purchase_price.services.g2b_contract_research import (
    G2BContractResearchClient,
    parse_contract_research,
)


DEFAULT_PRODUCT_NAMES = ("레이저프린터", "인공호흡기", "전신가스마취기")
_SECRET_QUERY_RE = re.compile(r"(?i)(serviceKey|service_key|authorization)=([^&\s]+)")


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    text = _SECRET_QUERY_RE.sub(r"\1=[REDACTED]", text)
    return text[:500] if text else type(exc).__name__


def _normalize_product_names(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = " ".join(value.split()).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    if not normalized:
        raise ValueError("at least one product name is required")
    return tuple(normalized)


def _dedupe_by_record_id(
    records: Sequence[Any],
) -> tuple[list[Any], int, int]:
    unique: list[Any] = []
    seen: set[str] = set()
    duplicates = 0
    unkeyed = 0
    for index, record in enumerate(records):
        record_id = str(getattr(record, "source_record_id", "") or "").strip()
        if not record_id:
            unkeyed += 1
            record_id = f"__unkeyed__:{index}"
        if record_id in seen:
            duplicates += 1
            continue
        seen.add(record_id)
        unique.append(record)
    return unique, duplicates, unkeyed


def _source_status(record_count: int) -> str:
    return "success" if record_count else "success_0"


def _build_live_clients(
    *,
    timeout_seconds: float,
    max_retries: int,
) -> tuple[G2BShoppingCollector | None, G2BContractResearchClient | None, dict[str, str]]:
    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    research_key = (settings.resolved_g2b_research_service_key or "").strip()
    sources = {
        "shopping_key_source": settings.g2b_shopping_key_source,
        "research_key_source": settings.g2b_research_key_source,
    }

    shopping: G2BShoppingCollector | None = None
    if shopping_key:
        shopping = G2BShoppingCollector(
            shopping_key,
            base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            client=PublicDataPortalClient(
                shopping_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            ),
        )

    contract: G2BContractResearchClient | None = None
    if research_key:
        contract = G2BContractResearchClient(
            research_key,
            base_url=settings.g2b_contract_base_url or G2B_CONTRACT_BASE_URL,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    return shopping, contract, sources


def _measure_case(
    *,
    product_name: str,
    begin: date,
    end: date,
    shopping_collector: G2BShoppingCollector,
    contract_client: G2BContractResearchClient,
) -> dict[str, Any]:
    shopping_report: dict[str, Any]
    try:
        page, payload = shopping_collector.fetch_specific_item_page(
            detail_product_name=product_name,
            begin_date=begin,
            end_date=end,
            page_no=1,
            num_of_rows=100,
            final_change_order_only="Y",
        )
        parsed = shopping_collector.parse_payload(
            payload,
            operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
        )
        unique, duplicates, unkeyed = _dedupe_by_record_id(parsed)
        shopping_report = {
            "status": _source_status(len(page.items)),
            "reported_total_count": page.total_count,
            "raw_record_count": len(page.items),
            "direct_price_record_count": len(parsed),
            "unique_direct_price_record_count": len(unique),
            "duplicates_removed": duplicates,
            "unkeyed_record_count": unkeyed,
            "sample_record_ids": [
                record.source_record_id for record in unique[:5] if record.source_record_id
            ],
        }
    except Exception as exc:
        shopping_report = {
            "status": "failure",
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
        }

    contract_report: dict[str, Any]
    try:
        page = contract_client.fetch_product_search_page(
            product_name=product_name,
            begin_date=begin,
            end_date=end,
            page_no=1,
            num_of_rows=100,
        )
        parsed = [
            parse_contract_research(record, search_term=product_name) for record in page.items
        ]
        unique, duplicates, unkeyed = _dedupe_by_record_id(parsed)
        contract_report = {
            "status": _source_status(len(page.items)),
            "reported_total_count": page.total_count,
            "raw_record_count": len(page.items),
            "unique_contract_record_count": len(unique),
            "duplicates_removed": duplicates,
            "unkeyed_record_count": unkeyed,
            "sample_record_ids": [record.source_record_id for record in unique[:5]],
            "direct_price_record_count": 0,
        }
    except Exception as exc:
        contract_report = {
            "status": "failure",
            "error_type": type(exc).__name__,
            "error_message": _safe_error(exc),
            "direct_price_record_count": 0,
        }

    both_sources_success = (
        shopping_report["status"] != "failure" and contract_report["status"] != "failure"
    )
    shopping_hit = shopping_report.get("unique_direct_price_record_count", 0) > 0
    contract_hit = contract_report.get("unique_contract_record_count", 0) > 0

    return {
        "product_name": product_name,
        "shopping": shopping_report,
        "contract": contract_report,
        "both_sources_success": both_sources_success,
        "shopping_direct_hit": shopping_hit,
        "contract_hit": contract_hit,
        "cross_evidence_hit": both_sources_success and shopping_hit and contract_hit,
        "independent_source_count": int(shopping_hit) + int(contract_hit),
    }


def build_report(
    *,
    product_names: Sequence[str],
    lookback_days: int,
    timeout_seconds: float = 15.0,
    max_retries: int = 1,
    today: date | None = None,
    shopping_collector: G2BShoppingCollector | None = None,
    contract_client: G2BContractResearchClient | None = None,
    key_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")

    names = _normalize_product_names(product_names)
    sources = key_sources or {}
    if shopping_collector is None or contract_client is None:
        live_shopping, live_contract, live_sources = _build_live_clients(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        shopping_collector = shopping_collector or live_shopping
        contract_client = contract_client or live_contract
        sources = {**live_sources, **sources}

    missing: list[str] = []
    if shopping_collector is None:
        missing.append("shopping_service_key")
    if contract_client is None:
        missing.append("research_service_key")
    if missing:
        return {
            "validation_status": "not_configured",
            "missing": missing,
            "product_names": list(names),
            "lookback_days": lookback_days,
            **sources,
        }

    end = today or date.today()
    begin = end - timedelta(days=lookback_days - 1)
    cases = [
        _measure_case(
            product_name=name,
            begin=begin,
            end=end,
            shopping_collector=shopping_collector,
            contract_client=contract_client,
        )
        for name in names
    ]

    eligible = [case for case in cases if case["both_sources_success"]]
    cross_hits = sum(1 for case in eligible if case["cross_evidence_hit"])
    failures = sum(1 for case in cases if not case["both_sources_success"])

    return {
        "validation_status": "pass" if failures == 0 else "partial_failure",
        "coverage_start": begin.isoformat(),
        "coverage_end": end.isoformat(),
        "lookback_days": lookback_days,
        "case_count": len(cases),
        "both_sources_success_case_count": len(eligible),
        "source_failure_case_count": failures,
        "shopping_direct_hit_case_count": sum(
            1 for case in eligible if case["shopping_direct_hit"]
        ),
        "contract_hit_case_count": sum(1 for case in eligible if case["contract_hit"]),
        "cross_evidence_case_count": cross_hits,
        "cross_evidence_rate": (cross_hits / len(eligible)) if eligible else None,
        "cases": cases,
        **sources,
        "safety_contract": {
            "contract_total_promoted_to_direct_price": False,
            "cross_source_records_collapsed_without_verified_link_key": False,
            "cross_evidence_is_automatic_quote_comparability": False,
            "dedupe_scope": "within each source by stable source_record_id",
        },
    }


def _parse_names(raw: str) -> tuple[str, ...]:
    return _normalize_product_names(raw.split(","))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure bounded G2B Shopping direct-price and independent contract cross-evidence "
            "coverage without promoting contract totals into unit prices."
        )
    )
    parser.add_argument(
        "--product-names",
        default=",".join(DEFAULT_PRODUCT_NAMES),
        help="Comma-separated PPS product names.",
    )
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        product_names=_parse_names(args.product_names),
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
