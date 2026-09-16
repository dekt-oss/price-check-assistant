from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.scripts.collect_g2b_track_b_r2 import (
    TRACK_B_OPERATION,
    TARGET_SEGMENTS,
    collect_track_b_batch,
)
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.services.g2b_target_code_snapshot import load_target_code_snapshot
from purchase_price.services.track_b_pipeline_state import (
    BACKFILL_BEGIN_DATE,
    BACKFILL_END_DATE,
    BOOTSTRAP_LAST_OBJECT_KEY,
    BOOTSTRAP_MIN_R2_OBJECTS,
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_TARGET_CODE_COUNT,
    SNAPSHOT_STATE_NAME,
    STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.storage.r2 import R2RawEvidenceStore, RawObjectRef
from purchase_price.storage.r2_reader import R2RawEvidenceReader
from purchase_price.storage.r2_state import R2OperationalStateStore

TRACK_B_PAGE_OPERATION = f"{TRACK_B_OPERATION}-page"


class ManifestingRawStore:
    def __init__(self, inner: R2RawEvidenceStore) -> None:
        self.inner = inner
        self.object_keys: list[str] = []

    def put_public_json(self, *, source_operation: str, payload: object) -> RawObjectRef:
        ref = self.inner.put_public_json(source_operation=source_operation, payload=payload)
        self.object_keys.append(ref.key)
        return ref


def _restore_snapshot(
    *,
    state_store: R2OperationalStateStore,
    bootstrap_snapshot: Path | None,
    output_path: Path,
) -> Path:
    persisted = state_store.read_json(SNAPSHOT_STATE_NAME)
    should_persist = persisted is None
    if persisted is None:
        if bootstrap_snapshot is None or not bootstrap_snapshot.exists():
            raise RuntimeError(
                "validated target-code snapshot is not persisted in R2 "
                "and bootstrap artifact is unavailable"
            )
        payload = json.loads(bootstrap_snapshot.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise RuntimeError("bootstrap target-code snapshot must be a JSON object")
        persisted = dict(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    snapshot = load_target_code_snapshot(output_path, expected_segments=TARGET_SEGMENTS)
    if snapshot.sha256 != EXPECTED_SNAPSHOT_SHA256:
        raise RuntimeError(f"target-code snapshot SHA mismatch: {snapshot.sha256}")
    if snapshot.code_count != EXPECTED_TARGET_CODE_COUNT:
        raise RuntimeError(f"target-code snapshot count mismatch: {snapshot.code_count}")
    if should_persist:
        state_store.write_json(SNAPSHOT_STATE_NAME, persisted)
    return output_path


def _load_or_bootstrap_pipeline_state(
    *,
    state_store: R2OperationalStateStore,
    reader: R2RawEvidenceReader,
) -> TrackBPipelineState:
    payload = state_store.read_json(STATE_NAME)
    if payload is not None:
        return TrackBPipelineState.from_payload(payload)

    objects = reader.list_public_json(source_operation=TRACK_B_PAGE_OPERATION)
    keys = {obj.key for obj in objects}
    if len(objects) < BOOTSTRAP_MIN_R2_OBJECTS or BOOTSTRAP_LAST_OBJECT_KEY not in keys:
        raise RuntimeError(
            "cannot bootstrap Track B cursor 3196: existing R2 evidence does not match batch-004 proof"
        )
    state = TrackBPipelineState.bootstrap()
    state_store.write_json(STATE_NAME, state.to_payload())
    return state


def run_daily(
    *,
    request_budget: int,
    bootstrap_snapshot: Path | None,
    summary_path: Path,
) -> int:
    settings = get_settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not catalog_key or not shopping_key:
        raise RuntimeError("G2B catalog/shopping service keys are not configured")

    state_store = R2OperationalStateStore.from_settings(settings)
    reader = R2RawEvidenceReader.from_settings(settings)
    snapshot_path = _restore_snapshot(
        state_store=state_store,
        bootstrap_snapshot=bootstrap_snapshot,
        output_path=summary_path.parent / "track-b-target-codes.json",
    )
    state = _load_or_bootstrap_pipeline_state(state_store=state_store, reader=reader)

    if not state.db_bootstrap_complete and state.db_bootstrap_cursor is not None:
        report: dict[str, Any] = {
            "status": "SUCCESS",
            "stop_reason": "DB_BOOTSTRAP_IN_PROGRESS",
            "next_cursor": {
                "code_index": state.collection_cursor.code_index,
                "page_no": state.collection_cursor.page_no,
            },
            "pending_object_count": len(state.pending_object_keys),
        }
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    if state.backfill_complete:
        report: dict[str, Any] = {
            "status": "SUCCESS",
            "stop_reason": "ALREADY_COMPLETE",
            "next_cursor": {
                "code_index": state.collection_cursor.code_index,
                "page_no": state.collection_cursor.page_no,
            },
            "pending_object_count": len(state.pending_object_keys),
        }
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    catalog_client = PublicDataPortalClient(
        catalog_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    shopping_client = PublicDataPortalClient(
        shopping_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    manifesting_store = ManifestingRawStore(R2RawEvidenceStore.from_settings(settings))
    summary = collect_track_b_batch(
        catalog_client=catalog_client,
        shopping_client=shopping_client,
        store=manifesting_store,
        catalog_base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
        shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        begin=date.fromisoformat(BACKFILL_BEGIN_DATE),
        end=date.fromisoformat(BACKFILL_END_DATE),
        start_cursor=state.collection_cursor,
        request_budget=request_budget,
        target_code_snapshot_path=snapshot_path,
    )
    state.apply_collection(summary, object_keys=manifesting_store.object_keys)
    state_store.write_json(STATE_NAME, state.to_payload())
    rendered = json.dumps(asdict(summary), ensure_ascii=False, indent=2)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if summary.status in {"SUCCESS", "PARTIAL_SUCCESS"} else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one resumable Track B daily backfill batch")
    parser.add_argument("--request-budget", type=int, default=900)
    parser.add_argument("--bootstrap-snapshot", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-daily/collection-summary.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return run_daily(
        request_budget=args.request_budget,
        bootstrap_snapshot=args.bootstrap_snapshot,
        summary_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
