"""Resumable state for collecting Track B trades older than the first one-year backfill.

The base pipeline covers 2025-09-12 onward. This collector walks back to 2021-01-01 in windows of
at most one year (the API rejects longer ranges). The price API answers one 10-digit category code
per request and data.go.kr allows about 1,000 requests a day, so the order matters more than the
total: every window is collected for the medical and laboratory categories that traded last year
first, then the other categories that traded, and only then the categories with no trade at all.

The tiers are frozen in the state (with a fingerprint) when the collector first runs, so a later
change to the serving index cannot reshuffle a half-collected pass.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor, CollectionSummary

HISTORY_STATE_SCHEMA = "track-b-history-state-v1"
HISTORY_STATE_NAME = "track-b/history-backfill"
HISTORY_START_CURSOR = CollectionCursor(0, 1)

# Newest first: the most recent missing year is the most useful for price comparison.
HISTORY_WINDOWS: tuple[tuple[str, str], ...] = (
    ("2024-09-12", "2025-09-11"),
    ("2023-09-12", "2024-09-11"),
    ("2022-09-12", "2023-09-11"),
    ("2021-09-12", "2022-09-11"),
    ("2021-01-01", "2021-09-11"),
)
PRIORITY_SEGMENTS = ("42", "41")  # 의료·실험/측정 장비
TIER_NAMES = ("hospital_active", "other_active", "no_recent_trade")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def build_tiers(
    snapshot_codes: Iterable[str],
    active_codes: Iterable[str],
) -> dict[str, tuple[str, ...]]:
    """Split the validated target codes into the three collection tiers, keeping snapshot order."""

    active = set(active_codes)
    tiers: dict[str, list[str]] = {name: [] for name in TIER_NAMES}
    for code in dict.fromkeys(snapshot_codes):
        if code not in active:
            tiers["no_recent_trade"].append(code)
        elif code[:2] in PRIORITY_SEGMENTS:
            tiers["hospital_active"].append(code)
        else:
            tiers["other_active"].append(code)
    return {name: tuple(codes) for name, codes in tiers.items() if codes}


def tiers_fingerprint(tiers: Mapping[str, tuple[str, ...]]) -> str:
    encoded = json.dumps(
        {name: list(codes) for name, codes in tiers.items()},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def history_passes(tiers: Mapping[str, tuple[str, ...]]) -> tuple[tuple[str, str, str], ...]:
    """(tier, begin, end) in collection order: each tier through every window, best tier first."""

    return tuple(
        (name, begin, end)
        for name in TIER_NAMES
        if tiers.get(name)
        for begin, end in HISTORY_WINDOWS
    )


@dataclass
class TrackBHistoryState:
    tiers: dict[str, tuple[str, ...]]
    pass_index: int = 0
    cursor: CollectionCursor = HISTORY_START_CURSOR
    pending_object_keys: list[str] = field(default_factory=list)
    requests_total: int = 0
    rows_total: int = 0
    updated_at: str = field(default_factory=_now)
    last_collection: dict[str, Any] | None = None

    @classmethod
    def bootstrap(cls, tiers: Mapping[str, tuple[str, ...]]) -> TrackBHistoryState:
        if not any(tiers.values()):
            raise ValueError("history target tiers must not be empty")
        unknown = set(tiers) - set(TIER_NAMES)
        if unknown:
            raise ValueError(f"unknown history tiers: {sorted(unknown)}")
        return cls(tiers={name: tuple(codes) for name, codes in tiers.items()})

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> TrackBHistoryState:
        if payload.get("schema") != HISTORY_STATE_SCHEMA:
            raise ValueError("Track B history state schema mismatch")
        raw_tiers = payload.get("tiers")
        if not isinstance(raw_tiers, Mapping):
            raise ValueError("Track B history tiers are missing")
        tiers = {str(name): tuple(str(code) for code in codes) for name, codes in raw_tiers.items()}
        if payload.get("tiers_fingerprint") != tiers_fingerprint(tiers):
            raise ValueError("Track B history tiers fingerprint mismatch")
        state = cls.bootstrap(tiers)
        passes = history_passes(state.tiers)
        state.pass_index = int(payload.get("pass_index") or 0)
        if not 0 <= state.pass_index <= len(passes):
            raise ValueError("Track B history pass index is invalid")
        cursor = payload.get("cursor") or {}
        state.cursor = CollectionCursor(
            code_index=int(cursor.get("code_index", 0)),
            page_no=int(cursor.get("page_no", 1)),
        )
        if state.cursor.code_index < 0 or state.cursor.page_no < 1:
            raise ValueError("Track B history cursor is invalid")
        if not state.complete and state.cursor.code_index > len(state.current_codes):
            raise ValueError("Track B history cursor is past the current tier")
        pending = payload.get("pending_object_keys") or []
        if not isinstance(pending, list) or not all(isinstance(key, str) for key in pending):
            raise ValueError("Track B history pending_object_keys must be a string list")
        state.pending_object_keys = list(dict.fromkeys(pending))
        state.requests_total = int(payload.get("requests_total") or 0)
        state.rows_total = int(payload.get("rows_total") or 0)
        state.updated_at = str(payload.get("updated_at") or _now())
        last = payload.get("last_collection")
        state.last_collection = dict(last) if isinstance(last, Mapping) else None
        return state

    @property
    def passes(self) -> tuple[tuple[str, str, str], ...]:
        return history_passes(self.tiers)

    @property
    def complete(self) -> bool:
        return self.pass_index >= len(self.passes)

    @property
    def current_pass(self) -> tuple[str, str, str]:
        if self.complete:
            raise ValueError("Track B history collection is complete")
        return self.passes[self.pass_index]

    @property
    def current_codes(self) -> tuple[str, ...]:
        return self.tiers[self.current_pass[0]]

    def progress(self) -> dict[str, Any]:
        """Codes done across every pass, for the run summary and the screen."""

        passes = self.passes
        total = sum(len(self.tiers[name]) for name, _begin, _end in passes)
        done = sum(len(self.tiers[name]) for name, _begin, _end in passes[: self.pass_index])
        if not self.complete:
            done += min(self.cursor.code_index, len(self.current_codes))
        return {
            "passes_total": len(passes),
            "passes_done": min(self.pass_index, len(passes)),
            "code_windows_total": total,
            "code_windows_done": done,
            "percent": round(done / total * 100, 1) if total else 100.0,
            "oldest_window_complete": (
                passes[self.pass_index - 1][1] if self.pass_index else None
            ),
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": HISTORY_STATE_SCHEMA,
            "windows": [list(window) for window in HISTORY_WINDOWS],
            "tiers": {name: list(codes) for name, codes in self.tiers.items()},
            "tiers_fingerprint": tiers_fingerprint(self.tiers),
            "tier_sizes": {name: len(codes) for name, codes in self.tiers.items()},
            "pass_index": self.pass_index,
            "current_pass": None if self.complete else list(self.current_pass),
            "cursor": {"code_index": self.cursor.code_index, "page_no": self.cursor.page_no},
            "complete": self.complete,
            "progress": self.progress(),
            "pending_object_keys": list(self.pending_object_keys),
            "requests_total": self.requests_total,
            "rows_total": self.rows_total,
            "updated_at": self.updated_at,
            "last_collection": self.last_collection,
        }

    def apply_collection(self, summary: CollectionSummary, *, object_keys: list[str]) -> None:
        tier, begin, end = self.current_pass
        if summary.begin_date != begin or summary.end_date != end:
            raise ValueError("history collector changed the active date window")
        if summary.target_code_count != len(self.current_codes):
            raise ValueError("history collector used a different code list")
        seen = set(self.pending_object_keys)
        for key in object_keys:
            if key not in seen:
                self.pending_object_keys.append(key)
                seen.add(key)
        self.requests_total += int(summary.track_b_requests or 0)
        self.rows_total += int(summary.rows_seen or 0)
        pass_complete = (
            summary.stop_reason == "TARGET_COMPLETE"
            and summary.next_cursor.code_index == len(self.current_codes)
            and summary.next_cursor.page_no == 1
        )
        if pass_complete:
            self.pass_index += 1
            self.cursor = HISTORY_START_CURSOR
        else:
            self.cursor = summary.next_cursor
        self.last_collection = {
            "tier": tier,
            "begin_date": begin,
            "end_date": end,
            "status": summary.status,
            "finished_at": summary.finished_at,
            "pass_complete": pass_complete,
            "track_b_requests": summary.track_b_requests,
            "pages_stored": summary.pages_stored,
            "rows_seen": summary.rows_seen,
            "stop_reason": summary.stop_reason,
            "error_type": summary.error_type,
            "error_message": summary.error_message,
        }
        self.updated_at = _now()

    def mark_pending_indexed(self, object_keys: list[str]) -> None:
        completed = set(object_keys)
        self.pending_object_keys = [key for key in self.pending_object_keys if key not in completed]
        self.updated_at = _now()
