from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingCollector,
    G2BShoppingOperation,
    parse_official_report_record,
)
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import load_g2b_product_mappings
from purchase_price.services.g2b_shopping_collection import iter_specific_item_pages
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import grade_product_identity, parse_g2b_identity

DEFAULT_PRODUCTS_PATH = Path(__file__).resolve().parents[3] / "data" / "phase0_products.csv"


class CandidateCaptureError(RuntimeError):
    pass


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD") from exc


def _load_queries(path: Path) -> dict[str, ProductQuery]:
    if not path.exists():
        raise CandidateCaptureError(f"Phase 0 product registry not found: {path}")

    queries: dict[str, ProductQuery] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"manufacturer", "product_name", "model_name", "specification"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise CandidateCaptureError("Phase 0 product registry is missing required columns")

        for row in reader:
            model = (row.get("model_name") or "").strip()
            key = normalize_text(model)
            if not key:
                continue
            queries[key] = ProductQuery(
                product_name=(row.get("product_name") or "").strip(),
                manufacturer=(row.get("manufacturer") or "").strip(),
                model_name=model,
                specification=(row.get("specification") or "").strip(),
            )
    return queries


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
            "Capture public G2B class records for human-reviewed F3 ground truth. "
            "The service key is never written to the output."
        )
    )
    parser.add_argument("--begin-date", required=True, type=_date)
    parser.add_argument("--end-date", required=True, type=_date)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--max-rows-per-model", type=int, default=25)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.max_rows_per_model < 1:
        raise SystemExit("--max-rows-per-model must be positive")

    settings = get_settings()
    if not settings.data_go_kr_service_key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY is not configured")

    queries = _load_queries(args.products)
    mappings = load_g2b_product_mappings()
    verified = tuple(mapping for mapping in mappings if mapping.verified)
    collector = G2BShoppingCollector(
        settings.data_go_kr_service_key,
        base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
    )

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

        for collected in iter_specific_item_pages(
            collector,
            detail_product_name=mapping.detail_product_name,
            begin_date=args.begin_date,
            end_date=args.end_date,
            num_of_rows=100,
            max_pages=20,
        ):
            pages_fetched += 1
            records_seen += len(collected.page.items)
            reported_total_count = collected.page.total_count

            for record in collected.page.items:
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

        deduped: dict[tuple[str, str], tuple[int, str, dict[str, str]]] = {}
        for item in model_rows:
            row = item[2]
            key = (row["source_record_id"], row["candidate_title"])
            deduped.setdefault(key, item)

        ranked = sorted(
            deduped.values(),
            key=lambda item: (item[0], item[1], item[2]["source_record_id"]),
            reverse=False,
        )
        selected = ranked[: args.max_rows_per_model]
        rows.extend(item[2] for item in selected)

        print(
            f"model={mapping.model_name} pages={pages_fetched} records={records_seen} "
            f"reported_total={reported_total_count} parsed={len(model_rows)} "
            f"captured={len(selected)}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
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
        "query_begin_date",
        "query_end_date",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"captured_rows={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
