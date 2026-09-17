from __future__ import annotations

import argparse
import json
import math
import sqlite3
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from purchase_price.config import Settings
from purchase_price.scripts.collect_g2b_track_b_r2 import TRACK_B_OPERATION, CollectionCursor
from purchase_price.services.g2b_target_code_snapshot import TargetCodeSnapshot, load_target_code_snapshot
from purchase_price.services.g2b_track_b_audit import TrackBAuditAccumulator
from purchase_price.services.g2b_track_b_normalization import (
    TrackBIdentityConflictError,
    TrackBNormalizationError,
    TrackBRawPage,
)
from purchase_price.services.track_b_pipeline_state import (
    BACKFILL_BEGIN_DATE,
    BACKFILL_END_DATE,
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_TARGET_CODE_COUNT,
    SERVING_INDEX_STATE_NAME,
    SNAPSHOT_STATE_NAME,
    STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_reader import R2RawEvidenceReader
from purchase_price.storage.r2_serving_index import R2ServingIndexRef, R2ServingIndexStore
from purchase_price.storage.r2_state import R2OperationalStateStore

TRACK_B_PAGE_OPERATION = f"{TRACK_B_OPERATION}-page"
POINTER_SCHEMA = "track-b-serving-index-pointer-v1"


def _load_snapshot(state_store: R2OperationalStateStore) -> TargetCodeSnapshot:
    payload = state_store.read_json(SNAPSHOT_STATE_NAME)
    if payload is None:
        raise RuntimeError("Track B target-code snapshot is missing from R2 state")
    with tempfile.TemporaryDirectory(prefix="track-b-audit-snapshot-") as temp_dir:
        path = Path(temp_dir) / "track-b-target-codes.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        snapshot = load_target_code_snapshot(
            path,
            expected_segments=tuple(payload.get("segments") or ()),
        )
    if snapshot.sha256 != EXPECTED_SNAPSHOT_SHA256:
        raise RuntimeError(f"Track B snapshot SHA mismatch: {snapshot.sha256}")
    if snapshot.code_count != EXPECTED_TARGET_CODE_COUNT:
        raise RuntimeError(f"Track B snapshot code count mismatch: {snapshot.code_count}")
    return snapshot


def completed_code_set(snapshot: TargetCodeSnapshot, cursor: CollectionCursor) -> set[str]:
    if cursor.code_index < 0 or cursor.code_index > snapshot.code_count or cursor.page_no < 1:
        raise ValueError("invalid Track B collection cursor")
    return set(snapshot.codes[: cursor.code_index])


def build_segment_coverage(
    *,
    snapshot: TargetCodeSnapshot,
    cursor: CollectionCursor,
    classification_counts: Mapping[str, Mapping[str, int]],
    page_codes: set[str],
    serving_by_code: Mapping[str, Mapping[str, int]] | None = None,
) -> dict[str, dict[str, int | float]]:
    completed = completed_code_set(snapshot, cursor)
    serving_by_code = serving_by_code or {}
    result: dict[str, dict[str, int | float]] = {}
    for segment in snapshot.segments:
        codes = [code for code in snapshot.codes if code.startswith(segment)]
        code_set = set(codes)
        completed_in_segment = code_set & completed
        page_codes_in_segment = code_set & page_codes
        rows_codes = {
            code
            for code in codes
            if int(classification_counts.get(code, {}).get("raw_rows", 0)) > 0
        }
        priced_codes = {
            code
            for code in codes
            if int(classification_counts.get(code, {}).get("price_candidates", 0)) > 0
        }
        target_count = len(codes)
        result[segment] = {
            "target_codes": target_count,
            "query_completed_codes": len(completed_in_segment),
            "query_completed_pct": round(
                (len(completed_in_segment) / target_count * 100.0)
                if target_count
                else 0.0,
                3,
            ),
            "codes_with_raw_page": len(page_codes_in_segment),
            "codes_with_rows": len(rows_codes),
            "codes_with_price_observation": len(priced_codes),
            "raw_rows": sum(
                int(classification_counts.get(code, {}).get("raw_rows", 0))
                for code in codes
            ),
            "normalized_rows": sum(
                int(classification_counts.get(code, {}).get("normalized_rows", 0))
                for code in codes
            ),
            "price_observations": sum(
                int(classification_counts.get(code, {}).get("price_candidates", 0))
                for code in codes
            ),
            "serving_rows": sum(
                int(serving_by_code.get(code, {}).get("rows", 0))
                for code in codes
            ),
            "serving_positive_price_rows": sum(
                int(serving_by_code.get(code, {}).get("positive_price_rows", 0))
                for code in codes
            ),
        }
    return result


