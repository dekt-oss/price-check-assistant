from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary

STATE_SCHEMA = "track-b-daily-pipeline-state-v1"
STATE_NAME = "track-b/daily-pipeline"
SNAPSHOT_STATE_NAME = "track-b/target-code-snapshot-20260913"
SERVING_INDEX_STATE_NAME = "track-b/serving-index"
EXPECTED_SNAPSHOT_SHA256 = "0885d82d25beaa60eb740bca538253ce67a51234c20acd7ba05e40da9674b365"
EXPECTED_TARGET_CODE_COUNT = 5208
BOOTSTRAP_CURSOR = CollectionCursor(code_index=3196, page_no=1)
ROLLING_BOOTSTRAP_CURSOR = CollectionCursor(code_index=0, page_no=1)
BOOTSTRAP_MIN_R2_OBJECTS = 3488
BOOTSTRAP_LAST_OBJECT_KEY = (
    "raw/v1/getSpcifyPrdlstPrcureInfoList-page/c8/38/"
    "c838061b4c87ee1eae263f1173fbfac262cb334bc70d61d3eeaa9302bc378d52.json.gz"
)
BACKFILL_BEGIN_DATE = "2025-09-12"
BACKFILL_END_DATE = "2026-09-11"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cursor_from_payload(
    payload: object,
    *,
    default: CollectionCursor | None = None,
    label: str,
) -> CollectionCursor:
    if payload is None and default is not None:
        return default
    if not isinstance(payload, Mapping):
        raise ValueError(f"Track B pipeline state {label} is missing")
    cursor = CollectionCursor(
        code_index=int(payload.get("code_index", -1)),
        page_no=int(payload.get("page_no", 0)),
    )
    if not 0 <= cursor.code_index <= EXPECTED_TARGET_CODE_COUNT or cursor.page_no < 1:
        raise ValueError(f"Track B pipeline state {label} is invalid")
    return cursor


def _validate_rolling_window(begin: str | None, end: str | None) -> None:
    if bool(begin) != bool(end):
        raise ValueError("Track B rolling window must contain both begin and end dates")
    if begin is None or end is None:
        return
    begin_date = date.fromisoformat(begin)
    end_date = date.fromisoformat(end)
    if begin_date > end_date:
        raise ValueError("Track B rolling window begin date is after end date")


def _validate_covered_through(value: str) -> str:
    covered = date.fromisoformat(value)
    historical_end = date.fromisoformat(BACKFILL_END_DATE)
    if covered < historical_end:
        raise ValueError("Track B rolling covered-through date cannot precede historical backfill")
    return value


