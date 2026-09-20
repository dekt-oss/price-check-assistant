from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.scripts.collect_g2b_track_b_r2 import collect_track_b_batch
from purchase_price.services.track_b_pipeline_state import BACKFILL_BEGIN_DATE, BACKFILL_END_DATE
from purchase_price.services.track_b_supplemental_state import (
    SUPPLEMENTAL_STATE_NAME,
    SupplementalTrackBState,
)
from purchase_price.services.track_b_supplemental_targets import supplemental_verified_codes
from purchase_price.storage.r2 import R2RawEvidenceStore
from purchase_price.storage.r2_state import R2OperationalStateStore

KST = ZoneInfo("Asia/Seoul")
ROLLING_WINDOW_DAYS = 7


class ManifestingRawStore:
    def __init__(self, inner: R2RawEvidenceStore) -> None:
        self.inner = inner
        self.object_keys: list[str] = []

    def put_public_json(self, *, source_operation: str, payload: object):
        ref = self.inner.put_public_json(source_operation=source_operation, payload=payload)
        self.object_keys.append(ref.key)
        return ref


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _exit_code(summary) -> int:
    if summary.status in {"SUCCESS", "PARTIAL_SUCCESS"}:
        return 0
    if summary.stop_reason == "RATE_LIMIT_EXHAUSTED" and (
        summary.codes_completed > 0 or summary.pages_stored > 0
    ):
        return 0
    return 1


def _rolling_window(state: SupplementalTrackBState, *, today: date) -> tuple[date, date] | None:
    covered = date.fromisoformat(state.rolling_covered_through)
    if today <= covered:
        return None
    first_uncovered = covered + timedelta(days=1)
    recent_begin = today - timedelta(days=ROLLING_WINDOW_DAYS - 1)
    begin = min(recent_begin, first_uncovered) if recent_begin > first_uncovered else recent_begin
    if recent_begin > first_uncovered:
        begin = first_uncovered
    return begin, min(today, begin + timedelta(days=ROLLING_WINDOW_DAYS - 1))


def run(*, request_budget: int, output: Path) -> int:
    if request_budget < 1 or request_budget > 100:
        raise ValueError("supplemental request_budget must be between 1 and 100")

    codes = supplemental_verified_codes()
    if not codes:
        _write(output, {"status": "SUCCESS", "mode": "supplemental", "stop_reason": "NO_TARGETS"})
        return 0

    settings = get_settings()
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not shopping_key:
        raise RuntimeError("G2B shopping service key is not configured")

    state_store = R2OperationalStateStore.from_settings(settings)
    payload = state_store.read_json(SUPPLEMENTAL_STATE_NAME)
    state = (
        SupplementalTrackBState.from_payload(payload)
        if payload is not None
        else SupplementalTrackBState.bootstrap(codes)
    )
    state.reconcile_targets(codes)

    client = PublicDataPortalClient(
        shopping_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    store = ManifestingRawStore(R2RawEvidenceStore.from_settings(settings))
    segments = tuple(sorted({code[:2] for code in codes}))

    if not state.backfill_complete:
        begin = date.fromisoformat(BACKFILL_BEGIN_DATE)
        end = date.fromisoformat(BACKFILL_END_DATE)
        summary = collect_track_b_batch(
            catalog_client=client,
            shopping_client=client,
            store=store,
            catalog_base_url="unused-explicit-targets",
            shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            begin=begin,
            end=end,
            start_cursor=state.collection_cursor,
            request_budget=request_budget,
            segments=segments,
            explicit_target_codes=codes,
        )
        state.apply_historical(summary, object_keys=store.object_keys)
        state_store.write_json(SUPPLEMENTAL_STATE_NAME, state.to_payload())
        report = {
            **asdict(summary),
            "mode": "supplemental_historical",
            "target_codes": list(codes),
            "pending_object_count": len(state.pending_object_keys),
        }
        _write(output, report)
        return _exit_code(summary)

    if state.rolling_window_begin is None:
        planned = _rolling_window(state, today=datetime.now(KST).date())
        if planned is None:
            _write(
                output,
                {
                    "status": "SUCCESS",
                    "mode": "supplemental_rolling",
                    "stop_reason": "ROLLING_UP_TO_DATE",
                    "target_codes": list(codes),
                    "rolling_covered_through": state.rolling_covered_through,
                    "pending_object_count": len(state.pending_object_keys),
                },
            )
            return 0
        state.begin_rolling(begin=planned[0], end=planned[1])
        state_store.write_json(SUPPLEMENTAL_STATE_NAME, state.to_payload())

    if state.rolling_window_end is None:
        raise RuntimeError("supplemental rolling window state is incomplete")
    begin = date.fromisoformat(state.rolling_window_begin)
    end = date.fromisoformat(state.rolling_window_end)
    summary = collect_track_b_batch(
        catalog_client=client,
        shopping_client=client,
        store=store,
        catalog_base_url="unused-explicit-targets",
        shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        begin=begin,
        end=end,
        start_cursor=state.rolling_cursor,
        request_budget=request_budget,
        segments=segments,
        explicit_target_codes=codes,
    )
    state.apply_rolling(summary, object_keys=store.object_keys)
    state_store.write_json(SUPPLEMENTAL_STATE_NAME, state.to_payload())
    report = {
        **asdict(summary),
        "mode": "supplemental_rolling",
        "target_codes": list(codes),
        "rolling_covered_through": state.rolling_covered_through,
        "rolling_cycles_completed": state.rolling_cycles_completed,
        "pending_object_count": len(state.pending_object_keys),
    }
    _write(output, report)
    return _exit_code(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect verified supplemental Track B codes")
    parser.add_argument("--request-budget", type=int, default=50)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/track-b-supplemental/collection-summary.json"),
    )
    args = parser.parse_args()
    return run(request_budget=args.request_budget, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
