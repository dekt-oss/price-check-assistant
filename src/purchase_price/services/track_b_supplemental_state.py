from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_pipeline_state import BACKFILL_END_DATE

SUPPLEMENTAL_STATE_SCHEMA = "track-b-supplemental-pipeline-state-v1"
SUPPLEMENTAL_STATE_NAME = "track-b/supplemental-pipeline"
SUPPLEMENTAL_BOOTSTRAP_CURSOR = CollectionCursor(code_index=0, page_no=1)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cursor_from_payload(payload: object) -> CollectionCursor:
    if not isinstance(payload, Mapping):
        raise ValueError("Track B supplemental cursor is missing")
    cursor = CollectionCursor(
        code_index=int(payload.get("code_index", -1)),
        page_no=int(payload.get("page_no", 0)),
    )
    if cursor.code_index < 0 or cursor.page_no < 1:
        raise ValueError("Track B supplemental cursor is invalid")
    return cursor


def _canonical_codes(raw: object, *, label: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise ValueError(f"Track B supplemental {label} must be a string list")
    codes = list(dict.fromkeys(value.strip() for value in raw if value.strip()))
    if any(len(code) != 10 or not code.isdigit() for code in codes):
        raise ValueError(f"Track B supplemental {label} contains an invalid detail code")
    if codes != sorted(codes):
        raise ValueError(f"Track B supplemental {label} must be sorted")
    return codes


@dataclass
class TrackBSupplementalState:
    historical_completed_codes: list[str] = field(default_factory=list)
    active_mode: str | None = None
    active_codes: list[str] = field(default_factory=list)
    cursor: CollectionCursor = SUPPLEMENTAL_BOOTSTRAP_CURSOR
    rolling_window_begin: str | None = None
    rolling_window_end: str | None = None
    rolling_covered_through: str = BACKFILL_END_DATE
    rolling_cycles_completed: int = 0
    pending_object_keys: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)
    last_collection: dict[str, Any] | None = None
    last_serving_index_sync: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> TrackBSupplementalState:
        if payload.get("schema") != SUPPLEMENTAL_STATE_SCHEMA:
            raise ValueError("Track B supplemental state schema mismatch")
        active_mode = str(payload.get("active_mode") or "").strip() or None
        if active_mode not in {None, "historical", "rolling"}:
            raise ValueError("Track B supplemental active_mode is invalid")
        completed = _canonical_codes(
            payload.get("historical_completed_codes"),
            label="historical_completed_codes",
        )
        active_codes = _canonical_codes(payload.get("active_codes"), label="active_codes")
        cursor = _cursor_from_payload(
            payload.get("cursor") or {"code_index": 0, "page_no": 1}
        )
        if active_codes and cursor.code_index > len(active_codes):
            raise ValueError("Track B supplemental cursor exceeds active target count")
        if not active_codes and cursor != SUPPLEMENTAL_BOOTSTRAP_CURSOR:
            raise ValueError("Track B supplemental idle state must use bootstrap cursor")
        if bool(active_codes) != bool(active_mode):
            raise ValueError("Track B supplemental active mode/codes are inconsistent")

        begin = str(payload.get("rolling_window_begin") or "").strip() or None
        end = str(payload.get("rolling_window_end") or "").strip() or None
        if bool(begin) != bool(end):
            raise ValueError("Track B supplemental rolling window is incomplete")
        if active_mode == "rolling" and (begin is None or end is None):
            raise ValueError("Track B supplemental rolling mode requires a locked window")
        if active_mode != "rolling" and (begin is not None or end is not None):
            raise ValueError("Track B supplemental rolling window requires rolling mode")
        if begin is not None and date.fromisoformat(begin) > date.fromisoformat(end or begin):
            raise ValueError("Track B supplemental rolling window begin is after end")

        covered = str(payload.get("rolling_covered_through") or BACKFILL_END_DATE)
        if date.fromisoformat(covered) < date.fromisoformat(BACKFILL_END_DATE):
            raise ValueError("Track B supplemental covered-through precedes historical end")
        cycles = int(payload.get("rolling_cycles_completed") or 0)
        if cycles < 0:
            raise ValueError("Track B supplemental rolling cycle count cannot be negative")
        pending = _canonical_codes(payload.get("pending_object_keys"), label="pending_object_keys") if False else None
        pending_raw = payload.get("pending_object_keys") or []
        if not isinstance(pending_raw, list) or not all(isinstance(v, str) for v in pending_raw):
            raise ValueError("Track B supplemental pending_object_keys must be a string list")

        return cls(
            historical_completed_codes=completed,
            active_mode=active_mode,
            active_codes=active_codes,
            cursor=cursor,
            rolling_window_begin=begin,
            rolling_window_end=end,
            rolling_covered_through=covered,
            rolling_cycles_completed=cycles,
            pending_object_keys=list(dict.fromkeys(pending_raw)),
            updated_at=str(payload.get("updated_at") or _now()),
            last_collection=(
                dict(payload["last_collection"])
                if isinstance(payload.get("last_collection"), Mapping)
                else None
            ),
            last_serving_index_sync=(
                dict(payload["last_serving_index_sync"])
                if isinstance(payload.get("last_serving_index_sync"), Mapping)
                else None
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": SUPPLEMENTAL_STATE_SCHEMA,
            "historical_completed_codes": list(self.historical_completed_codes),
            "active_mode": self.active_mode,
            "active_codes": list(self.active_codes),
            "cursor": {
                "code_index": self.cursor.code_index,
                "page_no": self.cursor.page_no,
            },
            "rolling_window_begin": self.rolling_window_begin,
            "rolling_window_end": self.rolling_window_end,
            "rolling_covered_through": self.rolling_covered_through,
            "rolling_cycles_completed": self.rolling_cycles_completed,
            "pending_object_keys": list(self.pending_object_keys),
            "updated_at": self.updated_at,
            "last_collection": self.last_collection,
            "last_serving_index_sync": self.last_serving_index_sync,
        }

    def missing_historical_codes(self, current_codes: tuple[str, ...]) -> tuple[str, ...]:
        completed = set(self.historical_completed_codes)
        return tuple(code for code in current_codes if code not in completed)

    def begin_historical(self, codes: tuple[str, ...]) -> None:
        if self.active_mode is not None:
            raise RuntimeError("Track B supplemental collection is already active")
        if not codes:
            raise ValueError("Track B supplemental historical target set is empty")
        self.active_mode = "historical"
        self.active_codes = list(codes)
        self.cursor = SUPPLEMENTAL_BOOTSTRAP_CURSOR
        self.updated_at = _now()

    def begin_rolling(self, codes: tuple[str, ...], *, begin: date, end: date) -> None:
        if self.active_mode is not None:
            raise RuntimeError("Track B supplemental collection is already active")
        if not codes:
            raise ValueError("Track B supplemental rolling target set is empty")
        if begin > end:
            raise ValueError("Track B supplemental rolling begin is after end")
        self.active_mode = "rolling"
        self.active_codes = list(codes)
        self.cursor = SUPPLEMENTAL_BOOTSTRAP_CURSOR
        self.rolling_window_begin = begin.isoformat()
        self.rolling_window_end = end.isoformat()
        self.updated_at = _now()

    def apply_collection(
        self,
        summary: CollectionSummary,
        *,
        object_keys: list[str],
    ) -> None:
        if self.active_mode is None or not self.active_codes:
            raise RuntimeError("Track B supplemental collection has no active target set")
        if summary.target_code_count != len(self.active_codes):
            raise ValueError("Track B supplemental summary target count changed during a locked cycle")
        if tuple(summary.target_segments) != tuple(sorted({code[:2] for code in self.active_codes})):
            raise ValueError("Track B supplemental summary segments changed during a locked cycle")

        for key in object_keys:
            if key not in self.pending_object_keys:
                self.pending_object_keys.append(key)

        cycle_complete = (
            summary.status == "SUCCESS"
            and summary.next_cursor.code_index >= len(self.active_codes)
        )
        mode = self.active_mode
        if cycle_complete:
            if mode == "historical":
                self.historical_completed_codes = sorted(
                    set(self.historical_completed_codes).union(self.active_codes)
                )
            else:
                assert self.rolling_window_end is not None
                self.rolling_covered_through = self.rolling_window_end
                self.rolling_cycles_completed += 1
            self.active_mode = None
            self.active_codes = []
            self.cursor = SUPPLEMENTAL_BOOTSTRAP_CURSOR
            self.rolling_window_begin = None
            self.rolling_window_end = None
        else:
            self.cursor = summary.next_cursor

        self.last_collection = {
            "mode": mode,
            "status": summary.status,
            "finished_at": summary.finished_at,
            "begin_date": summary.begin_date,
            "end_date": summary.end_date,
            "start_cursor": {
                "code_index": summary.start_cursor.code_index,
                "page_no": summary.start_cursor.page_no,
            },
            "next_cursor": {
                "code_index": summary.next_cursor.code_index,
                "page_no": summary.next_cursor.page_no,
            },
            "target_codes": list(self.active_codes) if not cycle_complete else [],
            "cycle_complete": cycle_complete,
            "track_b_requests": summary.track_b_requests,
            "pages_stored": summary.pages_stored,
            "rows_seen": summary.rows_seen,
            "stop_reason": summary.stop_reason,
            "error_type": summary.error_type,
            "error_message": summary.error_message,
        }
        self.updated_at = _now()

    def mark_pending_indexed(self, object_keys: list[str], report: Mapping[str, Any]) -> None:
        completed = set(object_keys)
        self.pending_object_keys = [
            key for key in self.pending_object_keys if key not in completed
        ]
        self.last_serving_index_sync = dict(report)
        self.updated_at = _now()
