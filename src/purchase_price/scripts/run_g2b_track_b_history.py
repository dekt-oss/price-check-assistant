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
from datetime import date
from pathlib import Path
from time import monotonic, sleep
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
from purchase_price.services.g2b_daily_usage import record_calls, remaining_today
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


# Requests take ~1.1 s. Stop starting new batches this long before the deadline so the last
# batch (at most ``batch_budget`` requests) and the state write finish inside the job timeout.
SECONDS_PER_REQUEST_ESTIMATE = 1.3
MAX_CONSECUTIVE_SOURCE_ERRORS = 3
SOURCE_ERROR_PAUSE_SECONDS = 60.0


def run(
    *,
    request_budget: int,
    output: Path,
    max_minutes: float = 0.0,
    clock=monotonic,
    pause=sleep,
) -> int:
    """Collect one batch, or with ``max_minutes`` keep collecting batches until done or out of time.

    State is written to R2 after every batch, so a stopped or failed job resumes exactly. Connection
    errors (data.go.kr ConnectTimeout happened on 2026-10-08) pause and retry from the saved cursor.
    """

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
    client = PublicDataPortalClient(
        shopping_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    started = clock()
    batch_seconds: list[float] = []
    deadline = started + max_minutes * 60 if max_minutes > 0 else None
    batches: list[dict[str, Any]] = []
    exit_code = 0
    consecutive_errors = 0

    cap_reached = False
    while not state.complete:
        if deadline is not None and batches:
            # A batch took longer than the per-request estimate on 2026-10-09, so the 140-minute
            # runs overran the job timeout and ended "cancelled": also use the slowest batch so far.
            next_batch_seconds = max(
                request_budget * SECONDS_PER_REQUEST_ESTIMATE, max(batch_seconds, default=0.0)
            )
            if clock() + next_batch_seconds > deadline:
                break
        # Leave part of the shared daily quota for the production app's live lookups.
        batch_budget = min(request_budget, remaining_today(state_store))
        if batch_budget < 1:
            cap_reached = True
            break
        tier, begin, end = state.current_pass
        codes = state.current_codes
        store = ManifestingRawStore(R2RawEvidenceStore.from_settings(settings))
        batch_started = clock()
        summary = collect_track_b_batch(
            catalog_client=client,
            shopping_client=client,
            store=store,
            catalog_base_url="unused-explicit-targets",
            shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            begin=date.fromisoformat(begin),
            end=date.fromisoformat(end),
            start_cursor=state.cursor,
            request_budget=batch_budget,
            segments=tuple(sorted({code[:2] for code in codes})),
            explicit_target_codes=codes,
        )
        state.apply_collection(summary, object_keys=store.object_keys)
        state_store.write_json(HISTORY_STATE_NAME, state.to_payload())
        batch_seconds.append(clock() - batch_started)
        record_calls(state_store, summary.total_requests)
        batches.append(
            {
                "tier": tier,
                "begin_date": begin,
                "end_date": end,
                "track_b_requests": summary.track_b_requests,
                "pages_stored": summary.pages_stored,
                "rows_seen": summary.rows_seen,
                "stop_reason": summary.stop_reason,
                "error_type": summary.error_type,
            }
        )
        exit_code = _exit_code_for_collection(summary)
        if deadline is None:
            break
        if summary.stop_reason in {"TARGET_COMPLETE", "REQUEST_BUDGET_EXHAUSTED"}:
            consecutive_errors = 0
            continue
        if summary.stop_reason == "RATE_LIMIT_EXHAUSTED":
            break
        consecutive_errors += 1
        if consecutive_errors >= MAX_CONSECUTIVE_SOURCE_ERRORS:
            break
        pause(SOURCE_ERROR_PAUSE_SECONDS)

    if state.complete:
        exit_code = 0
    _write(
        output,
        {
            "status": "SUCCESS" if exit_code == 0 else "FAILED",
            "mode": "history_backfill",
            "stop_reason": "HISTORY_COMPLETE" if state.complete else (
                "DAILY_CALL_CAP_REACHED" if cap_reached else (
                    batches[-1]["stop_reason"] if batches else "NO_BATCH"
                )
            ),
            "history_complete": state.complete,
            "batches": batches,
            "track_b_requests": sum(batch["track_b_requests"] for batch in batches),
            "pages_stored": sum(batch["pages_stored"] for batch in batches),
            "rows_seen": sum(batch["rows_seen"] for batch in batches),
            "elapsed_minutes": round((clock() - started) / 60, 1),
            "progress": state.progress(),
            "pending_object_count": len(state.pending_object_keys),
        },
    )
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one batch of older Track B trades")
    parser.add_argument("--request-budget", type=int, default=5000)
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=0.0,
        help="Keep collecting batches until done or this many minutes have passed (0: one batch)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-history/collection-summary.json"),
    )
    args = parser.parse_args()
    return run(request_budget=args.request_budget, output=args.output, max_minutes=args.max_minutes)


if __name__ == "__main__":
    raise SystemExit(main())
