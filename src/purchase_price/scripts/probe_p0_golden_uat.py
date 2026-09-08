from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.services.g2b_classification_research import resolve_classification_research
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_lifecycle import G2B_LIFECYCLE_BASE_URL
from purchase_price.services.g2b_lifecycle_enrichment import enrich_market_bundle_with_lifecycle
from purchase_price.services.g2b_market_models import MarketResearchBundle
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
    discover_unmapped_g2b_candidates,
)
from purchase_price.services.market_research import research_g2b_market
from purchase_price.services.research_basis import research_terms_with_basis

APC_DETAIL_CLASS_CODE = "4110449801"


def _candidate_row(candidate: G2BDiscoveryCandidate) -> dict[str, Any]:
    return {
        "title": candidate.title,
        "classification_name": candidate.classification_name,
        "classification_code": candidate.classification_code,
        "product_id": candidate.product_id,
        "price": str(candidate.price),
        "transaction_date": (
            candidate.transaction_date.isoformat() if candidate.transaction_date else None
        ),
        "relevance": candidate.relevance,
        "search_term": candidate.search_term,
        "match_reason": candidate.match_reason,
        "institution": candidate.institution,
        "supplier": candidate.supplier,
        "quantity": str(candidate.quantity) if candidate.quantity is not None else None,
        "unit": candidate.unit,
        "item_sequence": candidate.item_sequence,
        "original_specification": candidate.original_specification,
        "delivery_condition": candidate.delivery_condition,
        "record_change_order": candidate.record_change_order,
    }


def _source_rows(bundle: MarketResearchBundle | None) -> list[dict[str, Any]]:
    if bundle is None:
        return []
    return [
        {
            "source": source.source.value,
            "status": source.status.value,
            "record_count": len(source.records),
            "request_count": source.request_count,
            "error_type": source.error_type,
            "error_message": source.error_message,
            "coverage_start": (
                source.coverage_start.isoformat() if source.coverage_start else None
            ),
            "coverage_end": source.coverage_end.isoformat() if source.coverage_end else None,
            "requested_lookback_days": source.requested_lookback_days,
            "search_strategy": source.search_strategy,
        }
        for source in bundle.sources
    ]


