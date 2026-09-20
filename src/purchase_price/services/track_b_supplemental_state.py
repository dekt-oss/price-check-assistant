from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary
from purchase_price.services.track_b_pipeline_state import BACKFILL_BEGIN_DATE, BACKFILL_END_DATE

SUPPLEMENTAL_STATE_SCHEMA = "track-b-supplemental-state-v1"
SUPPLEMENTAL_STATE_NAME = "track-b/supplemental-pipeline"
SUPPLEMENTAL_ROLLING_CURSOR = CollectionCursor(0, 1)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def target_fingerprint(codes: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(codes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _cursor(payload: object, *, target_count: int, label: str) -> CollectionCursor:
    if not isinstance(payload, Mapping):
        raise ValueError(f"supplemental {label} is missing")
    value = CollectionCursor(
        code_index=int(payload.get("code_index", -1)),
        page_no=int(payload.get("page_no", 0)),
    )
    if not 0 <= value.code_index <= target_count or value.page_no < 1:
        raise ValueError(f"supplemental {label} is invalid")
    return value


@dataclass
class SupplementalTrackBState:
    target_codes: tuple[str, ...]
    collection_cursor: CollectionCursor = SUPPLEMENTAL_ROLLING_CURSOR
    backfill_complete: bool = False
    rolling_cursor: CollectionCursor = SUPPLEMENTAL_ROLLING_CURSOR
    rolling_window_begin: str | None = None
    rolling_window_end: str | None = None
    rolling_covered_through: str = BACKFILL_END_DATE
    rolling_cycles_completed: int = 0
    pending_object_keys: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)
    last_collection: dict[str, Any] | None = None

    @classmethod
    def bootstrap(cls, target_codes: tuple[str, ...]) -> SupplementalTrackBState:
        if not target_codes:
            raise ValueError("supplemental target set must not be empty")
        return cls(target_codes=target_codes)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SupplementalTrackBState:
        if payload.get("schema") != SUPPLEMENTAL_STATE_SCHEMA:
            raise ValueError("supplemental state schema mismatch")
        raw_codes = payload.get("target_codes")
        if not isinstance(raw_codes, list) or not all(isinstance(v, str) for v in raw_codes):
            raise ValueError("supplemental target_codes must be a string list")
        codes = tuple(raw_codes)
        if payload.get("target_fingerprint") != target_fingerprint(codes):
            raise ValueError("supplemental target fingerprint mismatch")
        cursor = _cursor(payload.get("collection_cursor"), target_count=len(codes), label="cursor")
        rolling = _cursor(
            payload.get("rolling_cursor"),
            target_count=len(codes),
            label="rolling cursor",
        )
        pending = payload.get("pending_object_keys") or []
        if not isinstance(pending, list) or not all(isinstance(v, str) for v in pending):
            raise ValueError("supplemental pending_object_keys must be a string list")
        return cls(
            target_codes=codes,
            collection_cursor=cursor,
            backfill_complete=bool(payload.get("backfill_complete")),
            rolling_cursor=rolling,
            rolling_window_begin=(
                str(payload["rolling_window_begin"]) if payload.get("rolling_window_begin") else None
            ),
            rolling_window_end=(
                str(payload["rolling_window_end"]) if payload.get("rolling_window_end") else None
            ),
            rolling_covered_through=str(
                payload.get("rolling_covered_through") or BACKFILL_END_DATE
            ),
            rolling_cycles_completed=int(payload.get("rolling_cycles_completed") or 0),
            pending_object_keys=list(dict.fromkeys(pending)),
            updated_at=str(payload.get("updated_at") or _now()),
            last_collection=(
                dict(payload["last_collection"])
                if isinstance(payload.get("last_collection"), Mapping)
                else None
            ),
        )

    def reconcile_targets(self, target_codes: tuple[str, ...]) -> None:
        if target_codes == self.target_codes:
            return
        if not self.backfill_complete:
            raise ValueError("supplemental target set changed during incomplete historical backfill")
        self.target_codes = target_codes
        self.collection_cursor = SUPPLEMENTAL_ROLLING_CURSOR
        self.backfill_complete = False
        self.rolling_cursor = SUPPLEMENTAL_ROLLING_CURSOR
        self.rolling_window_begin = None
        self.rolling_window_end = None
        self.rolling_covered_through = BACKFILL_END_DATE
        self.rolling_cycles_completed = 0
        self.updated_at = _now()

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": SUPPLEMENTAL_STATE_SCHEMA,
            "target_codes": list(self.target_codes),
            "target_fingerprint": target_fingerprint(self.target_codes),
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
            "updated_at": self.updated_at,
            "last_collection": self.last_collection,
        }

    def _append_pending(self, keys: list[str]) -> None:
        seen = set(self.pending_object_keys)
        for key in keys:
            if key not in seen:
                self.pending_object_keys.append(key)
                seen.add(key)

    def apply_historical(self, summary: CollectionSummary, *, object_keys: list[str]) -> None:
        if summary.target_code_source != "EXPLICIT_VERIFIED":
            raise ValueError("supplemental collector must use verified explicit targets")
        if summary.target_code_count != len(self.target_codes):
            raise ValueError("supplemental target count changed")
        self.collection_cursor = summary.next_cursor
        self._append_pending(object_keys)
        self.backfill_complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor.code_index == len(self.target_codes)
            and summary.next_cursor.page_no == 1
        )
        self.last_collection = {
            "mode": "historical_backfill",
            "status": summary.status,
            "finished_at": summary.finished_at,
            "rows_seen": summary.rows_seen,
            "pages_stored": summary.pages_stored,
            "track_b_requests": summary.track_b_requests,
            "stop_reason": summary.stop_reason,
        }
        self.updated_at = _now()

    def begin_rolling(self, *, begin: date, end: date) -> None:
        if not self.backfill_complete:
            raise ValueError("supplemental historical backfill is incomplete")
        if begin > end:
            raise ValueError("supplemental rolling begin is after end")
        self.rolling_window_begin = begin.isoformat()
        self.rolling_window_end = end.isoformat()
        self.updated_at = _now()

    def apply_rolling(self, summary: CollectionSummary, *, object_keys: list[str]) -> None:
        if self.rolling_window_begin is None or self.rolling_window_end is None:
            raise ValueError("supplemental rolling window is not locked")
        self._append_pending(object_keys)
        complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor.code_index == len(self.target_codes)
            and summary.next_cursor.page_no == 1
        )
        if complete:
            self.rolling_covered_through = self.rolling_window_end
            self.rolling_cursor = SUPPLEMENTAL_ROLLING_CURSOR
            self.rolling_window_begin = None
            self.rolling_window_end = None
            self.rolling_cycles_completed += 1
        else:
            self.rolling_cursor = summary.next_cursor
        self.last_collection = {
            "mode": "rolling_incremental",
            "status": summary.status,
            "finished_at": summary.finished_at,
            "rows_seen": summary.rows_seen,
            "pages_stored": summary.pages_stored,
            "track_b_requests": summary.track_b_requests,
            "stop_reason": summary.stop_reason,
        }
        self.updated_at = _now()

    def mark_pending_indexed(self, object_keys: list[str], report: Mapping[str, Any]) -> None:
        completed = set(object_keys)
        self.pending_object_keys = [key for key in self.pending_object_keys if key not in completed]
        self.updated_at = _now()