@dataclass
class TrackBPipelineState:
    collection_cursor: CollectionCursor = BOOTSTRAP_CURSOR
    backfill_complete: bool = False
    rolling_cursor: CollectionCursor = ROLLING_BOOTSTRAP_CURSOR
    rolling_window_begin: str | None = None
    rolling_window_end: str | None = None
    rolling_covered_through: str = BACKFILL_END_DATE
    rolling_cycles_completed: int = 0
    pending_object_keys: list[str] = field(default_factory=list)
    db_bootstrap_complete: bool = False
    db_bootstrap_cursor: str | None = None
    updated_at: str = field(default_factory=_now)
    last_collection: dict[str, Any] | None = None
    last_rolling_collection: dict[str, Any] | None = None
    last_db_sync: dict[str, Any] | None = None
    last_serving_index_sync: dict[str, Any] | None = None

    @classmethod
    def bootstrap(cls) -> TrackBPipelineState:
        return cls()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> TrackBPipelineState:
        if payload.get("schema") != STATE_SCHEMA:
            raise ValueError("Track B pipeline state schema mismatch")
        if payload.get("snapshot_sha256") != EXPECTED_SNAPSHOT_SHA256:
            raise ValueError("Track B pipeline state snapshot hash mismatch")
        if payload.get("target_code_count") != EXPECTED_TARGET_CODE_COUNT:
            raise ValueError("Track B pipeline state target-code count mismatch")
        cursor = _cursor_from_payload(payload.get("collection_cursor"), label="collection cursor")
        rolling_cursor = _cursor_from_payload(
            payload.get("rolling_cursor"),
            default=ROLLING_BOOTSTRAP_CURSOR,
            label="rolling cursor",
        )
        rolling_window_begin = (
            str(payload["rolling_window_begin"])
            if payload.get("rolling_window_begin")
            else None
        )
        rolling_window_end = (
            str(payload["rolling_window_end"])
            if payload.get("rolling_window_end")
            else None
        )
        _validate_rolling_window(rolling_window_begin, rolling_window_end)
        rolling_covered_through = _validate_covered_through(
            str(payload.get("rolling_covered_through") or BACKFILL_END_DATE)
        )
        rolling_cycles_completed = int(payload.get("rolling_cycles_completed") or 0)
        if rolling_cycles_completed < 0:
            raise ValueError("Track B rolling cycle count cannot be negative")
        pending_raw = payload.get("pending_object_keys") or []
        if not isinstance(pending_raw, list) or not all(isinstance(v, str) for v in pending_raw):
            raise ValueError("Track B pipeline pending_object_keys must be a string list")
        pending = list(dict.fromkeys(pending_raw))
        return cls(
            collection_cursor=cursor,
            backfill_complete=bool(payload.get("backfill_complete")),
            rolling_cursor=rolling_cursor,
            rolling_window_begin=rolling_window_begin,
            rolling_window_end=rolling_window_end,
            rolling_covered_through=rolling_covered_through,
            rolling_cycles_completed=rolling_cycles_completed,
            pending_object_keys=pending,
            db_bootstrap_complete=bool(payload.get("db_bootstrap_complete")),
            db_bootstrap_cursor=(
                str(payload["db_bootstrap_cursor"])
                if payload.get("db_bootstrap_cursor")
                else None
            ),
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
            last_db_sync=(
                dict(payload["last_db_sync"])
                if isinstance(payload.get("last_db_sync"), Mapping)
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
            "schema": STATE_SCHEMA,
            "snapshot_sha256": EXPECTED_SNAPSHOT_SHA256,
            "target_code_count": EXPECTED_TARGET_CODE_COUNT,
            "backfill_begin_date": BACKFILL_BEGIN_DATE,
            "backfill_end_date": BACKFILL_END_DATE,
            "collection_cursor": {
                "code_index": self.collection_cursor.code_index,
                "page_no": self.collection_cursor.page_no,
            },
            "backfill_complete": self.backfill_complete,
            "rolling_cursor": {
                "code_index": self.rolling_cursor.code_index,
                "page_no": self.rolling_cursor.page_no,
            },
            "rolling_window_begin": self.rolling_window_begin,
            "rolling_window_end": self.rolling_window_end,
            "rolling_covered_through": self.rolling_covered_through,
            "rolling_cycles_completed": self.rolling_cycles_completed,
            "pending_object_keys": list(self.pending_object_keys),
            "db_bootstrap_complete": self.db_bootstrap_complete,
            "db_bootstrap_cursor": self.db_bootstrap_cursor,
            "updated_at": self.updated_at,
            "last_collection": self.last_collection,
            "last_rolling_collection": self.last_rolling_collection,
            "last_db_sync": self.last_db_sync,
            "last_serving_index_sync": self.last_serving_index_sync,
        }

    def _append_pending_keys(self, object_keys: list[str]) -> None:
        seen = set(self.pending_object_keys)
        for key in object_keys:
            if key not in seen:
                self.pending_object_keys.append(key)
                seen.add(key)

    def enqueue_pending_object_keys(self, object_keys: list[str]) -> None:
        """Queue externally collected Track B raw pages for the shared serving-index sync."""
        self._append_pending_keys(object_keys)
        self.updated_at = _now()

    def apply_collection(self, summary: CollectionSummary, *, object_keys: list[str]) -> None:
        if summary.target_code_snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
            raise ValueError("collector used an unexpected target-code snapshot")
        if summary.target_code_count != EXPECTED_TARGET_CODE_COUNT:
            raise ValueError("collector target-code count changed")
        self.collection_cursor = summary.next_cursor
        self._append_pending_keys(object_keys)
        self.backfill_complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor.code_index == EXPECTED_TARGET_CODE_COUNT
            and summary.next_cursor.page_no == 1
        )
        self.last_collection = {
            "status": summary.status,
            "finished_at": summary.finished_at,
            "start_cursor": {
                "code_index": summary.start_cursor.code_index,
                "page_no": summary.start_cursor.page_no,
            },
            "next_cursor": {
                "code_index": summary.next_cursor.code_index,
                "page_no": summary.next_cursor.page_no,
            },
            "track_b_requests": summary.track_b_requests,
            "pages_stored": summary.pages_stored,
            "rows_seen": summary.rows_seen,
            "objects_created": summary.r2_objects_created,
            "objects_reused": summary.r2_objects_reused,
            "stop_reason": summary.stop_reason,
            "error_type": summary.error_type,
            "error_message": summary.error_message,
            "pagination_reconciliations": summary.pagination_reconciliations,
            "pagination_contractions": summary.pagination_contractions,
            "pagination_inconsistencies": summary.pagination_inconsistencies,
            "last_pagination_event": summary.last_pagination_event,
        }
        self.updated_at = _now()

    def begin_rolling_cycle(self, *, begin: date, end: date) -> None:
        if not self.backfill_complete:
            raise ValueError("historical Track B backfill must complete before rolling collection")
        if begin > end:
            raise ValueError("rolling collection begin date must not be after end date")
        if self.rolling_window_begin is not None or self.rolling_window_end is not None:
            raise ValueError("Track B rolling collection cycle is already active")
        if self.rolling_cursor != ROLLING_BOOTSTRAP_CURSOR:
            raise ValueError("Track B rolling cursor must be at cycle start before opening a window")
        covered_through = date.fromisoformat(self.rolling_covered_through)
        if end <= covered_through:
            raise ValueError("rolling collection window must advance the covered-through date")
        self.rolling_window_begin = begin.isoformat()
        self.rolling_window_end = end.isoformat()
        self.updated_at = _now()

    def apply_rolling_collection(
        self,
        summary: CollectionSummary,
        *,
        object_keys: list[str],
    ) -> None:
        if not self.backfill_complete:
            raise ValueError("historical Track B backfill must remain complete in rolling mode")
        if summary.target_code_snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
            raise ValueError("rolling collector used an unexpected target-code snapshot")
        if summary.target_code_count != EXPECTED_TARGET_CODE_COUNT:
            raise ValueError("rolling collector target-code count changed")
        if (
            self.rolling_window_begin is None
            or self.rolling_window_end is None
            or summary.begin_date != self.rolling_window_begin
            or summary.end_date != self.rolling_window_end
        ):
            raise ValueError("rolling collector changed the active date window")

        self._append_pending_keys(object_keys)
        cycle_complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor.code_index == EXPECTED_TARGET_CODE_COUNT
            and summary.next_cursor.page_no == 1
        )
        if cycle_complete:
            current_covered = date.fromisoformat(self.rolling_covered_through)
            completed_end = date.fromisoformat(summary.end_date)
            if completed_end <= current_covered:
                raise ValueError("completed rolling cycle did not advance coverage")
            self.rolling_covered_through = summary.end_date
            self.rolling_cursor = ROLLING_BOOTSTRAP_CURSOR
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
            "start_cursor": {
                "code_index": summary.start_cursor.code_index,
                "page_no": summary.start_cursor.page_no,
            },
            "next_cursor": {
                "code_index": summary.next_cursor.code_index,
                "page_no": summary.next_cursor.page_no,
            },
            "cycle_complete": cycle_complete,
            "covered_through": self.rolling_covered_through,
            "track_b_requests": summary.track_b_requests,
            "pages_stored": summary.pages_stored,
            "rows_seen": summary.rows_seen,
            "objects_created": summary.r2_objects_created,
            "objects_reused": summary.r2_objects_reused,
            "stop_reason": summary.stop_reason,
            "error_type": summary.error_type,
            "error_message": summary.error_message,
            "pagination_reconciliations": summary.pagination_reconciliations,
            "pagination_contractions": summary.pagination_contractions,
            "pagination_inconsistencies": summary.pagination_inconsistencies,
            "last_pagination_event": summary.last_pagination_event,
        }
        self.updated_at = _now()

    def mark_db_bootstrap_progress(self, *, cursor: str | None, complete: bool) -> None:
        self.db_bootstrap_cursor = cursor
        self.db_bootstrap_complete = complete
        if complete:
            self.pending_object_keys.clear()
        self.updated_at = _now()

    def mark_pending_synced(self, object_keys: list[str], report: Mapping[str, Any]) -> None:
        completed = set(object_keys)
        self.pending_object_keys = [k for k in self.pending_object_keys if k not in completed]
        self.last_db_sync = dict(report)
        self.updated_at = _now()

    def mark_pending_indexed(self, object_keys: list[str], report: Mapping[str, Any]) -> None:
        completed = set(object_keys)
        self.pending_object_keys = [k for k in self.pending_object_keys if k not in completed]
        self.last_serving_index_sync = dict(report)
        self.updated_at = _now()
