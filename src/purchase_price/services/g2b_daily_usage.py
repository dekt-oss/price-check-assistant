"""Count the price-API calls the collectors spend per KST day and stop them below a cap.

The production app's live lookups use the same data.go.kr quota. On 2026-10-09 the collectors
spent the whole day's quota, so the app's live check failed for the rest of the day. Every
collection run now reads how many calls were already spent today, shrinks its budget to stay
under ``TRACK_B_DAILY_CALL_CAP`` (default 80,000 of the 100,000/day traffic), and records what it
used. Writers share one concurrency group, so a plain read-modify-write is safe.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

USAGE_STATE_NAME = "track-b/api-usage"
USAGE_STATE_SCHEMA = "track-b-api-usage-v1"
CAP_ENV = "TRACK_B_DAILY_CALL_CAP"
DEFAULT_DAILY_CAP = 80_000
KEEP_DAYS = 14
KST = ZoneInfo("Asia/Seoul")


def kst_today() -> date:
    return datetime.now(KST).date()


def daily_cap() -> int:
    try:
        value = int(str(os.getenv(CAP_ENV, "")).strip() or DEFAULT_DAILY_CAP)
    except ValueError:
        return DEFAULT_DAILY_CAP
    return max(value, 0)


def used_today(state_store, *, today: date | None = None) -> int:
    payload = state_store.read_json(USAGE_STATE_NAME) or {}
    days = payload.get("days") if payload.get("schema") == USAGE_STATE_SCHEMA else None
    return int((days or {}).get((today or kst_today()).isoformat()) or 0)


def remaining_today(state_store, *, cap: int | None = None, today: date | None = None) -> int:
    return max((daily_cap() if cap is None else cap) - used_today(state_store, today=today), 0)


def record_calls(state_store, calls: int, *, today: date | None = None) -> int:
    """Add ``calls`` to today's count and return the new total."""

    if calls <= 0:
        return used_today(state_store, today=today)
    day = (today or kst_today()).isoformat()
    payload = state_store.read_json(USAGE_STATE_NAME) or {}
    days = dict(payload.get("days") or {}) if payload.get("schema") == USAGE_STATE_SCHEMA else {}
    days[day] = int(days.get(day) or 0) + int(calls)
    kept = dict(sorted(days.items())[-KEEP_DAYS:])
    state_store.write_json(USAGE_STATE_NAME, {"schema": USAGE_STATE_SCHEMA, "days": kept})
    return kept[day]
