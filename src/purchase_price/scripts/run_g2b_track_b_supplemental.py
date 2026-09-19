from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.scripts.collect_g2b_track_b_r2 import collect_track_b_batch
from purchase_price.scripts.run_g2b_track_b_daily import (
    ManifestingRawStore,
    _collection_clients,
    _exit_code_for_collection,
    _kst_today,
    _next_rolling_window,
)
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.services.track_b_pipeline_state import (
    BACKFILL_BEGIN_DATE,
    BACKFILL_END_DATE,
    STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.services.track_b_supplemental_state import (
    SUPPLEMENTAL_STATE_NAME,
    TrackBSupplementalState,
)
from purchase_price.services.track_b_supplemental_targets import supplemental_verified_codes
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_state import R2OperationalStateStore

MAX_SUPPLEMENTAL_REQUEST_BUDGET = 100


def _write_summary(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _load_base_state(state_store: R2OperationalStateStore) -> TrackBPipelineState:
    payload = state_store.read_json(STATE_NAME)
    if payload is None:
        raise RuntimeError("base Track B pipeline state is missing")
    return TrackBPipelineState.from_payload(payload)


def _load_supplemental_state(state_store: R2OperationalStateStore) -> TrackBSupplementalState:
    payload = state_store.read_json(SUPPLEMENTAL_STATE_NAME)
    if payload is None:
        return TrackBSupplementalState()
    return TrackBSupplementalState.from_payload(payload)


def _locked_window(state: TrackBSupplementalState) -> tuple[date, date]:
    if state.active_mode == "historical":
        return date.fromisoformat(BACKFILL_BEGIN_DATE), date.fromisoformat(BACKFILL_END_DATE)
    if state.active_mode != "rolling":
        raise RuntimeError("supplemental collection has no active mode")
    if state.rolling_window_begin is None or state.rolling_window_end is None:
        raise RuntimeError("supplemental rolling window is incomplete")
    return date.fromisoformat(state.rolling_window_begin), date.fromisoformat(
        state.rolling_window_end
    )


def run_supplemental(*, request_budget: int, summary_path: Path) -> int:
    if request_budget < 1 or request_budget > MAX_SUPPLEMENTAL_REQUEST_BUDGET:
        raise ValueError(
            f"supplemental request_budget must be between 1 and {MAX_SUPPLEMENTAL_REQUEST_BUDGET}"
        )

    settings = get_settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")

    state_store = R2OperationalStateStore.from_settings(settings)
    base_state = _load_base_state(state_store)
    current_codes = supplemental_verified_codes()
    state = _load_supplemental_state(state_store)

    if state.active_codes and not set(state.active_codes).issubset(current_codes):
        revoked = sorted(set(state.active_codes).difference(current_codes))
        raise RuntimeError(
            "active supplemental target was removed from verified mappings; "
            f"manual state review required: {revoked}"
        )

    if not current_codes:
        _write_summary(
            summary_path,
            {
                "status": "SUCCESS",
                "mode": "supplemental",
                "stop_reason": "NO_VERIFIED_SUPPLEMENTAL_TARGETS",
                "target_codes": [],
                "pending_object_count": len(state.pending_object_keys),
            },
        )
        return 0

    if not base_state.backfill_complete:
        _write_summary(
            summary_path,
            {
                "status": "SUCCESS",
                "mode": "supplemental",
                "stop_reason": "BASE_HISTORICAL_BACKFILL_IN_PROGRESS",
                "base_cursor": {
                    "code_index": base_state.collection_cursor.code_index,
                    "page_no": base_state.collection_cursor.page_no,
                },
                "target_codes": list(current_codes),
                "pending_object_count": len(state.pending_object_keys),
            },
        )
        return 0

    if state.active_mode is None:
        missing_historical = state.missing_historical_codes(current_codes)
        if missing_historical:
            state.begin_historical(missing_historical)
            state_store.write_json(SUPPLEMENTAL_STATE_NAME, state.to_payload())
        else:
            planned = _next_rolling_window(state, today=_kst_today())
            if planned is None:
                _write_summary(
                    summary_path,
                    {
                        "status": "SUCCESS",
                        "mode": "supplemental_rolling",
                        "stop_reason": "ROLLING_UP_TO_DATE",
                        "target_codes": list(current_codes),
                        "rolling_covered_through": state.rolling_covered_through,
                        "rolling_cycles_completed": state.rolling_cycles_completed,
                        "pending_object_count": len(state.pending_object_keys),
                    },
                )
                return 0
            begin, end, _strategy = planned
            state.begin_rolling(current_codes, begin=begin, end=end)
            state_store.write_json(SUPPLEMENTAL_STATE_NAME, state.to_payload())

    begin, end = _locked_window(state)
    active_codes = tuple(state.active_codes)
    segments = tuple(sorted({code[:2] for code in active_codes}))

    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not catalog_key or not shopping_key:
        raise RuntimeError("G2B catalog/shopping service keys are not configured")
    catalog_client, shopping_client = _collection_clients(
        settings,
        catalog_key=catalog_key,
        shopping_key=shopping_key,
    )
    manifesting_store = ManifestingRawStore(R2RawEvidenceStore.from_settings(settings))
    summary = collect_track_b_batch(
        catalog_client=catalog_client,
        shopping_client=shopping_client,
        store=manifesting_store,
        catalog_base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
        shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        begin=begin,
        end=end,
        start_cursor=state.cursor,
        request_budget=request_budget,
        segments=segments,
        explicit_target_codes=active_codes,
    )
    mode = state.active_mode
    state.apply_collection(summary, object_keys=manifesting_store.object_keys)
    state_store.write_json(SUPPLEMENTAL_STATE_NAME, state.to_payload())

    report = {
        **asdict(summary),
        "mode": f"supplemental_{mode}",
        "target_codes": list(active_codes),
        "historical_completed_codes": list(state.historical_completed_codes),
        "rolling_covered_through": state.rolling_covered_through,
        "rolling_cycles_completed": state.rolling_cycles_completed,
        "pending_object_count": len(state.pending_object_keys),
    }
    _write_summary(summary_path, report)
    return _exit_code_for_collection(summary)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run verified supplemental Track B collection without mutating the base snapshot"
    )
    parser.add_argument("--request-budget", type=int, default=25)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-supplemental/collection-summary.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return run_supplemental(
        request_budget=args.request_budget,
        summary_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
