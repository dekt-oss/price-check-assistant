"""Collect one budgeted batch of Track B trades older than the base backfill (back to 2021).

Each run resumes the frozen pass order in ``track-b/history-backfill`` and records the new raw
pages as pending, so the serving-index workflow folds them in incrementally. See
``services/track_b_history_state.py`` for the order and why it exists.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.scripts.collect_g2b_track_b_r2 import TARGET_SEGMENTS, collect_track_b_batch
from purchase_price.scripts.run_g2b_track_b_daily import (
    ManifestingRawStore,
    _exit_code_for_collection,
    _restore_snapshot,
)
from purchase_price.services.g2b_target_code_snapshot import load_target_code_snapshot
from purchase_price.services.track_b_history_state import (
    HISTORY_STATE_NAME,
    TrackBHistoryState,
    build_tiers,
)
from purchase_price.services.track_b_pipeline_state import SERVING_INDEX_STATE_NAME
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_serving_index import R2ServingIndexRef, R2ServingIndexStore
from purchase_price.storage.r2_state import R2OperationalStateStore


def _write(path: Path, report: Mapping[str, Any]) -> None:
    rendered = json.dumps(dict(report), ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _active_codes_from_serving_index(settings, state_store: R2OperationalStateStore) -> set[str]:
    """Codes that had at least one trade in the current serving index (the last year)."""

    pointer = state_store.read_json(SERVING_INDEX_STATE_NAME)
    if not pointer:
        raise RuntimeError("Track B serving index is required to rank history targets")
    ref = R2ServingIndexRef(
        key=str(pointer["key"]),
        sha256=str(pointer["sha256"]),
        stored_bytes=int(pointer.get("stored_bytes") or 0),
        uncompressed_bytes=int(pointer.get("uncompressed_bytes") or 0),
    )
    with tempfile.TemporaryDirectory(prefix="track-b-history-") as temp_dir:
        path = Path(temp_dir) / "serving.sqlite"
        R2ServingIndexStore.from_settings(settings).download_sqlite(ref, path)
        connection = sqlite3.connect(path)
        try:
            rows = connection.execute(
                "SELECT DISTINCT detail_code FROM track_b_delivery_lines"
            ).fetchall()
        finally:
            connection.close()
    return {str(row[0]) for row in rows if row[0]}


def _load_or_bootstrap(
    *,
    settings,
    state_store: R2OperationalStateStore,
    snapshot_path: Path,
) -> TrackBHistoryState:
    payload = state_store.read_json(HISTORY_STATE_NAME)
    if payload is not None:
        return TrackBHistoryState.from_payload(payload)
    snapshot = load_target_code_snapshot(snapshot_path, expected_segments=TARGET_SEGMENTS)
    active = _active_codes_from_serving_index(settings, state_store)
    state = TrackBHistoryState.bootstrap(build_tiers(snapshot.codes, active))
    # Freeze the order before any request so an interrupted first run resumes the same pass.
    state_store.write_json(HISTORY_STATE_NAME, state.to_payload())
    return state


def run(*, request_budget: int, output: Path) -> int:
    settings = get_settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not shopping_key:
        raise RuntimeError("G2B shopping service key is not configured")

    state_store = R2OperationalStateStore.from_settings(settings)
    snapshot_path = _restore_snapshot(
        state_store=state_store,
        bootstrap_snapshot=None,
        output_path=output.parent / "track-b-target-codes.json",
    )
    state = _load_or_bootstrap(settings=settings, state_store=state_store, snapshot_path=snapshot_path)
    if state.complete:
        _write(
            output,
            {
                "status": "SUCCESS",
                "mode": "history_backfill",
                "stop_reason": "HISTORY_COMPLETE",
                "progress": state.progress(),
                "pending_object_count": len(state.pending_object_keys),
            },
        )
        return 0

    tier, begin, end = state.current_pass
    codes = state.current_codes
    client = PublicDataPortalClient(
        shopping_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    store = ManifestingRawStore(R2RawEvidenceStore.from_settings(settings))
    summary = collect_track_b_batch(
        catalog_client=client,
        shopping_client=client,
        store=store,
        catalog_base_url="unused-explicit-targets",
        shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        begin=date.fromisoformat(begin),
        end=date.fromisoformat(end),
        start_cursor=state.cursor,
        request_budget=request_budget,
        segments=tuple(sorted({code[:2] for code in codes})),
        explicit_target_codes=codes,
    )
    state.apply_collection(summary, object_keys=store.object_keys)
    state_store.write_json(HISTORY_STATE_NAME, state.to_payload())
    _write(
        output,
        {
            **asdict(summary),
            "mode": "history_backfill",
            "tier": tier,
            "progress": state.progress(),
            "pending_object_count": len(state.pending_object_keys),
        },
    )
    return _exit_code_for_collection(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one batch of older Track B trades")
    parser.add_argument("--request-budget", type=int, default=5000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-history/collection-summary.json"),
    )
    args = parser.parse_args()
    return run(request_budget=args.request_budget, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
