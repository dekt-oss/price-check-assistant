"""Collect the full MFDS model-info (형명) dataset and publish an item-status SQLite index.

Read path is the same as the identity index: R2 pointer -> gzip SQLite -> local cache. Each run
resumes from the persisted page cursor, fetches 500-row pages with a few concurrent workers,
stores every raw page as public evidence, folds rows into one status row per item number and
publishes a new index generation.

Cycle safety mirrors the identity collector (#250/#252): an empty page only ends a cycle once
the cycle has covered >=99% of the known totalCount, transport/quota failures after some pages
keep the progress and stop, and stale rows are purged only after a coverage-verified cycle.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataTransportError
from purchase_price.config import Settings
from purchase_price.services.mfds_api_keys import build_mfds_json_client, is_key_not_registered
from purchase_price.services.mfds_device_intelligence import (
    MFDS_MODEL_INFO_BASE_URL,
    MFDS_MODEL_INFO_OPERATION,
    MODEL_INFO_PAGE_SIZE,
    parse_model_record,
    unwrap_mfds_page,
)
from purchase_price.services.mfds_item_status_index import (
    MFDS_ITEM_STATUS_PREFIX,
    MFDS_ITEM_STATUS_SCHEMA,
    create_item_status_schema,
    purge_items_not_seen_in_cycle,
    upsert_item_status,
)
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_mfds_identity_index import (
    MfdsIdentityIndexRef,
    R2MfdsIdentityIndexStore,
)
from purchase_price.storage.r2_state import R2OperationalStateStore

PIPELINE_STATE = "mfds-item-status-pipeline"
PIPELINE_SCHEMA = "mfds-item-status-pipeline-v1"
POINTER_STATE = "mfds-item-status-index-pointer"
POINTER_SCHEMA = "mfds-item-status-index-pointer-v1"
RAW_OPERATION = "mfds-model-info-page"
CYCLE_COVERAGE_RATIO = 0.99
DEFAULT_WORKERS = 4
_QUOTA_MARKERS = ("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", "code=22")
_ANOMALY_STATUS = {
    "EMPTY_PAGE_BEFORE_SOURCE_END": "SOURCE_EMPTY_PAGE",
    "TRANSPORT_ERROR": "SOURCE_TRANSPORT_ERROR",
    "QUOTA_EXCEEDED": "SOURCE_QUOTA_EXCEEDED",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _covers_source(rows_seen_in_cycle: int, total_count: int | None) -> bool:
    return bool(total_count) and rows_seen_in_cycle >= total_count * CYCLE_COVERAGE_RATIO


def load_pipeline(state_store: Any) -> dict[str, Any]:
    payload = state_store.read_json(PIPELINE_STATE)
    if payload is None:
        return {
            "schema": PIPELINE_SCHEMA,
            "next_page": 1,
            "cycle": 1,
            "complete_cycles": 0,
            "verified_complete_cycles": 0,
            "last_total_count": None,
            "cycle_rows_seen": 0,
            "rows_per_page": MODEL_INFO_PAGE_SIZE,
        }
    if payload.get("schema") != PIPELINE_SCHEMA:
        raise ValueError("MFDS item-status pipeline schema mismatch")
    return dict(payload)


def _ref_from_pointer(payload: Mapping[str, Any]) -> MfdsIdentityIndexRef:
    if payload.get("schema") != POINTER_SCHEMA:
        raise ValueError("MFDS item-status pointer schema mismatch")
    return MfdsIdentityIndexRef(
        key=str(payload["key"]),
        sha256=str(payload["sha256"]),
        stored_bytes=int(payload.get("stored_bytes") or 0),
        uncompressed_bytes=int(payload.get("uncompressed_bytes") or 0),
    )


def sync(
    *,
    max_pages: int,
    output: Path,
    settings: Settings | None = None,
    workers: int = DEFAULT_WORKERS,
    rows_per_page: int = MODEL_INFO_PAGE_SIZE,
    client: Any = None,
    state_store: Any = None,
    raw_store: Any = None,
    artifact_store: Any = None,
) -> dict[str, Any]:
    if max_pages < 1 or workers < 1:
        raise ValueError("max_pages and workers must be positive")
    settings = settings or Settings()
    client = client or build_mfds_json_client(settings, timeout_seconds=90.0, max_retries=2)
    if client is None:
        report = {"status": "NOT_CONFIGURED", "writes_performed": 0}
        _write(output, report)
        return report
    state_store = state_store or R2OperationalStateStore.from_settings(settings)
    raw_store = raw_store or R2RawEvidenceStore.from_settings(settings)
    artifact_store = artifact_store or R2MfdsIdentityIndexStore.from_settings(
        settings, prefix=MFDS_ITEM_STATUS_PREFIX, schema=MFDS_ITEM_STATUS_SCHEMA
    )
    base_url = settings.mfds_model_info_base_url or MFDS_MODEL_INFO_BASE_URL

    pipeline = load_pipeline(state_store)
    pointer = state_store.read_json(POINTER_STATE)
    previous_ref = _ref_from_pointer(pointer) if pointer else None
    page_no = int(pipeline.get("next_page") or 1)
    active_cycle = int(pipeline.get("cycle") or 1)
    cycle_rows_seen = int(pipeline.get("cycle_rows_seen") or 0)
    total_count = _positive_int(pipeline.get("last_total_count"))

    def fetch(page: int) -> tuple[int, dict[str, Any]]:
        return page, client.get_json(
            base_url, MFDS_MODEL_INFO_OPERATION, pageNo=page, numOfRows=rows_per_page
        )

    with tempfile.TemporaryDirectory(prefix="mfds-item-status-") as temp_dir:
        db_path = Path(temp_dir) / "mfds-item-status.sqlite"
        if previous_ref is not None:
            artifact_store.download_sqlite(previous_ref, db_path)
        connection = sqlite3.connect(db_path)
        create_item_status_schema(connection)

        pages_collected = rows_seen = upserted = 0
        source_anomaly: str | None = None
        cycle_completed = cycle_verified = False
        purged = 0
        last_page = page_no + max_pages - 1
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                while page_no <= last_page and not cycle_completed and source_anomaly is None:
                    batch = list(range(page_no, min(last_page, page_no + workers - 1) + 1))
                    if total_count:
                        final_page = -(-total_count // rows_per_page)
                        batch = [page for page in batch if page <= final_page] or batch[:1]
                    futures = [pool.submit(fetch, page) for page in batch]
                    for future in futures:
                        try:
                            page, payload = future.result()
                        except PublicDataClientError as exc:
                            if pages_collected and isinstance(exc, PublicDataTransportError):
                                source_anomaly = "TRANSPORT_ERROR"
                            elif pages_collected and any(m in str(exc) for m in _QUOTA_MARKERS):
                                source_anomaly = "QUOTA_EXCEEDED"
                            elif not pages_collected and is_key_not_registered(exc):
                                connection.close()
                                report = {"status": "SOURCE_NOT_AUTHORIZED", "writes_performed": 0}
                                _write(output, report)
                                return report
                            else:
                                raise
                            break
                        parsed = unwrap_mfds_page(payload)
                        total_count = _positive_int(parsed.total_count) or total_count
                        raw_store.put_public_json(source_operation=RAW_OPERATION, payload=payload)
                        records = [parse_model_record(item) for item in parsed.items]
                        upserted += upsert_item_status(connection, records, cycle=active_cycle)
                        rows_seen += len(records)
                        pages_collected += 1
                        if not parsed.items:
                            if _covers_source(cycle_rows_seen + rows_seen, total_count):
                                cycle_completed = True
                            else:
                                source_anomaly = "EMPTY_PAGE_BEFORE_SOURCE_END"
                            break
                        page_no = page + 1
                        if total_count and (page_no - 1) * rows_per_page >= total_count:
                            cycle_completed = True
                            break

            if cycle_completed:
                cycle_verified = _covers_source(cycle_rows_seen + rows_seen, total_count)
                pipeline["complete_cycles"] = int(pipeline.get("complete_cycles") or 0) + 1
                pipeline["cycle"] = active_cycle + 1
                if cycle_verified:
                    pipeline["verified_complete_cycles"] = (
                        int(pipeline.get("verified_complete_cycles") or 0) + 1
                    )
                    purged = purge_items_not_seen_in_cycle(connection, active_cycle)
                page_no = 1
            connection.commit()
            item_count = int(connection.execute("SELECT COUNT(*) FROM mfds_item_status").fetchone()[0])
            active_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM mfds_item_status WHERE domestic_active = 1"
                ).fetchone()[0]
            )
        finally:
            connection.close()

        if pages_collected == 0:
            report = {"status": "NO_CHANGE", "next_page": page_no, "writes_performed": 0}
            _write(output, report)
            return report

        ref = artifact_store.put_sqlite(db_path)
        state_store.write_json(
            POINTER_STATE,
            {
                "schema": POINTER_SCHEMA,
                "key": ref.key,
                "sha256": ref.sha256,
                "stored_bytes": ref.stored_bytes,
                "uncompressed_bytes": ref.uncompressed_bytes,
                "item_count": item_count,
                "domestic_active_count": active_count,
                "updated_at": _now(),
                "previous_key": previous_ref.key if previous_ref else None,
            },
        )
        pipeline.update(
            {
                "next_page": page_no,
                "last_total_count": total_count,
                "rows_per_page": rows_per_page,
                "cycle_rows_seen": 0 if cycle_completed else cycle_rows_seen + rows_seen,
                "updated_at": _now(),
            }
        )
        state_store.write_json(PIPELINE_STATE, pipeline)

    report = {
        "status": _ANOMALY_STATUS.get(source_anomaly or "", "SUCCESS"),
        "source_anomaly": source_anomaly,
        "pages_collected": pages_collected,
        "rows_seen": rows_seen,
        "rows_upserted": upserted,
        "item_count": item_count,
        "domestic_active_count": active_count,
        "next_page": page_no,
        "cycle": pipeline["cycle"],
        "complete_cycles": pipeline.get("complete_cycles", 0),
        "verified_complete_cycles": pipeline.get("verified_complete_cycles", 0),
        "cycle_completed": cycle_completed,
        "cycle_verified": cycle_verified,
        "cycle_rows_seen": pipeline["cycle_rows_seen"],
        "purged_stale_items": purged,
        "source_total_count": total_count,
        "index_key": ref.key,
        "stored_bytes": ref.stored_bytes,
        "writes_performed": pages_collected,
    }
    _write(output, report)
    return report


def plan(
    *,
    event_name: str,
    identity_verified_cycles: int,
    item_status_verified_cycles: int,
    weekday: int,
    force: bool = False,
) -> dict[str, Any]:
    """Run after the identity backfill is verified (user decision 2026-10-05), then weekly."""

    if event_name == "workflow_dispatch" and force:
        return {"run": True, "reason": "manual dispatch with force"}
    if identity_verified_cycles < 1:
        return {"run": False, "reason": "waiting for the MFDS identity backfill to verify coverage"}
    if item_status_verified_cycles < 1:
        return {"run": True, "reason": "first full 형명 cycle in progress"}
    if event_name == "schedule" and weekday != 6:
        return {"run": False, "reason": "after the first verified cycle, refresh weekly (Sunday)"}
    return {"run": True, "reason": "weekly refresh"}


def _write(output: Path, payload: Mapping[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("sync")
    run.add_argument("--max-pages", type=int, default=600)
    run.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    run.add_argument("--output", type=Path, required=True)
    planner = sub.add_parser("plan")
    planner.add_argument("--event-name", required=True)
    planner.add_argument("--force", action="store_true")
    planner.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "sync":
        sync(max_pages=args.max_pages, workers=args.workers, output=args.output)
        return 0

    from purchase_price.services.mfds_identity_status import get_mfds_identity_collection_status

    settings = Settings()
    identity = get_mfds_identity_collection_status(settings=settings)
    state = R2OperationalStateStore.from_settings(settings).read_json(PIPELINE_STATE) or {}
    decision = plan(
        event_name=args.event_name,
        identity_verified_cycles=int(getattr(identity, "verified_complete_cycles", 0) or 0),
        item_status_verified_cycles=int(state.get("verified_complete_cycles") or 0),
        weekday=datetime.now(UTC).weekday(),
        force=args.force,
    )
    _write(args.output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
