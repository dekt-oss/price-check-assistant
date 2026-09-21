from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, exists, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from purchase_price.config import Settings
from purchase_price.models import TrackBDeliveryLine
from purchase_price.services.g2b_product_mapping import (
    G2BProductMapping,
    load_g2b_product_mappings,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import canonical_manufacturer
from purchase_price.services.track_b_r2_quote_index import _local_index_path

REPORT_SCHEMA = "r2-search-recall-report-v1"
OUTPUT_SCHEMA = "r2-broad-reference-composition-v1"


def _mapping_for_model(
    model_name: str,
    mappings: tuple[G2BProductMapping, ...],
) -> G2BProductMapping | None:
    key = normalize_text(model_name)
    matches = [
        row
        for row in mappings
        if row.verified and row.detail_product_code and normalize_text(row.model_name) == key
    ]
    return matches[0] if len(matches) == 1 else None


def _current_clause():
    newer = aliased(TrackBDeliveryLine)
    return ~exists(
        select(1).where(
            newer.delivery_request_number == TrackBDeliveryLine.delivery_request_number,
            newer.product_sequence == TrackBDeliveryLine.product_sequence,
            newer.change_order_number > TrackBDeliveryLine.change_order_number,
        )
    )


def summarize_rows(
    rows: list[Any],
    *,
    query_model: str,
    query_manufacturer: str,
    topn: int = 8,
) -> dict[str, Any]:
    model_key = normalize_text(query_model)
    query_maker = canonical_manufacturer(query_manufacturer) if query_manufacturer else None

    exact_model = 0
    manufacturer_match = 0
    prices: list[float] = []
    model_counts: Counter[str] = Counter()
    maker_counts: Counter[str] = Counter()

    for row in rows:
        row_model = str(getattr(row, "model_name", None) or "").strip()
        row_maker = str(getattr(row, "manufacturer", None) or "").strip()
        if row_model:
            model_counts[row_model] += 1
        if row_maker:
            maker_counts[row_maker] += 1
        if model_key and normalize_text(row_model) == model_key:
            exact_model += 1
        if query_maker and row_maker and canonical_manufacturer(row_maker) == query_maker:
            manufacturer_match += 1
        price = getattr(row, "unit_price", None)
        if price is not None and float(price) > 0:
            prices.append(float(price))

    return {
        "row_count": len(rows),
        "exact_model_rows": exact_model,
        "manufacturer_match_rows": manufacturer_match,
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "top_models": model_counts.most_common(topn),
        "top_manufacturers": maker_counts.most_common(topn),
    }


def build_report(
    recall_report: dict[str, Any],
    *,
    mappings: tuple[G2BProductMapping, ...],
    session: Session,
) -> dict[str, Any]:
    current = _current_clause()
    cases: list[dict[str, Any]] = []

    for case in recall_report.get("cases", []):
        if case.get("tier") != "BROAD_REFERENCE":
            continue
        query = case.get("query") or {}
        model_name = str(query.get("model_name") or "").strip()
        manufacturer = str(query.get("manufacturer") or "").strip()
        mapping = _mapping_for_model(model_name, mappings)
        if mapping is None or not mapping.detail_product_code:
            cases.append(
                {
                    "case_id": case.get("case_id"),
                    "model_name": model_name,
                    "mapping_status": "missing_or_unverified",
                }
            )
            continue

        rows = session.scalars(
            select(TrackBDeliveryLine)
            .where(
                current,
                TrackBDeliveryLine.detail_code == mapping.detail_product_code,
                TrackBDeliveryLine.identity_conflict.is_(False),
            )
            .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        ).all()
        summary = summarize_rows(
            list(rows),
            query_model=model_name,
            query_manufacturer=manufacturer,
        )
        cases.append(
            {
                "case_id": case.get("case_id"),
                "model_name": model_name,
                "manufacturer": manufacturer,
                "mapping_status": "verified",
                "detail_product_code": mapping.detail_product_code,
                "detail_product_name": mapping.detail_product_name,
                **summary,
            }
        )

    return {
        "schema": OUTPUT_SCHEMA,
        "status": "SUCCESS",
        "case_count": len(cases),
        "cases": cases,
    }


def _write_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# R2 Broad Reference Composition",
        "",
        f"- broad-reference cases audited: **{report['case_count']}**",
        "",
        "| Case | Detail code | Rows | Exact model | Manufacturer match | Price range |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in report["cases"]:
        if row.get("mapping_status") != "verified":
            lines.append(
                f"| {row.get('case_id')} | - | - | - | - | mapping missing/unverified |"
            )
            continue
        price_range = "-"
        if row.get("price_min") is not None:
            price_range = f"{row['price_min']:.0f} ~ {row['price_max']:.0f}"
        lines.append(
            "| {case_id} | {code} | {rows} | {exact} | {maker} | {price} |".format(
                case_id=row["case_id"],
                code=row["detail_product_code"],
                rows=row["row_count"],
                exact=row["exact_model_rows"],
                maker=row["manufacturer_match_rows"],
                price=price_range,
            )
        )
        models = ", ".join(f"{name}({count})" for name, count in row["top_models"]) or "-"
        makers = ", ".join(
            f"{name}({count})" for name, count in row["top_manufacturers"]
        ) or "-"
        lines.append(f"  - top models: {models}")
        lines.append(f"  - top manufacturers: {makers}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit verified G2B class composition behind broad R2 references"
    )
    parser.add_argument(
        "--recall-report",
        type=Path,
        default=Path("artifacts/r2-search-recall/report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/r2-search-recall/broad-reference-composition.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/r2-search-recall/broad-reference-composition.md"),
    )
    args = parser.parse_args()

    payload = json.loads(args.recall_report.read_text(encoding="utf-8"))
    if payload.get("schema") != REPORT_SCHEMA:
        raise ValueError("R2 recall report schema mismatch")

    settings = Settings()
    index_path = _local_index_path(settings)
    if index_path is None:
        raise RuntimeError("Track B serving index is unavailable")

    engine = create_engine(
        f"sqlite+pysqlite:///{index_path}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as session:
            report = build_report(
                payload,
                mappings=load_g2b_product_mappings(),
                session=session,
            )
    finally:
        engine.dispose()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_summary(report, args.summary)
    print(json.dumps({"case_count": report["case_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
