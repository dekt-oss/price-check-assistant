from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
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
from purchase_price.storage.r2_state import R2OperationalStateStore

PIPELINE_STATE = "mfds-identity-pipeline"
PIPELINE_SCHEMA = "mfds-identity-pipeline-v1"
_SOURCE_NOT_AUTHORIZED_MARKERS = (
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
    "code=30",
    "등록되지 않은 서비스키",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
            "last_total_count": None,
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
        "last_total_count": payload.get("last_total_count"),
    }


def _write_report(output: Path, payload: Mapping[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True))


def sync(
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
        cycle_completed = False
        purged_stale_rows = 0
        pages_collected = 0
        rows_seen = 0
        upserted = 0
        new_raw_objects = 0
        total_count: int | None = None
        last_raw_key: str | None = None

        try:
            with PublicDataPortalClient(
                service_key,
                timeout_seconds=settings.mfds_request_timeout_seconds,
                max_retries=settings.mfds_max_retries,
            ) as client:
                for _ in range(max_pages):
                    try:
                        payload = client.get_json(
                            settings.mfds_product_info_base_url or MFDS_PRODUCT_INFO_BASE_URL,
                            MFDS_PRODUCT_INFO_OPERATION,
                            pageNo=page_no,
                            numOfRows=rows_per_page,
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
                        raise

                    page = unwrap_mfds_page(payload)
                    total_count = page.total_count if page.total_count is not None else total_count
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
                        page_no = 1
                        cycle_completed = True
                        pipeline["complete_cycles"] = int(pipeline["complete_cycles"]) + 1
                        pipeline["cycle"] = active_cycle + 1
                        break

                    page_no += 1
                    if total_count is not None and (page_no - 1) * rows_per_page >= total_count:
                        page_no = 1
                        cycle_completed = True
                        pipeline["complete_cycles"] = int(pipeline["complete_cycles"]) + 1
                        pipeline["cycle"] = active_cycle + 1
                        break

            if cycle_completed:
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
        }
        state_store.write_json(MFDS_IDENTITY_POINTER_STATE, pointer_payload)

        pipeline["next_page"] = page_no
        pipeline["last_total_count"] = total_count
        pipeline["updated_at"] = _now()
        state_store.write_json(PIPELINE_STATE, pipeline)

        if previous_ref is not None and previous_ref.key != ref.key:
            try:
                artifact_store.delete(previous_ref.key)
            except Exception:
                pass

        report = {
            "status": "SUCCESS",
            "pages_collected": pages_collected,
            "rows_seen": rows_seen,
            "rows_upserted": upserted,
            "row_count": row_count,
            "new_raw_objects": new_raw_objects,
            "next_page": page_no,
            "cycle": pipeline["cycle"],
            "complete_cycles": pipeline["complete_cycles"],
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
