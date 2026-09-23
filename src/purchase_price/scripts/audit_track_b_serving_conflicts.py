from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from purchase_price.config import Settings
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.sync_g2b_track_b_r2_index import _ref_from_pointer
from purchase_price.services.track_b_pipeline_state import SERVING_INDEX_STATE_NAME
from purchase_price.storage.r2_serving_index import R2ServingIndexStore
from purchase_price.storage.r2_state import R2OperationalStateStore


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _source_record_id(row: TrackBDeliveryLine) -> str:
    return (
        f"delivery:{row.delivery_request_number}"
        f"|change:{row.change_order}|line:{row.product_sequence}"
    )


def audit_conflict_rows(session: Session, *, sample_limit: int = 30) -> dict[str, Any]:
    if sample_limit < 1:
        raise ValueError("sample_limit must be positive")

    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(TrackBDeliveryLine.identity_conflict.is_(True))
        .order_by(
            TrackBDeliveryLine.identity_conflict_count.desc(),
            TrackBDeliveryLine.transaction_date.desc(),
            TrackBDeliveryLine.id.desc(),
        )
    ).all()

    event_count = sum(int(row.identity_conflict_count or 0) for row in rows)
    detail_codes = Counter((row.detail_code or "미확인") for row in rows)
    suppliers = Counter((row.supplier or "미확인") for row in rows)
    demand_institutions = Counter((row.demand_institution or "미확인") for row in rows)
    transaction_months = Counter(
        row.transaction_date.strftime("%Y-%m") if row.transaction_date is not None else "미확인"
        for row in rows
    )
    priced_rows = [row for row in rows if row.unit_price is not None and row.unit_price > 0]

    samples = [
        {
            "source_record_id": _source_record_id(row),
            "conflict_count": int(row.identity_conflict_count or 0),
            "detail_code": row.detail_code,
            "product_id": row.product_id,
            "product_title": row.product_title,
            "unit_price": _money(row.unit_price),
            "quantity": _money(row.quantity),
            "unit": row.unit,
            "total_amount": _money(row.total_amount),
            "supplier": row.supplier,
            "demand_institution": row.demand_institution,
            "transaction_date": (
                row.transaction_date.isoformat() if row.transaction_date is not None else None
            ),
            "contract_delivery_type": row.contract_delivery_type,
            "contract_type": row.contract_type,
            "delivery_condition": row.delivery_condition,
            "first_raw_object_key": row.raw_object_key,
        }
        for row in rows[:sample_limit]
    ]

    return {
        "status": "CONFLICTS_PRESENT" if rows else "CLEAN",
        "conflict_row_count": len(rows),
        "conflict_event_count": event_count,
        "max_conflicts_for_one_identity": max(
            (int(row.identity_conflict_count or 0) for row in rows),
            default=0,
        ),
        "priced_conflict_row_count": len(priced_rows),
        "top_detail_codes": detail_codes.most_common(20),
        "top_suppliers": suppliers.most_common(20),
        "top_demand_institutions": demand_institutions.most_common(20),
        "transaction_months": sorted(transaction_months.items()),
        "samples": samples,
        "interpretation": (
            "Rows marked identity_conflict are fail-closed and excluded from Track B "
            "direct/reference price lookup. This audit describes the quarantined current-index "
            "rows only; identifying which source fields changed requires a raw-variant audit."
        ),
    }


def build_live_report(*, sample_limit: int = 30) -> dict[str, Any]:
    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is required for serving conflict audit")

    state_store = R2OperationalStateStore.from_settings(settings)
    pointer = state_store.read_json(SERVING_INDEX_STATE_NAME)
    if pointer is None:
        raise RuntimeError("Track B serving-index pointer is missing")

    ref = _ref_from_pointer(pointer)
    with tempfile.TemporaryDirectory(prefix="track-b-conflict-audit-") as temp_dir:
        db_path = Path(temp_dir) / "track-b-serving.sqlite"
        R2ServingIndexStore.from_settings(settings).download_sqlite(ref, db_path)
        engine = create_engine(f"sqlite+pysqlite:///{db_path}")
        try:
            with Session(engine) as session:
                report = audit_conflict_rows(session, sample_limit=sample_limit)
        finally:
            engine.dispose()

    report.update(
        {
            "serving_index_key": ref.key,
            "serving_index_sha256": ref.sha256,
            "serving_schema": pointer.get("serving_schema"),
            "row_count": pointer.get("row_count"),
            "sync_mode": pointer.get("mode"),
            "writes_performed": 0,
            "public_api_requests": 0,
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit of quarantined Track B serving-index identity conflicts."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-limit", type=int, default=30)
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Exit 3 when any quarantined conflict row is present.",
    )
    args = parser.parse_args()

    report = build_live_report(sample_limit=args.sample_limit)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 3 if args.require_clean and report["conflict_row_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
