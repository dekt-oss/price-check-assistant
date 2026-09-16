from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary

STATE_SCHEMA = "track-b-daily-pipeline-state-v1"
STATE_NAME = "track-b/daily-pipeline"
SNAPSHOT_STATE_NAME = "track-b/target-code-snapshot-20260913"
EXPECTED_SNAPSHOT_SHA256 = "0885d82d25beaa60eb740bca538253ce67a51234c20acd7ba05e40da9674b365"
EXPECTED_TARGET_CODE_COUNT = 5208
BOOTSTRAP_CURSOR = CollectionCursor(code_index=3196, page_no=1)
BOOTSTRAP_MIN_R2_OBJECTS = 3488
BOOTSTRAP_LAST_OBJECT_KEY = (
    "raw/v1/getSpcifyPrdlstPrcureInfoList-page/c8/38/"
    "c838061b4c87ee1eae263f1173fbfac262cb334bc70d61d3eeaa9302bc378d52.json.gz"
)
BACKFILL_BEGIN_DATE = "2025-09-12"
BACKFILL_END_DATE = "2026-09-11"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TrackBPipelineState:
    collection_cursor: CollectionCursor = BOOTSTRAP_CURSOR
    backfill_complete: bool = False
    pending_object_keys: list[str] = field(default_factory=list)
    db_bootstrap_complete: bool = False
    db_bootstrap_cursor: str | None = None
    updated_at: str = field(default_factory=_now)
    last_collection: dict[str, Any] | None = None
    last_db_sync: dict[str, Any] | None = None

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
        cursor_raw = payload.get("collection_cursor")
        if not isinstance(cursor_raw, Mapping):
            raise ValueError("Track B pipeline state collection cursor is missing")
        cursor = CollectionCursor(
            code_index=int(cursor_raw.get("code_index", -1)),
            page_no=int(cursor_raw.get("page_no", 0)),
        )
        if not 0 <= cursor.code_index <= EXPECTED_TARGET_CODE_COUNT or cursor.page_no < 1:
            raise ValueError("Track B pipeline state collection cursor is invalid")
        pending_raw = payload.get("pending_object_keys") or []
        if not isinstance(pending_raw, list) or not all(isinstance(v, str) for v in pending_raw):
            raise ValueError("Track B pipeline pending_object_keys must be a string list")
        pending = list(dict.fromkeys(pending_raw))
        return cls(
            collection_cursor=cursor,
            backfill_complete=bool(payload.get("backfill_complete")),
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
            last_db_sync=(
                dict(payload["last_db_sync"])
                if isinstance(payload.get("last_db_sync"), Mapping)
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
            "pending_object_keys": list(self.pending_object_keys),
            "db_bootstrap_complete": self.db_bootstrap_complete,
            "db_bootstrap_cursor": self.db_bootstrap_cursor,
            "updated_at": self.updated_at,
            "last_collection": self.last_collection,
            "last_db_sync": self.last_db_sync,
        }

    def apply_collection(self, summary: CollectionSummary, *, object_keys: list[str]) -> None:
        if summary.target_code_snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
            raise ValueError("collector used an unexpected target-code snapshot")
        if summary.target_code_count != EXPECTED_TARGET_CODE_COUNT:
            raise ValueError("collector target-code count changed")
        self.collection_cursor = summary.next_cursor
        seen = set(self.pending_object_keys)
        for key in object_keys:
            if key not in seen:
                self.pending_object_keys.append(key)
                seen.add(key)
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
