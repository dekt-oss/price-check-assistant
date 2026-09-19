from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from purchase_price.config import get_settings
from purchase_price.scripts.collect_g2b_track_b_r2 import (
    TARGET_SEGMENTS,
    collect_track_b_batch,
)
from purchase_price.scripts.run_g2b_track_b_daily import (
    ManifestingRawStore,
    _collection_clients,
    _exit_code_for_collection,
)
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.services.g2b_product_mapping import load_g2b_product_mappings
from purchase_price.services.track_b_pipeline_state import (
    BACKFILL_BEGIN_DATE,
    BACKFILL_END_DATE,
    STATE_NAME as BASE_STATE_NAME,
    TrackBPipelineState,
)
from purchase_price.services.track_b_supplemental_state import (
    STATE_NAME,
    TrackBSupplementalState,
)
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_state import R2OperationalStateStore

KST = ZoneInfo("Asia/Seoul")
ROLLING_WINDOW_DAYS = 7


def _kst_today() -> date:
    return datetime.now(KST).date()


def verified_supplemental_codes() -> tuple[str, ...]:
    base_segments = set(TARGET_SEGMENTS)
    codes = {
        mapping.detail_product_code
        for mapping in load_g2b_product_mappings()
        if mapping.verified
        and mapping.detail_product_code
        and mapping.detail_product_code[:2] not in base_segments
    }
    resolved = tuple(sorted(str(code) for code in codes))
    for code in resolved:
        if len(code) != 10 or not code.isdigit():
            raise ValueError(f"verified supplemental code is invalid: {code!r}")
    return resolved


def _segments_for_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(code[:2] for code in codes))


def _next_rolling_window(
    state: TrackBSupplementalState,
    *,
    today: date,
) -> tuple[date, date, str] | None:
    covered_through = date.fromisoformat(state.rolling_covered_through)
    if today < covered_through:
        raise RuntimeError("supplemental collection date precedes covered-through state")
    if today == covered_through:
        return None
    recent_begin = today - timedelta(days=ROLLING_WINDOW_DAYS - 1)
    first_uncovered = covered_through + timedelta(days=1)
    if recent_begin > first_uncovered:
        begin = first_uncovered
        end = min(today, begin + timedelta(days=ROLLING_WINDOW_DAYS - 1))
        return begin, end, "catch_up"
    return recent_begin, today, "recent_overlap"


def _write_summary(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def run_supplemental(*, request_budget: int, summary_path: Path) -> int:
    if request_budget < 1 or request_budget > 100:
        raise ValueError("supplemental request_budget must be between 1 and 100")

    settings = get_settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not catalog_key or not shopping_key:
        raise RuntimeError("G2B catalog/shopping service keys are not configured")

    state_store = R2OperationalStateStore.from_settings(settings)
    base_payload = state_store.read_json(BASE_STATE_NAME)
    if base_payload is None:
        raise RuntimeError("base Track B pipeline state is missing")
    base_state = TrackBPipelineState.from_payload(base_payload)

    codes = verified_supplemental_codes()
    if not codes:
        _write_summary(
            summary_path,
            {
                "status": "SUCCESS",
                "mode": "supplemental",
                "stop_reason": "NO_VERIFIED_SUPPLEMENTAL_CODES",
                "target_codes": [],
                "track_b_requests": 0,
            },
        )
        return 0

    if not base_state.backfill_complete:
        _write_summary(
            summary_path,
            {
                "status": "SUCCESS",
                "mode": "supplemental",
                "stop_reason": "BASE_HISTORICAL_IN_PROGRESS",
                "target_codes": list(codes),
                "base_cursor": {
                    "code_index": base_state.collection_cursor.code_index,
                    "page_no": base_state.collection_cursor.page_no,
                },
                "track_b_requests": 0,
            },
        )
        return 0

    payload = state_store.read_json(STATE_NAME)
    state = (
        TrackBSupplementalState.from_payload(payload)
        if payload is not None
        else TrackBSupplementalState.bootstrap(codes)
    )
    state.reconcile_target_codes(codes)
    # Persist target reconciliation before any remote call.
    state_store.write_json(STATE_NAME, state.to_payload())

    catalog_client, shopping_client = _collection_clients(
        settings,
        catalog_key=catalog_key,
        shopping_key=shopping_key,
    )
    manifesting_store = ManifestingRawStore(R2RawEvidenceStore.from_settings(settings))
    segments = _segments_for_codes(state.target_codes)

    mode = "supplemental_historical"
    window_strategy: str | None = None
    if not state.historical_complete:
        begin = date.fromisoformat(BACKFILL_BEGIN_DATE)
        end = date.fromisoformat(BACKFILL_END_DATE)
        start_cursor = state.historical_cursor
    else:
        mode = "supplemental_rolling"
        if state.rolling_window_begin is None:
            planned = _next_rolling_window(state, today=_kst_today())
            if planned is None:
                _write_summary(
                    summary_path,
                    {
                        "status": "SUCCESS",
                        "mode": mode,
                        "stop_reason": "ROLLING_UP_TO_DATE",
                        "target_codes": list(state.target_codes),
                        "rolling_covered_through": state.rolling_covered_through,
                        "track_b_requests": 0,
                    },
                )
                return 0
            begin, end, window_strategy = planned
            state.begin_rolling_cycle(begin=begin, end=end)
            state_store.write_json(STATE_NAME, state.to_payload())
        else:
            if state.rolling_window_end is None:
                raise RuntimeError("supplemental rolling window state is incomplete")
            begin = date.fromisoformat(state.rolling_window_begin)
            end = date.fromisoformat(state.rolling_window_end)
            window_strategy = "resume_locked"
        start_cursor = state.rolling_cursor

    summary = collect_track_b_batch(
        catalog_client=catalog_client,
        shopping_client=shopping_client,
        store=manifesting_store,
        catalog_base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
        shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        begin=begin,
        end=end,
        start_cursor=start_cursor,
        request_budget=request_budget,
        segments=segments,
        explicit_target_codes=state.target_codes,
    )

    if mode == "supplemental_historical":
        state.apply_historical_collection(summary)
    else:
        state.apply_rolling_collection(summary)

    # The shared serving-index sync consumes only the base pending queue. Commit raw keys there
    # before advancing supplemental state; a retry can safely replay content-addressed raw pages.
    base_state.enqueue_pending_object_keys(manifesting_store.object_keys)
    state_store.write_json(BASE_STATE_NAME, base_state.to_payload())
    state_store.write_json(STATE_NAME, state.to_payload())

    report = {
        **asdict(summary),
        "mode": mode,
        "target_codes": list(state.target_codes),
        "base_pending_object_count": len(base_state.pending_object_keys),
        "supplemental_historical_complete": state.historical_complete,
        "rolling_covered_through": state.rolling_covered_through,
        "rolling_cycles_completed": state.rolling_cycles_completed,
    }
    if window_strategy is not None:
        report["rolling_window_strategy"] = window_strategy
    _write_summary(summary_path, report)
    return _exit_code_for_collection(summary)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect verified Track B detail codes outside the base segment snapshot"
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
