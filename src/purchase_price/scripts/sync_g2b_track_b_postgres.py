from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from purchase_price.config import Settings
from purchase_price.db import SessionLocal
from purchase_price.scripts.import_g2b_track_b_r2_to_db import (
    TRACK_B_PAGE_OPERATION,
    run,
)
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.services.track_b_db_quote_comparison import ingest_track_b_page
from purchase_price.services.track_b_pipeline_state import STATE_NAME, TrackBPipelineState
from purchase_price.storage.r2_reader import R2RawEvidenceReader, R2RawObject
from purchase_price.storage.r2_state import R2OperationalStateStore


def _merge_totals(total: dict[str, int], report: Mapping[str, Any]) -> None:
    for field in ("objects_scanned", "inserted", "replayed", "invalid_rows", "conflicts"):
        total[field] += int(report.get(field) or 0)


def _raw_object_for_key(reader: R2RawEvidenceReader, key: str) -> R2RawObject:
    prefix = f"{reader.raw_prefix}/{TRACK_B_PAGE_OPERATION}/"
    if not key.startswith(prefix) or not key.endswith(".json.gz"):
        raise ValueError(f"pending Track B key is outside the expected operation prefix: {key}")
    digest = key.rsplit("/", 1)[-1][: -len(".json.gz")]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"pending Track B key lacks a valid SHA-256 digest: {key}")
    return R2RawObject(
        bucket=reader.bucket,
        key=key,
        payload_hash=digest,
        stored_bytes=0,
        last_modified=None,
    )


def _sync_exact_keys(
    *,
    reader: R2RawEvidenceReader,
    object_keys: list[str],
) -> dict[str, Any]:
    inserted = replayed = invalid_rows = conflicts = scanned = 0
    for key in dict.fromkeys(object_keys):
        obj = _raw_object_for_key(reader, key)
        payload = reader.get_public_json(obj)
        if not isinstance(payload, Mapping):
            raise ValueError(f"Track B R2 page must be a JSON object: {key}")
        with SessionLocal() as session, session.begin():
            result = ingest_track_b_page(
                session,
                TrackBRawPage(
                    payload=payload,
                    raw_object_key=obj.key,
                    raw_payload_sha256=obj.payload_hash,
                ),
            )
        inserted += result.inserted
        replayed += result.replayed
        invalid_rows += result.invalid_rows
        conflicts += result.conflicts
        scanned += 1
    return {
        "status": "PARTIAL" if invalid_rows or conflicts else "SUCCESS",
        "objects_scanned": scanned,
        "inserted": inserted,
        "replayed": replayed,
        "invalid_rows": invalid_rows,
        "conflicts": conflicts,
    }


def sync(*, max_bootstrap_objects: int, output: Path) -> int:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL secret is required for production PostgreSQL sync")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL")

    settings = Settings()
    state_store = R2OperationalStateStore.from_settings(settings)
    payload = state_store.read_json(STATE_NAME)
    if payload is None:
        raise RuntimeError("Track B pipeline state is missing; run collection bootstrap first")
    state = TrackBPipelineState.from_payload(payload)
    reader = R2RawEvidenceReader.from_settings(settings)

    total = {
        "objects_scanned": 0,
        "inserted": 0,
        "replayed": 0,
        "invalid_rows": 0,
        "conflicts": 0,
    }
    mode = "pending-manifest"

    if not state.db_bootstrap_complete:
        mode = "full-bootstrap"
        cursor = state.db_bootstrap_cursor
        while total["objects_scanned"] < max_bootstrap_objects:
            remaining = max_bootstrap_objects - total["objects_scanned"]
            report = run(
                reader=reader,
                session_factory=SessionLocal,
                limit=min(1000, remaining),
                cursor=cursor,
            )
            _merge_totals(total, report)
            cursor = report.get("resume_cursor") or cursor
            state.mark_db_bootstrap_progress(cursor=cursor, complete=not bool(report.get("has_more")))
            state_store.write_json(STATE_NAME, state.to_payload())
            if not report.get("has_more"):
                break
            if int(report.get("objects_scanned") or 0) == 0:
                raise RuntimeError("Track B PostgreSQL bootstrap cursor did not advance")
        if not state.db_bootstrap_complete:
            raise RuntimeError(
                f"Track B PostgreSQL bootstrap exceeded {max_bootstrap_objects} R2 objects"
            )
    else:
        pending = list(state.pending_object_keys)
        if pending:
            report = _sync_exact_keys(reader=reader, object_keys=pending)
            _merge_totals(total, report)
            state.mark_pending_synced(pending, report)
            state_store.write_json(STATE_NAME, state.to_payload())

    final = {
        "status": "PARTIAL" if total["invalid_rows"] or total["conflicts"] else "SUCCESS",
        "mode": mode,
        **total,
        "db_bootstrap_complete": state.db_bootstrap_complete,
        "remaining_pending_objects": len(state.pending_object_keys),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Track B R2 evidence into production PostgreSQL")
    parser.add_argument("--max-bootstrap-objects", type=int, default=100000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-daily/postgres-sync.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_bootstrap_objects < 1:
        raise ValueError("max-bootstrap-objects must be positive")
    return sync(max_bootstrap_objects=args.max_bootstrap_objects, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
