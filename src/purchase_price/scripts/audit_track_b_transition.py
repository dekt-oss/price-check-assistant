from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from purchase_price.config import Settings
from purchase_price.services.track_b_pipeline_state import (
    BACKFILL_END_DATE,
    EXPECTED_TARGET_CODE_COUNT,
    SERVING_INDEX_STATE_NAME,
    STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.storage.r2_state import R2OperationalStateStore

KST = ZoneInfo("Asia/Seoul")


def _cursor_payload(code_index: int, page_no: int) -> dict[str, int]:
    return {"code_index": code_index, "page_no": page_no}


def _pointer_cursor(pointer: Mapping[str, Any] | None) -> tuple[int, int] | None:
    if not isinstance(pointer, Mapping):
        return None
    raw = pointer.get("collection_cursor")
    if not isinstance(raw, Mapping):
        return None
    try:
        return int(raw.get("code_index", -1)), int(raw.get("page_no", 0))
    except (TypeError, ValueError):
        return None


def audit_transition(
    state: TrackBPipelineState,
    *,
    serving_pointer: Mapping[str, Any] | None,
    today: date,
    require_serving_synced: bool = False,
) -> dict[str, Any]:
    """Summarize historical -> rolling state without treating expected progress as a failure."""

    errors: list[str] = []
    warnings: list[str] = []

    historical_cursor = state.collection_cursor
    historical_complete_cursor = (
        historical_cursor.code_index == EXPECTED_TARGET_CODE_COUNT
        and historical_cursor.page_no == 1
    )
    if state.backfill_complete != historical_complete_cursor:
        errors.append(
            "historical completion flag and collection cursor are inconsistent"
        )

    active_window = (
        state.rolling_window_begin is not None and state.rolling_window_end is not None
    )
    if active_window and not state.backfill_complete:
        errors.append("rolling window is active before historical backfill completion")

    historical_end = date.fromisoformat(BACKFILL_END_DATE)
    covered_through = date.fromisoformat(state.rolling_covered_through)
    if covered_through < historical_end:
        errors.append("rolling covered-through date precedes historical endpoint")

    if state.rolling_cycles_completed > 0 and covered_through <= historical_end:
        errors.append("completed rolling cycles did not advance covered-through date")

    pointer_cursor = _pointer_cursor(serving_pointer)
    expected_pointer_cursor = (
        historical_cursor.code_index,
        historical_cursor.page_no,
    )
    pointer_present = serving_pointer is not None
    serving_cursor_matches = pointer_cursor == expected_pointer_cursor

    if require_serving_synced:
        if not pointer_present:
            errors.append("R2 serving-index pointer is missing after sync")
        elif pointer_cursor is None:
            errors.append("R2 serving-index pointer has no valid collection cursor")
        elif not serving_cursor_matches:
            errors.append(
                "R2 serving-index pointer is behind the historical collection cursor"
            )
        if state.pending_object_keys:
            errors.append("pending raw objects remain after serving-index sync")
    elif state.pending_object_keys:
        warnings.append(
            f"{len(state.pending_object_keys)} pending raw objects await serving-index sync"
        )

    if not state.backfill_complete:
        phase = "historical_progress"
        acceptance_status = "HISTORICAL_IN_PROGRESS"
    elif active_window:
        phase = "rolling_in_progress"
        acceptance_status = "ROLLING_STARTED"
    elif state.rolling_cycles_completed > 0:
        phase = "rolling_operational"
        acceptance_status = "ROLLING_ACCEPTED"
    else:
        phase = "historical_complete_waiting_rolling"
        acceptance_status = "HISTORICAL_COMPLETE_WAITING_FIRST_ROLLING"

    remaining_codes = max(
        EXPECTED_TARGET_CODE_COUNT - historical_cursor.code_index,
        0,
    )
    rolling_lag_days = max((today - covered_through).days, 0)

    last_collection = state.last_collection or {}
    last_rolling = state.last_rolling_collection or {}
    last_serving = state.last_serving_index_sync or {}

    return {
        "status": "fail" if errors else "pass",
        "phase": phase,
        "acceptance_status": acceptance_status,
        "issue_157_acceptance": acceptance_status == "ROLLING_ACCEPTED",
        "checked_at_kst": datetime.now(KST).isoformat(),
        "checked_date_kst": today.isoformat(),
        "historical": {
            "target_code_count": EXPECTED_TARGET_CODE_COUNT,
            "cursor": _cursor_payload(
                historical_cursor.code_index,
                historical_cursor.page_no,
            ),
            "remaining_codes": remaining_codes,
            "backfill_complete": state.backfill_complete,
            "last_stop_reason": last_collection.get("stop_reason"),
            "last_finished_at": last_collection.get("finished_at"),
        },
        "rolling": {
            "active_window": active_window,
            "window_begin": state.rolling_window_begin,
            "window_end": state.rolling_window_end,
            "cursor": _cursor_payload(
                state.rolling_cursor.code_index,
                state.rolling_cursor.page_no,
            ),
            "covered_through": state.rolling_covered_through,
            "lag_days": rolling_lag_days,
            "cycles_completed": state.rolling_cycles_completed,
            "last_cycle_complete": last_rolling.get("cycle_complete"),
            "last_stop_reason": last_rolling.get("stop_reason"),
            "last_finished_at": last_rolling.get("finished_at"),
        },
        "serving_index": {
            "pointer_present": pointer_present,
            "pointer_collection_cursor": (
                _cursor_payload(*pointer_cursor) if pointer_cursor is not None else None
            ),
            "historical_cursor_matches_pointer": serving_cursor_matches,
            "pending_object_count": len(state.pending_object_keys),
            "row_count": (
                serving_pointer.get("row_count")
                if isinstance(serving_pointer, Mapping)
                else None
            ),
            "last_sync_row_count": last_serving.get("row_count"),
            "last_sync_mode": last_serving.get("mode"),
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_live_report(*, require_serving_synced: bool) -> dict[str, Any]:
    settings = Settings()
    if not settings.r2_configured:
        return {
            "status": "fail",
            "phase": "configuration_error",
            "acceptance_status": "R2_NOT_CONFIGURED",
            "issue_157_acceptance": False,
            "errors": ["R2 repository secret set is incomplete"],
            "warnings": [],
        }

    state_store = R2OperationalStateStore.from_settings(settings)
    state_payload = state_store.read_json(STATE_NAME)
    if state_payload is None:
        return {
            "status": "fail",
            "phase": "state_missing",
            "acceptance_status": "PIPELINE_STATE_MISSING",
            "issue_157_acceptance": False,
            "errors": ["Track B daily pipeline state is missing"],
            "warnings": [],
        }

    try:
        state = TrackBPipelineState.from_payload(state_payload)
    except (TypeError, ValueError) as exc:
        return {
            "status": "fail",
            "phase": "state_invalid",
            "acceptance_status": "PIPELINE_STATE_INVALID",
            "issue_157_acceptance": False,
            "errors": [str(exc)],
            "warnings": [],
        }

    serving_pointer = state_store.read_json(SERVING_INDEX_STATE_NAME)
    return audit_transition(
        state,
        serving_pointer=serving_pointer,
        today=datetime.now(KST).date(),
        require_serving_synced=require_serving_synced,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Track B historical-to-rolling transition and serving-index readiness"
    )
    parser.add_argument(
        "--require-serving-synced",
        action="store_true",
        help="Fail when the serving pointer lags the collection cursor or pending raw objects remain.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_live_report(require_serving_synced=args.require_serving_synced)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
