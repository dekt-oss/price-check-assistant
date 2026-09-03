from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, G2BShoppingCollector
from purchase_price.config import get_settings
from purchase_price.services.g2b_product_mapping import load_g2b_product_mappings
from purchase_price.services.g2b_scan import G2BExactModelScanResult, scan_exact_model_candidates
from purchase_price.services.match_benchmark import (
    DEFAULT_PRODUCTS_PATH,
    load_phase0_product_queries,
)
from purchase_price.services.matching import normalize_text

SUMMARY_FIELDS = [
    "benchmark_model",
    "detail_product_name",
    "chunk_begin_date",
    "chunk_end_date",
    "status",
    "pages_fetched",
    "records_seen",
    "reported_total_count",
    "candidate_count",
    "grade_counts",
    "error",
]

CANDIDATE_FIELDS = [
    "benchmark_model",
    "candidate_title",
    "predicted_grade",
    "match_note",
    "transaction_count",
    "first_transaction_date",
    "last_transaction_date",
    "min_price",
    "max_price",
    "evidence_types",
    "source_record_ids",
    "query_begin_date",
    "query_end_date",
]


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan verified G2B classifications for exact benchmark model tokens in bounded "
            "date windows. Every window is paginated to completion or reported as incomplete; "
            "no window is silently truncated. The service key is never written to the output."
        )
    )
    parser.add_argument("--begin-date", required=True, type=_date)
    parser.add_argument("--end-date", required=True, type=_date)
    parser.add_argument("--summary-output", required=True, type=Path)
    parser.add_argument("--candidates-output", required=True, type=Path)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--chunk-days", type=int, default=31)
    parser.add_argument("--max-pages-per-chunk", type=int, default=20)
    parser.add_argument("--num-of-rows", type=int, default=100)
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Restrict to these benchmark models (repeatable). Default: all verified mappings.",
    )
    return parser


def write_scan_outputs(
    results: list[G2BExactModelScanResult],
    *,
    summary_path: Path,
    candidates_path: Path,
    begin_date: date,
    end_date: date,
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)

    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for result in results:
            for chunk in result.chunks:
                writer.writerow(
                    {
                        "benchmark_model": chunk.benchmark_model,
                        "detail_product_name": chunk.detail_product_name,
                        "chunk_begin_date": chunk.begin_date.isoformat(),
                        "chunk_end_date": chunk.end_date.isoformat(),
                        "status": chunk.status,
                        "pages_fetched": chunk.pages_fetched,
                        "records_seen": chunk.records_seen,
                        "reported_total_count": (
                            "" if chunk.reported_total_count is None else chunk.reported_total_count
                        ),
                        "candidate_count": chunk.candidate_count,
                        "grade_counts": " ".join(
                            f"{grade}={count}" for grade, count in chunk.grade_counts.items()
                        ),
                        "error": chunk.error or "",
                    }
                )

    with candidates_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        for result in results:
            for candidate in result.candidates:
                writer.writerow(
                    {
                        "benchmark_model": candidate.benchmark_model,
                        "candidate_title": candidate.candidate_title,
                        "predicted_grade": candidate.predicted_grade,
                        "match_note": candidate.match_note,
                        "transaction_count": candidate.transaction_count,
                        "first_transaction_date": (
                            candidate.first_transaction_date.isoformat()
                            if candidate.first_transaction_date
                            else ""
                        ),
                        "last_transaction_date": (
                            candidate.last_transaction_date.isoformat()
                            if candidate.last_transaction_date
                            else ""
                        ),
                        "min_price": str(candidate.min_price),
                        "max_price": str(candidate.max_price),
                        "evidence_types": " ".join(candidate.evidence_types),
                        "source_record_ids": " ".join(candidate.source_record_ids),
                        "query_begin_date": begin_date.isoformat(),
                        "query_end_date": end_date.isoformat(),
                    }
                )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.chunk_days < 1 or args.max_pages_per_chunk < 1 or args.num_of_rows < 1:
        raise SystemExit("--chunk-days, --max-pages-per-chunk and --num-of-rows must be positive")
    if args.begin_date > args.end_date:
        raise SystemExit("--begin-date must not be after --end-date")

    settings = get_settings()
    if not settings.data_go_kr_service_key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY is not configured")

    queries = load_phase0_product_queries(args.products)
    mappings = load_g2b_product_mappings()
    verified = [mapping for mapping in mappings if mapping.verified]
    if args.model:
        wanted = {normalize_text(model) for model in args.model}
        verified = [m for m in verified if normalize_text(m.model_name) in wanted]
        if not verified:
            raise SystemExit("none of the requested models has a verified G2B mapping")

    collector = G2BShoppingCollector(
        settings.data_go_kr_service_key,
        base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
    )

    results: list[G2BExactModelScanResult] = []
    for mapping in verified:
        query = queries.get(normalize_text(mapping.model_name))
        if query is None:
            raise SystemExit(
                f"verified G2B mapping is missing from Phase 0 registry: {mapping.model_name!r}"
            )
        result = scan_exact_model_candidates(
            collector,
            query,
            begin_date=args.begin_date,
            end_date=args.end_date,
            mappings=mappings,
            chunk_days=args.chunk_days,
            num_of_rows=args.num_of_rows,
            max_pages_per_chunk=args.max_pages_per_chunk,
        )
        results.append(result)
        for chunk in result.chunks:
            grades = " ".join(f"{g}={c}" for g, c in chunk.grade_counts.items()) or "-"
            print(
                f"model={chunk.benchmark_model} window={chunk.begin_date}..{chunk.end_date} "
                f"status={chunk.status} pages={chunk.pages_fetched} records={chunk.records_seen} "
                f"total={chunk.reported_total_count} candidates={chunk.candidate_count} "
                f"grades={grades}"
                + (f" error={chunk.error}" if chunk.error else "")
            )
        print(
            f"model={mapping.model_name} windows={len(result.chunks)} "
            f"complete={result.complete} records={result.records_seen} "
            f"candidate_identities={len(result.candidates)} "
            f"candidate_transactions={result.transaction_count}"
        )

    write_scan_outputs(
        results,
        summary_path=args.summary_output,
        candidates_path=args.candidates_output,
        begin_date=args.begin_date,
        end_date=args.end_date,
    )
    print(f"summary={args.summary_output} candidates={args.candidates_output}")

    if not all(result.complete for result in results):
        print("scan_status=incomplete (at least one window was not fully paginated)")
        return 1
    print("scan_status=complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
