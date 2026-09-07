from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
)
from purchase_price.services.g2b_research_terms import research_terms_for_query
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
    discover_unmapped_g2b_candidates,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.research_basis import resolve_research_basis

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_PATH = PROJECT_ROOT / "data" / "research_quality_uat_cases.csv"


def _price_range(candidates: list[G2BDiscoveryCandidate]) -> dict[str, str | int | None]:
    values = [candidate.price for candidate in candidates if candidate.price > 0]
    if not values:
        return {"count": 0, "low": None, "high": None}
    return {
        "count": len(values),
        "low": str(min(values)),
        "high": str(max(values)),
    }


def _candidate_row(candidate: G2BDiscoveryCandidate) -> dict[str, Any]:
    return {
        "title": candidate.title,
        "classification_name": candidate.classification_name,
        "classification_code": candidate.classification_code,
        "price": str(candidate.price),
        "transaction_date": (
            candidate.transaction_date.isoformat() if candidate.transaction_date else None
        ),
        "search_term": candidate.search_term,
        "relevance": candidate.relevance,
        "score": candidate.score,
        "match_reason": candidate.match_reason,
        "source_record_id": candidate.source_record_id,
    }


def _mapping_index() -> dict[str, G2BProductMapping]:
    return {
        normalize_text(mapping.model_name): mapping
        for mapping in load_g2b_product_mappings()
        if mapping.model_name
    }


def _load_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError("research quality UAT case registry is empty")
    return rows


def _curated_terms(query: ProductQuery, mapping: G2BProductMapping | None) -> tuple[str, ...]:
    terms = list(research_terms_for_query(query))
    if mapping and mapping.verified and mapping.detail_product_name:
        terms.append(mapping.detail_product_name)
    output: list[str] = []
    seen: set[str] = set()
    for term in terms:
        term = " ".join(term.split()).strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            output.append(term)
    return tuple(output)


def _run_case(
    row: dict[str, str],
    *,
    mapping_by_model: dict[str, G2BProductMapping],
    service_key: str,
    base_url: str,
    lookback_days: int,
    request_budget: int,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, Any]:
    query = ProductQuery(
        product_name=(row.get("product_name") or "").strip(),
        manufacturer=(row.get("manufacturer") or "").strip(),
        model_name=(row.get("model_name") or "").strip(),
        specification=(row.get("specification") or "").strip(),
    )
    mapping = mapping_by_model.get(normalize_text(query.model_name))
    basis = resolve_research_basis(query)
    curated = _curated_terms(query, mapping)

    discovery = discover_unmapped_g2b_candidates(
        query,
        service_key=service_key,
        lookback_days=lookback_days,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        pages_per_term_window=1,
        request_budget=request_budget,
        today=date.today(),
        curated_terms=curated,
    )

    price_candidates = [candidate for candidate in discovery.candidates if candidate.price > 0]
    model_candidates = [
        candidate for candidate in price_candidates if candidate.relevance == "모델 표기 후보"
    ]

    verified_classification_candidates: list[G2BDiscoveryCandidate] = []
    if basis.is_verified_official and basis.code:
        verified_classification_candidates = [
            candidate
            for candidate in price_candidates
            if candidate.classification_code == basis.code
            and candidate.relevance != "모델 표기 후보"
        ]

    unverified_related = [
        candidate
        for candidate in price_candidates
        if candidate not in model_candidates
        and candidate not in verified_classification_candidates
    ]

    if model_candidates:
        usefulness = "same_model_price_candidate"
        useful = True
    elif verified_classification_candidates:
        usefulness = "verified_category_alternative_price"
        useful = True
    else:
        usefulness = "research_only_no_qualified_price"
        useful = False

    return {
        "case_id": (row.get("case_id") or "").strip(),
        "case_role": (row.get("case_role") or "").strip(),
        "manufacturer": query.manufacturer,
        "product_name": query.product_name,
        "model_name": query.model_name,
        "specification": query.specification,
        "mapping_status": mapping.mapping_status if mapping else "not_registered",
        "basis_status": basis.status.value,
        "basis_name": basis.name,
        "basis_code": basis.code,
        "basis_rationale": basis.rationale,
        "query_terms": list(discovery.terms),
        "discovery_status": discovery.status,
        "request_count": discovery.request_count,
        "request_budget": discovery.request_budget,
        "records_seen": discovery.records_seen,
        "failed_query_count": discovery.failed_query_count,
        "truncated_query_count": discovery.truncated_query_count,
        "same_model_prices": _price_range(model_candidates),
        "verified_category_alternative_prices": _price_range(
            verified_classification_candidates
        ),
        "unverified_related_price_candidates": _price_range(unverified_related),
        "provisional_decision_useful_price": useful,
        "usefulness_reason": usefulness,
        "top_candidates": [_candidate_row(candidate) for candidate in price_candidates[:10]],
        "safety_contract": {
            "research_candidates_are_collected_prices": False,
            "unverified_related_in_aggregate_price_band": False,
            "verified_category_alternative_is_same_model_price": False,
        },
    }


def build_report(
    *,
    cases_path: Path,
    lookback_days: int,
    request_budget: int,
    timeout_seconds: float,
    max_retries: int,
) -> dict[str, Any]:
    settings = get_settings()
    service_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not service_key:
        return {
            "validation_status": "not_configured",
            "key_source": settings.g2b_shopping_key_source,
            "cases": [],
        }

    mapping_by_model = _mapping_index()
    cases = []
    for row in _load_cases(cases_path):
        cases.append(
            _run_case(
                row,
                mapping_by_model=mapping_by_model,
                service_key=service_key,
                base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
                lookback_days=lookback_days,
                request_budget=request_budget,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )

    useful_count = sum(bool(case["provisional_decision_useful_price"]) for case in cases)
    failure_count = sum(case["discovery_status"] == "failure" for case in cases)
    return {
        "validation_status": "pass" if failure_count == 0 else "partial_or_failure",
        "key_source": settings.g2b_shopping_key_source,
        "lookback_days": lookback_days,
        "case_count": len(cases),
        "provisional_useful_price_count": useful_count,
        "target_useful_price_count": 3,
        "target_met": useful_count >= 3,
        "failure_count": failure_count,
        "cases": cases,
        "acceptance_note": (
            "target_met is a provisional evidence-availability metric. Human UAT must still verify "
            "that the returned product/category relationship is decision-useful; raw API counts "
            "alone are never a pass."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the five-case G2B research-quality UAT")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--request-budget", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_report(
        cases_path=args.cases,
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
    return 0 if report.get("validation_status") != "not_configured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