def _read_serving_index(
    *, settings: Settings, state_store: R2OperationalStateStore
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    pointer = state_store.read_json(SERVING_INDEX_STATE_NAME)
    if pointer is None:
        return {"status": "MISSING"}, {}
    if pointer.get("schema") != POINTER_SCHEMA:
        raise RuntimeError("Track B serving-index pointer schema mismatch")
    key = str(pointer.get("key") or "").strip()
    sha256 = str(pointer.get("sha256") or "").strip()
    if not key or len(sha256) != 64:
        raise RuntimeError("Track B serving-index pointer is incomplete")
    ref = R2ServingIndexRef(
        key=key,
        sha256=sha256,
        stored_bytes=int(pointer.get("stored_bytes") or 0),
        uncompressed_bytes=int(pointer.get("uncompressed_bytes") or 0),
    )
    with tempfile.TemporaryDirectory(prefix="track-b-serving-audit-") as temp_dir:
        path = Path(temp_dir) / "serving.sqlite"
        R2ServingIndexStore.from_settings(settings).download_sqlite(ref, path)
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            totals = connection.execute(
                """
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN unit_price > 0 THEN 1 ELSE 0 END),
                    COUNT(DISTINCT detail_code),
                    SUM(CASE WHEN change_order_number > 0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN identity_conflict = 1 THEN 1 ELSE 0 END)
                FROM track_b_delivery_lines
                """
            ).fetchone()
            by_code_rows = connection.execute(
                """
                SELECT detail_code,
                       COUNT(*),
                       SUM(CASE WHEN unit_price > 0 THEN 1 ELSE 0 END)
                FROM track_b_delivery_lines
                GROUP BY detail_code
                """
            ).fetchall()
        finally:
            connection.close()
    by_code = {
        str(code): {
            "rows": int(rows or 0),
            "positive_price_rows": int(positive or 0),
        }
        for code, rows, positive in by_code_rows
    }
    report = {
        "status": "SUCCESS" if integrity == "ok" else "FAILED_INTEGRITY",
        "integrity_check": integrity,
        "key": key,
        "sha256": sha256,
        "stored_bytes": ref.stored_bytes,
        "uncompressed_bytes": ref.uncompressed_bytes,
        "pointer_row_count": int(pointer.get("row_count") or 0),
        "physical_row_count": int(totals[0] or 0),
        "positive_price_rows": int(totals[1] or 0),
        "distinct_detail_codes": int(totals[2] or 0),
        "changed_order_rows": int(totals[3] or 0),
        "identity_conflict_rows": int(totals[4] or 0),
        "collection_cursor": pointer.get("collection_cursor"),
        "updated_at": pointer.get("updated_at"),
    }
    return report, by_code


def _audit_raw_historical(
    *, reader: R2RawEvidenceReader, snapshot: TargetCodeSnapshot
) -> tuple[dict[str, Any], set[str], dict[str, set[int]], dict[str, int]]:
    objects = reader.list_public_json(source_operation=TRACK_B_PAGE_OPERATION)
    audit = TrackBAuditAccumulator()
    target_codes = set(snapshot.codes)
    page_codes: set[str] = set()
    pages_by_code: dict[str, set[int]] = defaultdict(set)
    expected_pages_by_code: dict[str, int] = {}
    historical_stored_bytes = 0
    ignored_stored_bytes = 0
    ignored_windows: Counter[str] = Counter()
    out_of_target_codes: Counter[str] = Counter()
    policy_violations = 0
    historical_objects = 0

    for obj in objects:
        payload = reader.get_public_json(obj)
        if not isinstance(payload, Mapping):
            audit.invalid_pages += 1
            continue
        request = payload.get("request")
        response = payload.get("response")
        if not isinstance(request, Mapping) or not isinstance(response, Mapping):
            audit.invalid_pages += 1
            continue
        begin = str(request.get("begin_date") or "")
        end = str(request.get("end_date") or "")
        if (begin, end) != (BACKFILL_BEGIN_DATE, BACKFILL_END_DATE):
            ignored_windows[f"{begin}..{end}"] += 1
            ignored_stored_bytes += obj.stored_bytes
            continue

        historical_objects += 1
        historical_stored_bytes += obj.stored_bytes
        code = str(request.get("detail_code") or "").strip()
        try:
            page_no = int(request.get("page_no") or 0)
            page_size = int(request.get("page_size") or 0)
            total_count = int(response.get("total_count") or 0)
        except (TypeError, ValueError):
            audit.invalid_pages += 1
            continue
        if request.get("final_change_order_filter") != "OMITTED":
            policy_violations += 1
        if code not in target_codes:
            out_of_target_codes[code or "<missing>"] += 1
        if page_no < 1 or page_size < 1:
            audit.invalid_pages += 1
            continue
        page_codes.add(code)
        pages_by_code[code].add(page_no)
        expected_pages_by_code[code] = max(
            expected_pages_by_code.get(code, 0),
            max(1, math.ceil(total_count / page_size)),
        )
        try:
            audit.add_page(
                TrackBRawPage(
                    payload=payload,
                    raw_object_key=obj.key,
                    raw_payload_sha256=obj.payload_hash,
                )
            )
        except TrackBIdentityConflictError:
            raise
        except TrackBNormalizationError:
            audit.invalid_pages += 1

    report = audit.summary().as_dict()
    report.update(
        {
            "raw_objects_all_windows": len(objects),
            "historical_raw_objects": historical_objects,
            "historical_raw_stored_bytes": historical_stored_bytes,
            "ignored_non_historical_objects": len(objects) - historical_objects,
            "ignored_non_historical_stored_bytes": ignored_stored_bytes,
            "ignored_windows": dict(sorted(ignored_windows.items())),
            "final_change_order_policy_violations": policy_violations,
            "out_of_target_codes": dict(sorted(out_of_target_codes.items())),
        }
    )
    return report, page_codes, pages_by_code, expected_pages_by_code


def _consistency_report(
    *,
    snapshot: TargetCodeSnapshot,
    state: TrackBPipelineState,
    raw_report: Mapping[str, Any],
    page_codes: set[str],
    pages_by_code: Mapping[str, set[int]],
    expected_pages_by_code: Mapping[str, int],
    serving: Mapping[str, Any],
    serving_by_code: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    completed = completed_code_set(snapshot, state.collection_cursor)
    missing_completed_codes = sorted(completed - page_codes)
    incomplete_completed_pages: dict[str, list[int]] = {}
    for code in sorted(completed & page_codes):
        expected = expected_pages_by_code.get(code, 1)
        missing = sorted(set(range(1, expected + 1)) - pages_by_code.get(code, set()))
        if missing:
            incomplete_completed_pages[code] = missing

    raw_classifications = raw_report.get("classification_counts") or {}
    raw_codes = {
        str(code)
        for code, counts in raw_classifications.items()
        if isinstance(counts, Mapping) and int(counts.get("normalized_rows", 0)) > 0
    }
    serving_codes = {
        code for code, counts in serving_by_code.items() if int(counts.get("rows", 0)) > 0
    }
    raw_rows = int(raw_report.get("normalized_records") or 0)
    raw_prices = int(raw_report.get("price_candidates") or 0)
    serving_rows = int(serving.get("physical_row_count") or 0)
    serving_prices = int(serving.get("positive_price_rows") or 0)
    return {
        "collection_complete": state.backfill_complete,
        "collection_cursor": asdict(state.collection_cursor),
        "query_completed_codes": len(completed),
        "target_codes": snapshot.code_count,
        "query_completed_pct": round(len(completed) / snapshot.code_count * 100.0, 3),
        "remaining_target_codes": snapshot.code_count - len(completed),
        "missing_raw_page_for_completed_codes": missing_completed_codes,
        "missing_raw_page_for_completed_count": len(missing_completed_codes),
        "incomplete_page_sets_for_completed_codes": incomplete_completed_pages,
        "incomplete_page_set_count": len(incomplete_completed_pages),
        "pending_serving_objects": len(state.pending_object_keys),
        "raw_vs_serving_row_delta": serving_rows - raw_rows,
        "raw_vs_serving_positive_price_delta": serving_prices - raw_prices,
        "raw_codes_missing_from_serving": sorted(raw_codes - serving_codes),
        "serving_codes_missing_from_raw": sorted(serving_codes - raw_codes),
        "snapshot_active_only": True,
    }


def run(*, output: Path) -> dict[str, Any]:
    settings = Settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 configuration is required for Track B historical audit")
    state_store = R2OperationalStateStore.from_settings(settings)
    state_payload = state_store.read_json(STATE_NAME)
    if state_payload is None:
        raise RuntimeError("Track B pipeline state is missing from R2")
    state = TrackBPipelineState.from_payload(state_payload)
    snapshot = _load_snapshot(state_store)
    reader = R2RawEvidenceReader.from_settings(settings)
    raw_report, page_codes, pages_by_code, expected_pages_by_code = _audit_raw_historical(
        reader=reader,
        snapshot=snapshot,
    )
    serving, serving_by_code = _read_serving_index(settings=settings, state_store=state_store)
    classification_counts = raw_report.get("classification_counts") or {}
    if not isinstance(classification_counts, Mapping):
        raise RuntimeError("Track B audit classification counts are invalid")
    segment_coverage = build_segment_coverage(
        snapshot=snapshot,
        cursor=state.collection_cursor,
        classification_counts=classification_counts,
        page_codes=page_codes,
        serving_by_code=serving_by_code,
    )
    consistency = _consistency_report(
        snapshot=snapshot,
        state=state,
        raw_report=raw_report,
        page_codes=page_codes,
        pages_by_code=pages_by_code,
        expected_pages_by_code=expected_pages_by_code,
        serving=serving,
        serving_by_code=serving_by_code,
    )
    usage = R2RawEvidenceStore.from_settings(settings).measure_bucket_usage()
    critical_issues = []
    if raw_report.get("invalid_pages"):
        critical_issues.append("invalid_raw_pages")
    if raw_report.get("final_change_order_policy_violations"):
        critical_issues.append("final_change_order_policy_violation")
    if raw_report.get("out_of_target_codes"):
        critical_issues.append("out_of_target_code")
    if consistency["missing_raw_page_for_completed_count"]:
        critical_issues.append("completed_code_missing_raw_page")
    if consistency["incomplete_page_set_count"]:
        critical_issues.append("completed_code_missing_page")
    if consistency["pending_serving_objects"]:
        critical_issues.append("serving_index_pending_objects")
    if serving.get("status") != "SUCCESS":
        critical_issues.append("serving_index_integrity")
    if consistency["raw_vs_serving_row_delta"] != 0:
        critical_issues.append("raw_serving_row_mismatch")
    if consistency["raw_vs_serving_positive_price_delta"] != 0:
        critical_issues.append("raw_serving_price_mismatch")
    if serving.get("identity_conflict_rows"):
        critical_issues.append("serving_identity_conflict")

    report = {
        "status": (
            "FAILED"
            if critical_issues
            else ("COMPLETE" if state.backfill_complete else "COLLECTION_IN_PROGRESS")
        ),
        "critical_issues": critical_issues,
        "historical_window": {
            "begin_date": BACKFILL_BEGIN_DATE,
            "end_date": BACKFILL_END_DATE,
        },
        "snapshot": {
            "sha256": snapshot.sha256,
            "generated_at": snapshot.generated_at,
            "active_only": True,
            "target_code_count": snapshot.code_count,
            "segments": list(snapshot.segments),
        },
        "pipeline": {
            "backfill_complete": state.backfill_complete,
            "collection_cursor": asdict(state.collection_cursor),
            "pending_object_count": len(state.pending_object_keys),
            "updated_at": state.updated_at,
        },
        "segment_coverage": segment_coverage,
        "raw_historical": raw_report,
        "serving_index": serving,
        "consistency": consistency,
        "r2_capacity": {
            "bucket_object_count": usage.object_count,
            "bucket_stored_bytes": usage.stored_bytes,
            "hard_limit_bytes": usage.hard_limit_bytes,
            "warn_limit_bytes": usage.warn_limit_bytes,
            "remaining_bytes": usage.remaining_bytes,
            "hard_limit_utilization_pct": round(
                usage.stored_bytes / usage.hard_limit_bytes * 100.0,
                4,
            ),
            "warning": usage.warning,
        },
        "public_api_requests": 0,
        "r2_writes": 0,
        "database_writes": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Track B historical corpus / serving-index consistency audit"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-audit/historical-audit.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = run(output=args.output)
    return 1 if report["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
