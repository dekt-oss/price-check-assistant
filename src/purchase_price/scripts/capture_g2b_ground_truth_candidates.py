from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, G2BShoppingCollector
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_candidate_search import search_mapped_g2b_candidates
from purchase_price.services.g2b_product_mapping import load_g2b_product_mappings
from purchase_price.services.matching import normalize_text

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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture public G2B candidate rows for human-reviewed F3 ground truth. "
            "The service key is never written to the output."
        )
    )
    parser.add_argument("--begin-date", required=True, type=_date)
    parser.add_argument("--end-date", required=True, type=_date)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    return parser


def main() -> None:
    args = _parser().parse_args()
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

        result = search_mapped_g2b_candidates(
            collector,
            query,
            begin_date=args.begin_date,
            end_date=args.end_date,
            mappings=mappings,
        )
        for candidate in result.candidate_prices:
            rows.append(
                {
                    "benchmark_model": mapping.model_name,
                    "source_name": candidate.source_name,
                    "source_record_id": candidate.source_record_id or "",
                    "candidate_title": candidate.original_title or candidate.product_name,
                    "predicted_grade": candidate.match_grade.value,
                    "match_note": candidate.match_note or "",
                    "price": str(candidate.price),
                    "transaction_date": (
                        candidate.transaction_date.isoformat()
                        if candidate.transaction_date is not None
                        else ""
                    ),
                    "quantity": str(candidate.quantity) if candidate.quantity is not None else "",
                    "unit": candidate.unit or "",
                    "total_amount": (
                        str(candidate.total_amount) if candidate.total_amount is not None else ""
                    ),
                    "evidence_type": candidate.evidence_type.value,
                    "query_begin_date": args.begin_date.isoformat(),
                    "query_end_date": args.end_date.isoformat(),
                }
            )

        print(
            f"model={mapping.model_name} pages={result.pages_fetched} "
            f"records={result.records_seen} candidates={len(result.candidate_prices)}"
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