def _run_case(
    *,
    case_id: str,
    query: ProductQuery,
    target_codes: tuple[str, ...],
    lookback_days: int,
    request_budget: int,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, Any]:
    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    research_key = (settings.resolved_g2b_research_service_key or "").strip()
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    lifecycle_key = (settings.resolved_g2b_lifecycle_service_key or "").strip()

    classification = resolve_classification_research(
        query,
        service_key=catalog_key,
        base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    resolver_terms = classification.research_terms

    discovery = None
    if shopping_key:
        discovery = discover_unmapped_g2b_candidates(
            query,
            service_key=shopping_key,
            lookback_days=lookback_days,
            base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            pages_per_term_window=1,
            request_budget=request_budget,
            curated_terms=research_terms_with_basis(query) + resolver_terms,
            target_detail_product_codes=target_codes,
        )

    market_bundle = None
    if research_key:
        market_bundle = research_g2b_market(
            query,
            service_key=research_key,
            lookback_days=min(lookback_days, 90),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_terms=6,
            max_pages_per_window=1,
            additional_terms=resolver_terms,
        )
        market_bundle = enrich_market_bundle_with_bid_items(
            market_bundle,
            service_key=research_key,
            max_bid_notices=2,
            max_pages_per_bid=1,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        market_bundle = enrich_market_bundle_with_contracts(
            market_bundle,
            service_key=research_key,
            max_bid_notices=2,
            max_pages_per_bid=1,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            independent_terms=research_terms_with_basis(query) + resolver_terms,
            requested_lookback_days=lookback_days,
            minimum_records_before_stop=2,
            max_independent_terms=1,
            max_pages_per_window=1,
        )
        market_bundle = enrich_market_bundle_with_lifecycle(
            market_bundle,
            service_key=lifecycle_key,
            max_bid_notices=2,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            base_url=settings.g2b_lifecycle_base_url or G2B_LIFECYCLE_BASE_URL,
        )

    candidates = list(discovery.candidates) if discovery is not None else []
    model_candidates = [
        candidate for candidate in candidates if candidate.relevance == "모델 표기 후보"
    ]
    related_candidates = [
        candidate for candidate in candidates if candidate.relevance != "모델 표기 후보"
    ]

    safety_violations: list[str] = []
    if case_id == "apc30d":
        for candidate in model_candidates:
            if "apc30d" not in candidate.title.casefold().replace("-", "").replace(" ", ""):
                safety_violations.append(
                    f"non-APC candidate promoted to same-model Research: {candidate.title}"
                )
    if case_id == "flow_c":
        for candidate in model_candidates:
            normalized = candidate.title.casefold().replace("-", "").replace(" ", "")
            if "flowc20" in normalized:
                safety_violations.append(
                    f"FLOW-C20 promoted to FLOW-C same-model Research: {candidate.title}"
                )
            if any(
                marker in candidate.title.casefold()
                for marker in ("accessory", "accessories", "액세서리", "부속품", "부품")
            ):
                safety_violations.append(
                    f"accessory promoted to FLOW-C same-model Research: {candidate.title}"
                )

    return {
        "case_id": case_id,
        "query": asdict(query),
        "classification_status": classification.status.value,
        "classification_lookup_terms": [
            request.term for request in classification.lookup_requests
        ],
        "classification_specification_clues": list(classification.specification_clues),
        "classification_candidates": [
            {
                "detail_product_code": candidate.detail_product_code,
                "korean_name": candidate.korean_name,
                "english_name": candidate.english_name,
                "use_status": candidate.use_status,
                "search_term": candidate.search_term,
            }
            for candidate in classification.candidates[:20]
        ],
        "target_detail_codes": list(target_codes),
        "shopping_status": discovery.status if discovery is not None else "not_configured",
        "shopping_request_count": discovery.request_count if discovery is not None else 0,
        "shopping_error_types": list(discovery.error_types) if discovery is not None else [],
        "shopping_error_messages": (
            list(discovery.error_messages) if discovery is not None else []
        ),
        "same_model_status": "observed" if model_candidates else "unconfirmed",
        "same_model_candidates": [_candidate_row(row) for row in model_candidates[:10]],
        "related_candidates": [_candidate_row(row) for row in related_candidates[:10]],
        "procurement_sources": _source_rows(market_bundle),
        "safety_violations": safety_violations,
        "safety_contract": {
            "targeted_class_is_quote_identity": False,
            "related_price_is_same_model_price": False,
            "contract_total_is_unit_price": False,
            "prespec_or_bid_budget_is_unit_price": False,
            "unknown_configuration_is_match": False,
        },
    }


def build_report(
    *,
    lookback_days: int,
    request_budget: int,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, Any]:
    cases = [
        _run_case(
            case_id="apc30d",
            query=ProductQuery(
                product_name="CO₂ Incubator(Water Jacket)",
                manufacturer="ASTEC",
                model_name="APC-30D",
            ),
            target_codes=(APC_DETAIL_CLASS_CODE,),
            lookback_days=lookback_days,
            request_budget=request_budget,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        ),
        _run_case(
            case_id="flow_c",
            query=ProductQuery(
                product_name="가스 마취기",
                manufacturer="Maquet",
                model_name="FLOW-C",
            ),
            target_codes=(),
            lookback_days=lookback_days,
            request_budget=request_budget,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        ),
    ]

    violations = [
        violation
        for case in cases
        for violation in case.get("safety_violations", [])
    ]
    source_failures = [
        source
        for case in cases
        for source in case.get("procurement_sources", [])
        if source.get("status") in {"failure", "not_authorized"}
    ]
    shopping_failures = [case for case in cases if case["shopping_status"] == "failure"]
    classification_failures = [
        case for case in cases if case["classification_status"] == "failure"
    ]

    if violations:
        validation_status = "safety_violation"
    elif source_failures or shopping_failures or classification_failures:
        validation_status = "partial_or_environment_failure"
    else:
        validation_status = "pass"

    return {
        "validation_status": validation_status,
        "lookback_days": lookback_days,
        "cases": cases,
        "safety_violation_count": len(violations),
        "safety_violations": violations,
        "acceptance_note": (
            "A pass means the current live sources did not violate the P0 identity/amount gates. "
            "It does not prove configuration equivalence. P1 fingerprinting remains required for "
            "body/package comparability and option-level equivalence."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run APC-30D / FLOW-C P0 golden UAT")
    parser.add_argument("--lookback-days", type=int, default=1095)
    parser.add_argument("--request-budget", type=int, default=24)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_report(
        lookback_days=args.lookback_days,
        request_budget=args.request_budget,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 2 if report["validation_status"] == "safety_violation" else 0


if __name__ == "__main__":
    raise SystemExit(main())
