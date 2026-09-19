from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_pipeline_state import BACKFILL_END_DATE

STATE_SCHEMA = "track-b-supplemental-state-v1"
STATE_NAME = "track-b/supplemental-verified-codes"
BOOTSTRAP_CURSOR = CollectionCursor(0, 1)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cursor_from_payload(payload: object, *, target_count: int, label: str) -> CollectionCursor:
    if not isinstance(payload, Mapping):
        raise ValueError(f"supplemental Track B {label} is missing")
    cursor = CollectionCursor(
        code_index=int(payload.get("code_index", -1)),
        page_no=int(payload.get("page_no", 0)),
    )
    if not 0 <= cursor.code_index <= target_count or cursor.page_no < 1:
        raise ValueError(f"supplemental Track B {label} is invalid")
    return cursor


def _validate_codes(codes: tuple[str, ...]) -> None:
    if len(codes) != len(set(codes)):
        raise ValueError("supplemental Track B target codes contain duplicates")
    for code in codes:
        if len(code) != 10 or not code.isdigit():
            raise ValueError(f"invalid supplemental Track B code: {code!r}")


@dataclass
class TrackBSupplementalState:
    target_codes: tuple[str, ...] = ()
    historical_cursor: CollectionCursor = BOOTSTRAP_CURSOR
    historical_complete: bool = False
    rolling_cursor: CollectionCursor = BOOTSTRAP_CURSOR
    rolling_window_begin: str | None = None
    rolling_window_end: str | None = None
    rolling_covered_through: str = BACKFILL_END_DATE
    rolling_cycles_completed: int = 0
    updated_at: str = field(default_factory=_now)
    last_collection: dict[str, Any] | None = None
    last_rolling_collection: dict[str, Any] | None = None

    @classmethod
    def bootstrap(cls, target_codes: tuple[str, ...]) -> TrackBSupplementalState:
        _validate_codes(target_codes)
        return cls(target_codes=target_codes)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> TrackBSupplementalState:
        if payload.get("schema") != STATE_SCHEMA:
            raise ValueError("supplemental Track B state schema mismatch")
        raw_codes = payload.get("target_codes")
        if not isinstance(raw_codes, list) or not all(isinstance(v, str) for v in raw_codes):
            raise ValueError("supplemental Track B target_codes must be a string list")
        target_codes = tuple(raw_codes)
        _validate_codes(target_codes)
        target_count = len(target_codes)
        begin = str(payload["rolling_window_begin"]) if payload.get("rolling_window_begin") else None
        end = str(payload["rolling_window_end"]) if payload.get("rolling_window_end") else None
        if bool(begin) != bool(end):
            raise ValueError("supplemental Track B rolling window is incomplete")
        if begin and end and date.fromisoformat(begin) > date.fromisoformat(end):
            raise ValueError("supplemental Track B rolling window is invalid")
        covered = str(payload.get("rolling_covered_through") or BACKFILL_END_DATE)
        if date.fromisoformat(covered) < date.fromisoformat(BACKFILL_END_DATE):
            raise ValueError("supplemental Track B covered-through predates historical endpoint")
        cycles = int(payload.get("rolling_cycles_completed") or 0)
        if cycles < 0:
            raise ValueError("supplemental Track B rolling cycle count cannot be negative")
        return cls(
            target_codes=target_codes,
            historical_cursor=_cursor_from_payload(
                payload.get("historical_cursor"),
                target_count=target_count,
                label="historical cursor",
            ),
            historical_complete=bool(payload.get("historical_complete")),
            rolling_cursor=_cursor_from_payload(
                payload.get("rolling_cursor"),
                target_count=target_count,
                label="rolling cursor",
            ),
            rolling_window_begin=begin,
            rolling_window_end=end,
            rolling_covered_through=covered,
            rolling_cycles_completed=cycles,
            updated_at=str(payload.get("updated_at") or _now()),
            last_collection=(
                dict(payload["last_collection"])
                if isinstance(payload.get("last_collection"), Mapping)
                else None
            ),
            last_rolling_collection=(
                dict(payload["last_rolling_collection"])
                if isinstance(payload.get("last_rolling_collection"), Mapping)
                else None
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "target_codes": list(self.target_codes),
            "historical_cursor": {
                "code_index": self.historical_cursor.code_index,
                "page_no": self.historical_cursor.page_no,
            },
            "historical_complete": self.historical_complete,
            "rolling_cursor": {
                "code_index": self.rolling_cursor.code_index,
                "page_no": self.rolling_cursor.page_no,
            },
            "rolling_window_begin": self.rolling_window_begin,
            "rolling_window_end": self.rolling_window_end,
            "rolling_covered_through": self.rolling_covered_through,
            "rolling_cycles_completed": self.rolling_cycles_completed,
            "updated_at": self.updated_at,
            "last_collection": self.last_collection,
            "last_rolling_collection": self.last_rolling_collection,
        }

    def reconcile_target_codes(self, current_codes: tuple[str, ...]) -> None:
        _validate_codes(current_codes)
        current = set(current_codes)
        removed = [code for code in self.target_codes if code not in current]
        if removed:
            raise ValueError(
                "supplemental Track B verified code removal requires explicit state migration: "
                + ", ".join(removed)
            )
        missing = tuple(code for code in current_codes if code not in self.target_codes)
        if not missing:
            return

        previous_count = len(self.target_codes)
        self.target_codes = (*self.target_codes, *missing)
        if self.historical_complete:
            self.historical_complete = False
            self.historical_cursor = CollectionCursor(previous_count, 1)

        # New codes must replay every rolling date after the common historical endpoint.
        # Resetting the small supplemental lane is safe because R2 raw storage is content-addressed.
        self.rolling_cursor = BOOTSTRAP_CURSOR
        self.rolling_window_begin = None
        self.rolling_window_end = None
        self.rolling_covered_through = BACKFILL_END_DATE
        self.rolling_cycles_completed = 0
        self.updated_at = _now()

    def _validate_summary(self, summary: CollectionSummary) -> None:
        if summary.target_code_source != "EXPLICIT_CODES":
            raise ValueError("supplemental Track B collector did not use explicit codes")
        if summary.target_code_snapshot_sha256 is not None:
            raise ValueError("supplemental Track B collector unexpectedly used a snapshot")
        if summary.target_code_count != len(self.target_codes):
            raise ValueError("supplemental Track B target-code count changed")

    def apply_historical_collection(self, summary: CollectionSummary) -> None:
        self._validate_summary(summary)
        self.historical_cursor = summary.next_cursor
        self.historical_complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor == CollectionCursor(len(self.target_codes), 1)
        )
        self.last_collection = {
            "status": summary.status,
            "finished_at": summary.finished_at,
            "next_cursor": {
                "code_index": summary.next_cursor.code_index,
                "page_no": summary.next_cursor.page_no,
            },
            "track_b_requests": summary.track_b_requests,
            "pages_stored": summary.pages_stored,
            "rows_seen": summary.rows_seen,
            "stop_reason": summary.stop_reason,
            "error_type": summary.error_type,
            "error_message": summary.error_message,
        }
        self.updated_at = _now()

    def begin_rolling_cycle(self, *, begin: date, end: date) -> None:
        if not self.historical_complete:
            raise ValueError("supplemental historical collection must complete before rolling")
        if begin > end:
            raise ValueError("supplemental rolling begin must not be after end")
        if self.rolling_window_begin is not None or self.rolling_window_end is not None:
            raise ValueError("supplemental rolling cycle is already active")
        if self.rolling_cursor != BOOTSTRAP_CURSOR:
            raise ValueError("supplemental rolling cursor must start at zero")
        if end <= date.fromisoformat(self.rolling_covered_through):
            raise ValueError("supplemental rolling window must advance coverage")
        self.rolling_window_begin = begin.isoformat()
        self.rolling_window_end = end.isoformat()
        self.updated_at = _now()

    def apply_rolling_collection(self, summary: CollectionSummary) -> None:
        self._validate_summary(summary)
        if not self.historical_complete:
            raise ValueError("supplemental historical collection is incomplete")
        if (
            self.rolling_window_begin is None
            or self.rolling_window_end is None
            or summary.begin_date != self.rolling_window_begin
            or summary.end_date != self.rolling_window_end
        ):
            raise ValueError("supplemental rolling collector changed the locked window")

        cycle_complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor == CollectionCursor(len(self.target_codes), 1)
        )
        if cycle_complete:
            self.rolling_covered_through = summary.end_date
            self.rolling_cursor = BOOTSTRAP_CURSOR
            self.rolling_window_begin = None
            self.rolling_window_end = None
            self.rolling_cycles_completed += 1
        else:
            self.rolling_cursor = summary.next_cursor

        self.last_rolling_collection = {
            "status": summary.status,
            "finished_at": summary.finished_at,
            "begin_date": summary.begin_date,
            "end_date": summary.end_date,
            "cycle_complete": cycle_complete,
            "track_b_requests": summary.track_b_requests,
            "pages_stored": summary.pages_stored,
            "rows_seen": summary.rows_seen,
            "stop_reason": summary.stop_reason,
            "error_type": summary.error_type,
            "error_message": summary.error_message,
        }
        self.updated_at = _now()
