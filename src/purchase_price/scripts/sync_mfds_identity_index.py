from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import (
    PublicDataClientError,
    PublicDataPortalClient,
    PublicDataTransportError,
    call_with_server_retry,
    is_server_side_error,
)
from purchase_price.config import Settings
from purchase_price.services.mfds_device_intelligence import unwrap_mfds_page
from purchase_price.services.mfds_identity_index import (
    MFDS_PRODUCT_INFO_BASE_URL,
    MFDS_PRODUCT_INFO_OPERATION,
    MFDS_PRODUCT_INFO_RAW_OPERATION,
    create_identity_schema,
    parse_mfds_product_info_record,
    purge_identity_records_not_seen_in_cycle,
    upsert_identity_records,
)
from purchase_price.services.mfds_identity_r2 import (
    MFDS_IDENTITY_POINTER_SCHEMA,
    MFDS_IDENTITY_POINTER_STATE,
)
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_mfds_identity_index import (
    MfdsIdentityIndexRef,
    R2MfdsIdentityIndexStore,
)
from purchase_price.storage.r2_state import R2LockHeldError, R2OperationalStateStore

PIPELINE_STATE = "mfds-identity-pipeline"
PIPELINE_SCHEMA = "mfds-identity-pipeline-v1"
COLLECTION_LOCK_STATE = "mfds-identity-collection-lock"
COLLECTION_LOCK_TTL_SECONDS = 3 * 60 * 60
# A cycle only counts as complete (and may purge rows) once it has seen this share of the
# source totalCount. Small drift is allowed because the source changes while a cycle runs.
CYCLE_COVERAGE_RATIO = 0.99
_SOURCE_NOT_AUTHORIZED_MARKERS = (
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
    "code=30",
    "등록되지 않은 서비스키",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


_QUOTA_EXCEEDED_MARKERS = (
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "code=22",
)


def _is_quota_exceeded(exc: PublicDataClientError) -> bool:
    message = str(exc)
    return any(marker in message for marker in _QUOTA_EXCEEDED_MARKERS)


def _is_source_not_authorized(exc: PublicDataClientError) -> bool:
    message = str(exc)
    return any(marker in message for marker in _SOURCE_NOT_AUTHORIZED_MARKERS)


def _ref_from_pointer(payload: Mapping[str, Any]) -> MfdsIdentityIndexRef:
    if payload.get("schema") != MFDS_IDENTITY_POINTER_SCHEMA:
        raise ValueError("MFDS identity pointer schema mismatch")
    key = str(payload.get("key") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip()
    if not key or len(sha256) != 64:
        raise ValueError("MFDS identity pointer is incomplete")
    return MfdsIdentityIndexRef(
        key=key,
        sha256=sha256,
        stored_bytes=int(payload.get("stored_bytes") or 0),
        uncompressed_bytes=int(payload.get("uncompressed_bytes") or 0),
    )


def _load_pipeline(state_store: R2OperationalStateStore) -> dict[str, Any]:
    payload = state_store.read_json(PIPELINE_STATE)
    if payload is None:
        return {
            "schema": PIPELINE_SCHEMA,
            "next_page": 1,
            "cycle": 1,
            "complete_cycles": 0,
            "verified_complete_cycles": 0,
            "last_total_count": None,
            "cycle_rows_seen": None,
            "rows_per_page": None,
        }
    if payload.get("schema") != PIPELINE_SCHEMA:
        raise ValueError("MFDS identity pipeline schema mismatch")
    next_page = int(payload.get("next_page") or 1)
    if next_page < 1:
        raise ValueError("MFDS identity next_page must be positive")
    return {
        "schema": PIPELINE_SCHEMA,
        "next_page": next_page,
        "cycle": max(int(payload.get("cycle") or 1), 1),
        "complete_cycles": max(int(payload.get("complete_cycles") or 0), 0),
        "verified_complete_cycles": max(int(payload.get("verified_complete_cycles") or 0), 0),
        "last_total_count": payload.get("last_total_count"),
        "cycle_rows_seen": payload.get("cycle_rows_seen"),
        "rows_per_page": payload.get("rows_per_page"),
    }


_ANOMALY_STATUS = {
    "EMPTY_PAGE_BEFORE_SOURCE_END": "SOURCE_EMPTY_PAGE",
    "TRANSPORT_ERROR": "SOURCE_TRANSPORT_ERROR",
    "QUOTA_EXCEEDED": "SOURCE_QUOTA_EXCEEDED",
}


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _covers_source(rows_seen_in_cycle: int, total_count: int | None) -> bool:
    return bool(total_count) and rows_seen_in_cycle >= total_count * CYCLE_COVERAGE_RATIO


def _write_report(output: Path, payload: Mapping[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True))


def _sync_without_lock(
    *,
    max_pages: int,
    rows_per_page: int,
    output: Path,
    settings: Settings | None = None,
) -> int:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    if not 1 <= rows_per_page <= 1000:
        raise ValueError("rows_per_page must be between 1 and 1000")

    settings = settings or Settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if not service_key:
        _write_report(
            output,
            {
                "status": "NOT_CONFIGURED",
                "source": "MFDS medical-device product information",
                "writes_performed": 0,
            },
        )
        return 0
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is required for MFDS identity collection")

    state_store = R2OperationalStateStore.from_settings(settings)
    raw_store = R2RawEvidenceStore.from_settings(settings)
    artifact_store = R2MfdsIdentityIndexStore.from_settings(settings)
    pipeline = _load_pipeline(state_store)
    pointer = state_store.read_json(MFDS_IDENTITY_POINTER_STATE)
    stale_retained_key = (
        str(pointer.get("previous_key") or "").strip()
        if pointer is not None
        else ""
    )

    previous_ref: MfdsIdentityIndexRef | None = None
    with tempfile.TemporaryDirectory(prefix="mfds-identity-") as temp_dir:
        db_path = Path(temp_dir) / "mfds-identity.sqlite"
        if pointer is not None:
            previous_ref = _ref_from_pointer(pointer)
            artifact_store.download_sqlite(previous_ref, db_path)

        connection = sqlite3.connect(db_path)
        create_identity_schema(connection)
        page_no = int(pipeline["next_page"])
        active_cycle = int(pipeline["cycle"])
        stored_cycle_rows_seen = pipeline.get("cycle_rows_seen")
        if stored_cycle_rows_seen in (None, ""):
            cycle_rows_seen = max((page_no - 1) * rows_per_page, 0)
        else:
            cycle_rows_seen = max(int(stored_cycle_rows_seen), 0)
        cycle_completed = False
        cycle_verified = False
        source_anomaly: str | None = None
        purged_stale_rows = 0
        pages_collected = 0
        rows_seen = 0
        upserted = 0
        new_raw_objects = 0
        total_count = _positive_int(pipeline.get("last_total_count"))
        last_raw_key: str | None = None

        try:
            with PublicDataPortalClient(
                service_key,
                timeout_seconds=settings.mfds_request_timeout_seconds,
                max_retries=settings.mfds_max_retries,
            ) as client:
                for _ in range(max_pages):
                    try:
                        payload = call_with_server_retry(
                            lambda: client.get_json(
                                settings.mfds_product_info_base_url or MFDS_PRODUCT_INFO_BASE_URL,
                                MFDS_PRODUCT_INFO_OPERATION,
                                pageNo=page_no,
                                numOfRows=rows_per_page,
                            )
                        )
                    except PublicDataClientError as exc:
                        if pages_collected == 0 and _is_source_not_authorized(exc):
                            connection.close()
                            _write_report(
                                output,
                                {
                                    "status": "SOURCE_NOT_AUTHORIZED",
                                    "source": "MFDS medical-device product information",
                                    "operation": MFDS_PRODUCT_INFO_OPERATION,
                                    "reason": (
                                        "configured service key is not approved for this "
                                        "official product-info operation"
                                    ),
                                    "next_page": page_no,
                                    "writes_performed": 0,
                                },
                            )
                            return 0
                        if pages_collected > 0 and (
                            isinstance(exc, PublicDataTransportError) or is_server_side_error(exc)
                        ):
                            # Publish the pages already collected in this run; the next run
                            # resumes from this page instead of redoing the whole chunk.
                            source_anomaly = "TRANSPORT_ERROR"
                            break
                        if pages_collected > 0 and _is_quota_exceeded(exc):
                            source_anomaly = "QUOTA_EXCEEDED"
                            break
                        raise

                    page = unwrap_mfds_page(payload)
                    # A transient response can report totalCount=0; never let it erase a
                    # known source size.
                    total_count = _positive_int(page.total_count) or total_count
                    raw_ref = raw_store.put_public_json(
                        source_operation=MFDS_PRODUCT_INFO_RAW_OPERATION,
                        payload=payload,
                    )
                    last_raw_key = raw_ref.key
                    new_raw_objects += int(raw_ref.created)
                    records = tuple(
                        parse_mfds_product_info_record(
                            item,
                            source_payload_sha256=raw_ref.payload_hash,
                        )
                        for item in page.items
                    )
                    upserted += upsert_identity_records(
                        connection,
                        records,
                        cycle=active_cycle,
                    )
                    rows_seen += len(records)
                    pages_collected += 1

                    if not page.items:
                        if not _covers_source(cycle_rows_seen + rows_seen, total_count):
                            # An empty page before the known end is a source glitch, not the
                            # end of the cycle. Keep page_no so the next run retries it.
                            source_anomaly = "EMPTY_PAGE_BEFORE_SOURCE_END"
                            break
                        page_no = 1
                        cycle_completed = True
                        break

                    page_no += 1
                    if total_count is not None and (page_no - 1) * rows_per_page >= total_count:
                        page_no = 1
                        cycle_completed = True
                        break

            if cycle_completed:
                cycle_verified = _covers_source(cycle_rows_seen + rows_seen, total_count)
                pipeline["complete_cycles"] = int(pipeline["complete_cycles"]) + 1
                pipeline["cycle"] = active_cycle + 1
                if cycle_verified:
                    pipeline["verified_complete_cycles"] = (
                        int(pipeline.get("verified_complete_cycles") or 0) + 1
                    )

            if cycle_verified:
                purged_stale_rows = purge_identity_records_not_seen_in_cycle(
                    connection,
                    active_cycle,
                )
            connection.commit()
            row_count = int(
                connection.execute("SELECT COUNT(*) FROM mfds_identity").fetchone()[0]
            )
            connection.execute("PRAGMA optimize")
            connection.commit()
        finally:
            try:
                connection.close()
            except Exception:
                pass

        if pages_collected == 0:
            _write_report(
                output,
                {
                    "status": "NO_CHANGE",
                    "next_page": page_no,
                    "row_count": 0 if pointer is None else pointer.get("row_count"),
                    "writes_performed": 0,
                },
            )
            return 0

        ref = artifact_store.put_sqlite(db_path)
        pointer_payload = {
            "schema": MFDS_IDENTITY_POINTER_SCHEMA,
            "key": ref.key,
            "sha256": ref.sha256,
            "stored_bytes": ref.stored_bytes,
            "uncompressed_bytes": ref.uncompressed_bytes,
            "row_count": row_count,
            "updated_at": _now(),
            "source_operation": MFDS_PRODUCT_INFO_OPERATION,
            "last_raw_key": last_raw_key,
            "previous_key": previous_ref.key if previous_ref is not None else None,
        }
        state_store.write_json(MFDS_IDENTITY_POINTER_STATE, pointer_payload)

        pipeline["next_page"] = page_no
        pipeline["last_total_count"] = total_count
        pipeline["rows_per_page"] = rows_per_page
        pipeline["cycle_rows_seen"] = 0 if cycle_completed else cycle_rows_seen + rows_seen
        pipeline["updated_at"] = _now()
        state_store.write_json(PIPELINE_STATE, pipeline)

        # Keep the immediately previous complete index as a grace generation.
        # A reader may have fetched the old pointer just before this publish. Delete only
        # the generation that was already retained by the previous pointer.
        if (
            stale_retained_key
            and stale_retained_key != ref.key
            and (previous_ref is None or stale_retained_key != previous_ref.key)
        ):
            try:
                artifact_store.delete(stale_retained_key)
            except Exception:
                pass

        report = {
            "status": _ANOMALY_STATUS.get(source_anomaly, "SUCCESS"),
            "source_anomaly": source_anomaly,
            "pages_collected": pages_collected,
            "rows_seen": rows_seen,
            "rows_upserted": upserted,
            "row_count": row_count,
            "new_raw_objects": new_raw_objects,
            "next_page": page_no,
            "cycle": pipeline["cycle"],
            "complete_cycles": pipeline["complete_cycles"],
            "verified_complete_cycles": pipeline.get("verified_complete_cycles", 0),
            "cycle_verified": cycle_verified,
            "cycle_rows_seen": pipeline["cycle_rows_seen"],
            "rows_per_page": pipeline["rows_per_page"],
            "cycle_completed": cycle_completed,
            "purged_stale_rows": purged_stale_rows,
            "source_total_count": total_count,
            "index_key": ref.key,
            "index_sha256": ref.sha256,
            "stored_bytes": ref.stored_bytes,
            "writes_performed": pages_collected,
        }
        _write_report(output, report)
        return 0



def sync(
    *,
    max_pages: int,
    rows_per_page: int,
    output: Path,
    settings: Settings | None = None,
) -> int:
    settings = settings or Settings()
    service_key = (settings.resolved_mfds_service_key or "").strip()
    if not service_key or not settings.r2_configured:
        return _sync_without_lock(
            max_pages=max_pages,
            rows_per_page=rows_per_page,
            output=output,
            settings=settings,
        )

    state_store = R2OperationalStateStore.from_settings(settings)
    owner = (
        os.getenv("GITHUB_RUN_ID")
        or os.getenv("HOSTNAME")
        or f"local-{uuid.uuid4().hex}"
    )
    try:
        state_store.acquire_lock(
            COLLECTION_LOCK_STATE,
            owner=owner,
            ttl_seconds=COLLECTION_LOCK_TTL_SECONDS,
        )
    except R2LockHeldError:
        _write_report(
            output,
            {
                "status": "LOCK_HELD",
                "source": "MFDS medical-device product information",
                "writes_performed": 0,
            },
        )
        return 0

    try:
        return _sync_without_lock(
            max_pages=max_pages,
            rows_per_page=rows_per_page,
            output=output,
            settings=settings,
        )
    finally:
        try:
            state_store.release_lock(COLLECTION_LOCK_STATE, owner=owner)
        except Exception:
            # The TTL guarantees eventual recovery. A release transport error must not
            # overwrite the collector's evidence/report result.
            pass

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect MFDS product identity pages and publish a reverse-search SQLite index."
    )
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--rows-per-page", type=int, default=100)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/mfds-identity/sync.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return sync(
        max_pages=args.max_pages,
        rows_per_page=args.rows_per_page,
        output=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
