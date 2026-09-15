"""Run a bounded R2 -> SQLite -> quote comparison using real Track B objects."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from purchase_price.config import Settings
from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.scripts.import_g2b_track_b_r2_to_db import run as import_track_b
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote
from purchase_price.storage.r2_reader import R2RawEvidenceReader


def run(*, limit: int) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be positive")
    with tempfile.TemporaryDirectory(prefix="track-b-db-live-") as directory:
        database_path = Path(directory) / "validation.sqlite"
        engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine)
        reader = R2RawEvidenceReader.from_settings(Settings())
        started = time.monotonic()
        imported = import_track_b(
            reader=reader, session_factory=factory, limit=limit
        )
        elapsed = round(time.monotonic() - started, 3)
        with Session(engine) as session:
            total_rows = session.scalar(
                select(func.count()).select_from(TrackBDeliveryLine)
            ) or 0
            priced_rows = session.scalar(
                select(func.count()).select_from(TrackBDeliveryLine).where(
                    TrackBDeliveryLine.unit_price > 0
                )
            ) or 0
            modeled_rows = session.scalar(
                select(func.count()).select_from(TrackBDeliveryLine).where(
                    TrackBDeliveryLine.model_key.is_not(None)
                )
            ) or 0
            sample = session.scalar(
                select(TrackBDeliveryLine).where(
                    TrackBDeliveryLine.unit_price > 0,
                    TrackBDeliveryLine.model_key.is_not(None),
                    TrackBDeliveryLine.product_class.is_not(None),
                ).order_by(TrackBDeliveryLine.transaction_date.desc())
            )
            if sample is None or sample.unit_price is None or sample.model_name is None:
                raise RuntimeError("bounded real sample contained no searchable priced model")
            query = ProductQuery(
                product_name=sample.product_class or "",
                manufacturer=sample.manufacturer or "",
                model_name=sample.model_name,
                specification=sample.specification or "",
            )
            quote_price = (sample.unit_price * Decimal("1.10")).quantize(Decimal("0.01"))
            matched = compare_track_b_quote(
                session, query, quote_unit_price=quote_price
            )
            near_miss = compare_track_b_quote(
                session,
                ProductQuery(
                    product_name=query.product_name,
                    manufacturer=query.manufacturer,
                    model_name=f"{query.model_name}-NONEXISTENT",
                    specification=query.specification,
                ),
                quote_unit_price=quote_price,
            )
        engine.dispose()
    if not matched.candidates:
        raise RuntimeError("real DB row could not be found through quote comparison")
    if near_miss.candidates:
        raise RuntimeError("near-miss model unexpectedly returned a price candidate")
    return {
        "status": "SUCCESS",
        "objects_scanned": imported["objects_scanned"],
        "normalized_rows_inserted": total_rows,
        "positive_unit_price_rows": priced_rows,
        "modeled_rows": modeled_rows,
        "invalid_rows": imported["invalid_rows"],
        "elapsed_seconds": elapsed,
        "sample_match_grade": matched.candidates[0].match_grade.value,
        "sample_delta_percent": str(matched.candidates[0].delta_percent),
        "near_miss_status": near_miss.status,
        "public_api_requests": 0,
        "r2_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    report = run(limit=args.limit)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
