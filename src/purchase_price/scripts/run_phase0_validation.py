from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from purchase_price.clients.data_go_kr import PublicDataPortalClient, redact_service_key_query
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingCollector,
)
from purchase_price.collectors.g2b_shopping import (
    SOURCE_NAME as G2B_SOURCE_NAME,
)
from purchase_price.config import get_settings
from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_candidate_search import search_mapped_g2b_candidates
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
    resolve_verified_g2b_mapping,
)
from purchase_price.services.match_benchmark import (
    DEFAULT_PRODUCTS_PATH,
    load_phase0_product_queries,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.phase0_validation import (
    Phase0SourceEvaluation,
    build_source_evaluation,
    summarize_phase0_evaluations,
)

PRODUCT_FIELDS = [
    "benchmark_model",
    "product_name",
    "source_name",
    "mapping_status",
    "evaluation_status",
    "source_hit",
    "records_seen",
    "reported_total_count",
    "evidence_count",
    "direct_evidence_count",
    "reference_evidence_count",
    "traceable_evidence_count",
    "condition_complete_count",
    "elapsed_ms",
    "reason",
]


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD") from exc


def _default_dates() -> tuple[date, date]:
    end_date = date.today()
    return end_date - timedelta(days=30), end_date


def _parser() -> argparse.ArgumentParser:
    begin_default, end_default = _default_dates()
    parser = argparse.ArgumentParser(
        description=(
            "Run the Phase 0 benchmark against currently verified public-price source mappings. "
            "Unverified mappings are reported as not evaluated, never as source misses."
        )
    )
    parser.add_argument("--begin-date", type=_date, default=begin_default)
    parser.add_argument("--end-date", type=_date, default=end_default)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/phase0-validation"))
    parser.add_argument("--num-of-rows", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not call external APIs; emit mapping/readiness coverage only.",
    )
    return parser


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_product_rows(rows: tuple[Phase0SourceEvaluation, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRODUCT_FIELDS)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            writer.writerow({key: _csv_value(payload[key]) for key in PRODUCT_FIELDS})


def _write_summary(
    rows: tuple[Phase0SourceEvaluation, ...],
    *,
    benchmark_products: int,
    path: Path,
    begin_date: date,
    end_date: date,
    offline: bool,
) -> None:
    summary = summarize_phase0_evaluations(rows, benchmark_products=benchmark_products)
    payload = {
        "schema_version": "phase0-validation-v1",
        "query_window": {
            "begin_date": begin_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "offline": offline,
        "summary": asdict(summary),
        "metric_definitions": {
            "mapping_readiness_rate": (
                "benchmark products with an explicitly verified source mapping / all benchmark products"
            ),
            "evaluation_coverage_rate": (
                "benchmark products with at least one successful source evaluation / all benchmark products"
            ),
            "source_hit_rate": (
                "successful source-product evaluations whose public source reported or returned at least one "
                "record / successful source-product evaluations"
            ),
            "direct_evidence_product_rate": (
                "successfully evaluated products with >=1 A/B observation whose EvidenceType is a direct "
                "unit/public-sale price / successfully evaluated products"
            ),
            "multi_source_product_rate": (
                "successfully evaluated products with usable A/B/C/D evidence from >=2 independent sources / "
                "successfully evaluated products; null until >=2 source adapters are successfully evaluated"
            ),
            "traceability_rate": (
                "observations carrying source name + source record id + source URL or original title / all "
                "observations"
            ),
            "condition_completeness_rate": (
                "direct evidence with quantity + unit + transaction date + VAT status + conditions / all "
                "direct evidence; this is conservative v0 until install/shipping/options/warranty are split"
            ),
            "collector_error_rate": (
                "source-product evaluations that raised a collector error / attempted source-product evaluations"
            ),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_ratio(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _mapping_status_for_query(
    query: ProductQuery,
    mappings: tuple[G2BProductMapping, ...],
) -> str:
    if resolve_verified_g2b_mapping(query, mappings) is not None:
        return "verified"
    model_key = normalize_text(query.model_name)
    if model_key and any(normalize_text(row.model_name) == model_key for row in mappings):
        return "unverified"
    return "missing"


def _source_hit(*, reported_total_count: int | None, records_seen: int) -> bool:
    if reported_total_count is not None:
        return reported_total_count > 0
    return records_seen > 0


def _retained_evidence_reason(candidate_prices: tuple) -> str | None:
    if not candidate_prices:
        return "source searched successfully but no model/manufacturer candidate evidence was retained"
    if not any(price.match_grade in {MatchGrade.A, MatchGrade.B, MatchGrade.C, MatchGrade.D} for price in candidate_prices):
        return "candidate rows were retained but all failed usable identity grading and remained X"
    return None


def _safe_error_detail(exc: Exception) -> str:
    detail = redact_service_key_query(str(exc)).strip()
    return detail[:500] if detail else "collection failed"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.begin_date > args.end_date:
        raise SystemExit("--begin-date must not be after --end-date")
    if args.num_of_rows < 1 or args.max_pages < 1:
        raise SystemExit("--num-of-rows and --max-pages must be positive")

    queries = load_phase0_product_queries(args.products)
    mappings = load_g2b_product_mappings()

    collector: G2BShoppingCollector | None = None
    if not args.offline:
        settings = get_settings()
        if not settings.data_go_kr_service_key:
            raise SystemExit(
                "DATA_GO_KR_SERVICE_KEY is not configured; use --offline for readiness-only output"
            )
        client = PublicDataPortalClient(
            settings.data_go_kr_service_key,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
        )
        collector = G2BShoppingCollector(
            settings.data_go_kr_service_key,
            base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            client=client,
        )

    rows: list[Phase0SourceEvaluation] = []
    for query in queries.values():
        mapping = resolve_verified_g2b_mapping(query, mappings)
        mapping_status = _mapping_status_for_query(query, mappings)

        if mapping is None:
            rows.append(
                build_source_evaluation(
                    benchmark_model=query.model_name,
                    product_name=query.product_name,
                    source_name=G2B_SOURCE_NAME,
                    mapping_status=mapping_status,
                    evaluation_status="mapping_unverified",
                    reason="verified G2B detail-product mapping required before live evaluation",
                )
            )
            continue

        if args.offline:
            rows.append(
                build_source_evaluation(
                    benchmark_model=query.model_name,
                    product_name=query.product_name,
                    source_name=G2B_SOURCE_NAME,
                    mapping_status=mapping_status,
                    evaluation_status="not_run_offline",
                    reason="verified mapping exists; external API call skipped by --offline",
                )
            )
            continue

        started = time.monotonic()
        try:
            assert collector is not None
            result = search_mapped_g2b_candidates(
                collector,
                query,
                begin_date=args.begin_date,
                end_date=args.end_date,
                mappings=mappings,
                num_of_rows=args.num_of_rows,
                max_pages=args.max_pages,
            )
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            rows.append(
                build_source_evaluation(
                    benchmark_model=query.model_name,
                    product_name=query.product_name,
                    source_name=G2B_SOURCE_NAME,
                    mapping_status=mapping_status,
                    evaluation_status="error",
                    elapsed_ms=elapsed_ms,
                    reason=f"{type(exc).__name__}: {_safe_error_detail(exc)}",
                )
            )
            continue

        elapsed_ms = round((time.monotonic() - started) * 1000)
        rows.append(
            build_source_evaluation(
                benchmark_model=query.model_name,
                product_name=query.product_name,
                source_name=G2B_SOURCE_NAME,
                mapping_status=mapping_status,
                evaluation_status="success",
                observations=result.candidate_prices,
                source_hit=_source_hit(
                    reported_total_count=result.reported_total_count,
                    records_seen=result.records_seen,
                ),
                records_seen=result.records_seen,
                reported_total_count=result.reported_total_count,
                elapsed_ms=elapsed_ms,
                reason=_retained_evidence_reason(result.candidate_prices),
            )
        )

    row_tuple = tuple(rows)
    products_path = args.output_dir / "phase0-products.csv"
    summary_path = args.output_dir / "phase0-summary.json"
    _write_product_rows(row_tuple, products_path)
    _write_summary(
        row_tuple,
        benchmark_products=len(queries),
        path=summary_path,
        begin_date=args.begin_date,
        end_date=args.end_date,
        offline=args.offline,
    )

    summary = summarize_phase0_evaluations(row_tuple, benchmark_products=len(queries))
    print(f"benchmark_products={summary.benchmark_products}")
    print(
        "mapping_readiness="
        f"{summary.mapping_ready_products}/{summary.benchmark_products} "
        f"({_fmt_ratio(summary.mapping_readiness_rate)})"
    )
    print(
        "evaluation_coverage="
        f"{summary.successfully_evaluated_products}/{summary.benchmark_products} "
        f"({_fmt_ratio(summary.evaluation_coverage_rate)})"
    )
    print(
        f"source_hit_rate={summary.source_hit_pairs}/{summary.successful_source_product_pairs} "
        f"({_fmt_ratio(summary.source_hit_rate)})"
    )
    print(
        f"direct_evidence_product_rate={summary.direct_evidence_products}/"
        f"{summary.successfully_evaluated_products} "
        f"({_fmt_ratio(summary.direct_evidence_product_rate)})"
    )
    print(f"multi_source_product_rate={_fmt_ratio(summary.multi_source_product_rate)}")
    print(f"traceability_rate={_fmt_ratio(summary.traceability_rate)}")
    print(f"condition_completeness_rate={_fmt_ratio(summary.condition_completeness_rate)}")
    print(f"collector_error_rate={_fmt_ratio(summary.collector_error_rate)}")
    print(f"not_evaluated_products={summary.not_evaluated_products}")
    print(f"products_output={products_path}")
    print(f"summary_output={summary_path}")

    return 1 if summary.error_pairs else 0


if __name__ == "__main__":
    sys.exit(main())
