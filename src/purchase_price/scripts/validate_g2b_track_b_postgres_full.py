"""Validate full Track B R2 import and lookup against an isolated PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal
from statistics import quantiles
from urllib.parse import urlparse

from sqlalchemy import func, select

from purchase_price.config import Settings
from purchase_price.db import SessionLocal
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.scripts.import_g2b_track_b_r2_to_db import run as import_track_b
from purchase_price.scripts.validate_g2b_track_b_db_live import _find_comparison_case
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote
from purchase_price.storage.r2_reader import R2RawEvidenceReader


def require_postgres(database_url: str) -> None:
    if not urlparse(database_url).scheme.startswith("postgresql"):
        raise ValueError("full import validation requires an isolated PostgreSQL database")


def require_complete_import(report: dict[str, object]) -> None:
    if report.get("has_more") is not False:
        raise RuntimeError("object limit reached before the current R2 collection was exhausted")


def run(*, limit: int) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be positive")
    settings = Settings()
    require_postgres(settings.database_url)
    reader = R2RawEvidenceReader.from_settings(settings)

    started = time.monotonic()
    imported = import_track_b(
        reader=reader,
        session_factory=SessionLocal,
        limit=limit,
    )
    require_complete_import(imported)
    import_seconds = round(time.monotonic() - started, 3)

    with SessionLocal() as session:
        total_rows = session.scalar(select(func.count()).select_from(TrackBDeliveryLine)) or 0
        priced_rows = session.scalar(
            select(func.count())
            .select_from(TrackBDeliveryLine)
            .where(TrackBDeliveryLine.unit_price > 0)
        ) or 0
        modeled_rows = session.scalar(
            select(func.count())
            .select_from(TrackBDeliveryLine)
            .where(TrackBDeliveryLine.model_key.is_not(None))
        ) or 0
        sample, quote_price, first_match = _find_comparison_case(session)
        assert sample.model_name is not None
        query = ProductQuery(
            product_name=sample.product_class or "",
            manufacturer=sample.manufacturer or "",
            model_name=sample.model_name,
            specification=sample.specification or "",
        )
        lookup_times_ms: list[float] = []
        for _ in range(20):
            lookup_started = time.perf_counter()
            comparison = compare_track_b_quote(
                session,
                query,
                quote_unit_price=quote_price,
            )
            lookup_times_ms.append((time.perf_counter() - lookup_started) * 1000)
            if not comparison.candidates:
                raise RuntimeError("PostgreSQL lookup lost the validated candidate")

    replay = import_track_b(
        reader=reader,
        session_factory=SessionLocal,
        limit=min(10, limit),
    )
    if replay["inserted"] != 0 or replay["replayed"] < 1:
        raise RuntimeError("PostgreSQL replay was not idempotent")
    if imported["invalid_rows"]:
        raise RuntimeError("full PostgreSQL import contained invalid rows")

    p95_lookup_ms = quantiles(lookup_times_ms, n=20, method="inclusive")[18]
    return {
        "status": "SUCCESS",
        "objects_scanned": imported["objects_scanned"],
        "rows_inserted": imported["inserted"],
        "rows_stored": total_rows,
        "positive_unit_price_rows": priced_rows,
        "modeled_rows": modeled_rows,
        "invalid_rows": imported["invalid_rows"],
        "has_more": imported["has_more"],
        "import_seconds": import_seconds,
        "rows_per_second": round(total_rows / import_seconds, 2) if import_seconds else None,
        "lookup_p95_ms": round(p95_lookup_ms, 3),
        "lookup_match_grade": first_match.candidates[0].match_grade.value,
        "lookup_delta_percent": str(
            first_match.candidates[0].delta_percent or Decimal("0")
        ),
        "replay_objects": replay["objects_scanned"],
        "replayed_rows": replay["replayed"],
        "public_api_requests": 0,
        "r2_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()
    print(json.dumps(run(limit=args.limit), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
