from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

from purchase_price.collectors.g2b_shopping import (
    G2BShoppingOperation,
    parse_official_report_record,
)
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import load_g2b_product_mappings
from purchase_price.services.g2b_runtime import build_configured_g2b_collector
from purchase_price.services.match_benchmark import (
    DEFAULT_PRODUCTS_PATH,
    MatchBenchmarkError,
    load_phase0_product_queries,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import grade_product_identity, parse_g2b_identity

CAPTURE_FIELDS = [
    "benchmark_model",
    "source_name",
    "source_record_id",
    "candidate_title",
    "predicted_grade",
    "match_note",
    "price",
    "transaction_date",
    "quantity",
    "unit",
    "total_amount",
    "evidence_type",
    "transaction_count",
    "query_begin_date",
    "query_end_date",
]


class CandidateCaptureError(RuntimeError):
    pass


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD") from exc


def _load_queries(path: Path) -> dict[str, ProductQuery]:
    try:
        return load_phase0_product_queries(path)
    except MatchBenchmarkError as exc:
        raise CandidateCaptureError(str(exc)) from exc


def select_identity_sample(
    ranked_rows: list[tuple[int, str, dict[str, str]]],
    *,
    max_rows: int,
) -> list[dict[str, str]]:
    """Keep one representative transaction per distinct candidate title.

    Repeated deliveries of the same G2B identity would otherwise fill the human-review sample
    with the same product. The kept row is the best-ranked (priority, date, record id) one and
    carries `transaction_count` so reviewers can see how often the identity recurred.
    """

    grouped: dict[str, list[tuple[int, str, dict[str, str]]]] = {}
    for item in ranked_rows:
        key = normalize_text(item[2]["candidate_title"])
        if not key:
            continue
        grouped.setdefault(key, []).append(item)

    representatives: list[tuple[int, str, dict[str, str]]] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: (item[0], item[1], item[2]["source_record_id"]))
        priority, transaction_date, row = ordered[0]
        representatives.append(
            (priority, transaction_date, {**row, "transaction_count": str(len(ordered))})
        )

    representatives.sort(key=lambda item: (item[0], item[1], item[2]["source_record_id"]))
    return [item[2] for item in representatives[:max_rows]]


def _priority(query: ProductQuery, title: str) -> int:
    normalized_title = normalize_text(title)
    model = normalize_text(query.model_name)
    manufacturer = normalize_text(query.manufacturer)
    if model and model in normalized_title:
        return 0
    if manufacturer and manufacturer in normalized_title:
        return 1
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a bounded public G2B sample for human-reviewed F3 ground truth. "
            "This is a sampling workflow, not a completeness scan, and the service key is "
            "never written to the output."
        )
    )
    parser.add_argument("--begin-date", required=True, type=_date)
    parser.add_argument("--end-date", required=True, type=_date)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--sample-pages-per-model", type=int, default=1)
    parser.add_argument("--max-rows-per-model", type=int, default=25)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.sample_pages_per_model < 1:
        raise SystemExit("--sample-pages-per-model must be positive")
    if args.max_rows_per_model < 1:
        raise SystemExit("--max-rows-per-model must be positive")

    settings = get_settings()
    if not settings.data_go_kr_service_key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY is not configured")

    queries = _load_queries(args.products)
    mappings = load_g2b_product_mappings()
    verified = tuple(mapping for mapping in mappings if mapping.verified)
    collector = build_configured_g2b_collector(settings)

    rows: list[dict[str, str]] = []
    for mapping in verified:
        query = queries.get(normalize_text(mapping.model_name))
        if query is None:
            raise CandidateCaptureError(
                f"verified G2B mapping is missing from Phase 0 registry: {mapping.model_name!r}"
            )
        if not mapping.detail_product_name:
            raise CandidateCaptureError(
                f"verified G2B mapping has no detail product name: {mapping.model_name!r}"
            )

        model_rows: list[tuple[int, str, dict[str, str]]] = []
        records_seen = 0
        pages_fetched = 0
        reported_total_count: int | None = None

        for page_no in range(1, args.sample_pages_per_model + 1):
            page, _payload = collector.fetch_specific_item_page(
                detail_product_name=mapping.detail_product_name,
                begin_date=args.begin_date,
                end_date=args.end_date,
                page_no=page_no,
                num_of_rows=100,
            )
            pages_fetched += 1
            records_seen += len(page.items)
            reported_total_count = page.total_count

            for record in page.items:
                parsed = parse_official_report_record(
                    record,
                    operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
                )
                if parsed is None:
                    continue

                title = parsed.original_title or parsed.product_name
                identity = parse_g2b_identity(title)
                decision = grade_product_identity(query, identity)
                transaction_date = (
                    parsed.transaction_date.isoformat()
                    if parsed.transaction_date is not None
                    else ""
                )
                row = {
                    "benchmark_model": mapping.model_name,
                    "source_name": parsed.source_name,
                    "source_record_id": parsed.source_record_id or "",
                    "candidate_title": title,
                    "predicted_grade": decision.grade.value,
                    "match_note": decision.note,
                    "price": str(parsed.price),
                    "transaction_date": transaction_date,
                    "quantity": str(parsed.quantity) if parsed.quantity is not None else "",
                    "unit": parsed.unit or "",
                    "total_amount": (
                        str(parsed.total_amount) if parsed.total_amount is not None else ""
                    ),
                    "evidence_type": parsed.evidence_type.value,
                    "query_begin_date": args.begin_date.isoformat(),
                    "query_end_date": args.end_date.isoformat(),
                }
                model_rows.append((_priority(query, title), transaction_date, row))

            if page.total_count is not None and page_no * 100 >= page.total_count:
                break
            if page.total_count is None and len(page.items) < 100:
                break

        selected = select_identity_sample(model_rows, max_rows=args.max_rows_per_model)
        rows.extend(selected)

        print(
            f"model={mapping.model_name} sampled_pages={pages_fetched} "
            f"sampled_records={records_seen} reported_total={reported_total_count} "
            f"parsed={len(model_rows)} identities={len(selected)}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CAPTURE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"captured_rows={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
