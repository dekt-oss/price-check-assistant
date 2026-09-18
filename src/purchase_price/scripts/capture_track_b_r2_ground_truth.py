from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, exists, or_, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from purchase_price.config import Settings
from purchase_price.models import TrackBDeliveryLine
from purchase_price.services.match_benchmark import (
    DEFAULT_GROUND_TRUTH_PATH,
    DEFAULT_PRODUCTS_PATH,
    load_phase0_product_queries,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_r2_quote_index import _local_index_path

SOURCE_NAME = "조달청_나라장터쇼핑몰 Track B R2 serving index"

OUTPUT_FIELDS = (
    "benchmark_model",
    "benchmark_manufacturer",
    "benchmark_product_name",
    "source_name",
    "source_record_id",
    "candidate_title",
    "candidate_match_basis",
    "parsed_manufacturer",
    "parsed_model_name",
    "parsed_product_class",
    "detail_code",
    "transaction_date",
    "raw_object_key",
    "expected_grade",
    "review_note",
)

SUMMARY_SCHEMA = "track-b-r2-ground-truth-capture-v1"


def _source_record_id(row: TrackBDeliveryLine) -> str:
    return (
        f"delivery:{row.delivery_request_number}"
        f"|change:{row.change_order}|line:{row.product_sequence}"
    )


def _load_existing_pairs(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            (
                str(row.get("benchmark_model") or "").strip(),
                str(row.get("source_record_id") or "").strip(),
            )
            for row in reader
            if str(row.get("benchmark_model") or "").strip()
            and str(row.get("source_record_id") or "").strip()
        }


def _candidate_basis(row: TrackBDeliveryLine, model_key: str, model_name: str) -> str:
    if row.model_key == model_key:
        return "parsed_model_exact"
    title = str(row.product_title or "")
    if model_name.casefold() in title.casefold():
        return "title_model_literal"
    return "model_reference"


def capture_candidates(
    session: Session,
    *,
    products_path: Path = DEFAULT_PRODUCTS_PATH,
    ground_truth_path: Path = DEFAULT_GROUND_TRUTH_PATH,
    max_per_model: int = 10,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if max_per_model < 1 or max_per_model > 100:
        raise ValueError("max_per_model must be between 1 and 100")

    queries = load_phase0_product_queries(products_path)
    existing = _load_existing_pairs(ground_truth_path)
    newer = aliased(TrackBDeliveryLine)
    current = ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )

    output: list[dict[str, str]] = []
    per_model: dict[str, dict[str, Any]] = {}
    existing_excluded = 0

    for query in queries.values():
        model_name = query.model_name.strip()
        model_key = normalize_text(model_name)
        if not model_name or not model_key:
            per_model[model_name or "(blank)"] = {
                "candidate_count": 0,
                "status": "no_model",
                "bases": {},
            }
            continue

        conditions = [TrackBDeliveryLine.model_key == model_key]
        conditions.append(TrackBDeliveryLine.product_title.icontains(model_name, autoescape=True))

        rows = session.scalars(
            select(TrackBDeliveryLine)
            .where(
                current,
                or_(*conditions),
                TrackBDeliveryLine.identity_conflict.is_(False),
                TrackBDeliveryLine.product_title.is_not(None),
            )
            .order_by(
                TrackBDeliveryLine.transaction_date.desc(),
                TrackBDeliveryLine.id.desc(),
            )
            .limit(max_per_model * 40)
        ).all()

        selected = 0
        seen_identity: set[tuple[str, str, str]] = set()
        bases: dict[str, int] = {}

        for row in rows:
            record_id = _source_record_id(row)
            if (model_name, record_id) in existing:
                existing_excluded += 1
                continue

            identity_key = (
                str(row.product_title or "").strip().casefold(),
                str(row.manufacturer or "").strip().casefold(),
                str(row.model_name or "").strip().casefold(),
            )
            if identity_key in seen_identity:
                continue
            seen_identity.add(identity_key)

            basis = _candidate_basis(row, model_key, model_name)
            bases[basis] = bases.get(basis, 0) + 1
            output.append(
                {
                    "benchmark_model": model_name,
                    "benchmark_manufacturer": query.manufacturer,
                    "benchmark_product_name": query.product_name,
                    "source_name": SOURCE_NAME,
                    "source_record_id": record_id,
                    "candidate_title": str(row.product_title or "").strip(),
                    "candidate_match_basis": basis,
                    "parsed_manufacturer": str(row.manufacturer or "").strip(),
                    "parsed_model_name": str(row.model_name or "").strip(),
                    "parsed_product_class": str(row.product_class or "").strip(),
                    "detail_code": str(row.detail_code or "").strip(),
                    "transaction_date": (
                        row.transaction_date.isoformat()
                        if row.transaction_date is not None
                        else ""
                    ),
                    "raw_object_key": str(row.raw_object_key or "").strip(),
                    "expected_grade": "",
                    "review_note": "",
                }
            )
            selected += 1
            if selected >= max_per_model:
                break

        per_model[model_name] = {
            "candidate_count": selected,
            "status": "candidates" if selected else "zero",
            "bases": bases,
        }

    models_with_candidates = sum(
        1 for item in per_model.values() if int(item.get("candidate_count") or 0) > 0
    )
    summary = {
        "schema": SUMMARY_SCHEMA,
        "model_count": len(queries),
        "models_with_candidates": models_with_candidates,
        "models_without_candidates": [
            model
            for model, item in per_model.items()
            if int(item.get("candidate_count") or 0) == 0
        ],
        "candidate_row_count": len(output),
        "existing_ground_truth_pairs_excluded": existing_excluded,
        "max_per_model": max_per_model,
        "per_model": per_model,
        "safety_contract": {
            "g2b_live_api_requests": 0,
            "predicted_grade_written": False,
            "human_expected_grade_required": True,
            "identity_conflicts_excluded": True,
            "superseded_change_orders_excluded": True,
        },
    }
    return output, summary


def write_capture(
    *,
    rows: Iterable[dict[str, str]],
    summary: dict[str, Any],
    csv_path: Path,
    summary_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_with_sqlite(
    sqlite_path: Path,
    *,
    products_path: Path,
    ground_truth_path: Path,
    max_per_model: int,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    engine = create_engine(f"sqlite+pysqlite:///{sqlite_path}")
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with session_factory() as session:
            return capture_candidates(
                session,
                products_path=products_path,
                ground_truth_path=ground_truth_path,
                max_per_model=max_per_model,
            )
    finally:
        engine.dispose()


def capture_from_current_r2(
    *,
    products_path: Path,
    ground_truth_path: Path,
    max_per_model: int,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 repository secret set is incomplete")
    path = _local_index_path(settings)
    if path is None:
        raise RuntimeError("Track B serving-index pointer is missing")
    return _run_with_sqlite(
        path,
        products_path=products_path,
        ground_truth_path=ground_truth_path,
        max_per_model=max_per_model,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture human-review Ground Truth candidates from the existing Track B R2 serving "
            "index without calling the live G2B API."
        )
    )
    parser.add_argument("--sqlite-path", type=Path)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--max-per-model", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-ground-truth/candidates.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("artifacts/r2-ground-truth/summary.json"),
    )
    args = parser.parse_args()

    if args.sqlite_path is not None:
        rows, summary = _run_with_sqlite(
            args.sqlite_path,
            products_path=args.products,
            ground_truth_path=args.ground_truth,
            max_per_model=args.max_per_model,
        )
    else:
        rows, summary = capture_from_current_r2(
            products_path=args.products,
            ground_truth_path=args.ground_truth,
            max_per_model=args.max_per_model,
        )

    write_capture(
        rows=rows,
        summary=summary,
        csv_path=args.output,
        summary_path=args.summary_output,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
