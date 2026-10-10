"""NAVER news-search calls per KST day for the News Radar collector, and its chain switch.

The collector runs a pass every 10 minutes (27 keywords = 27 calls, plus a retry per NAVER 429),
about 3,900 calls a day. NAVER counts search calls per application per day and resets at 00:00
KST (Developers Center: 25,000 a day; API HUB: per-day limit set in the console, free for now
but metered once it turns paid). The collector records every call it makes in a small JSON state,
skips a pass that would cross ``NEWS_RADAR_DAILY_CALL_CAP`` (default 5,000: normal use is about
3,888 a day, so this leaves room for 429 retries and the page's own "새 기사 확인" button while
keeping a possible per-call bill small) and the self-chaining stops when the next loop would
cross it.

``NEWS_RADAR_CHAIN=off`` (a repository variable) turns the chain off: each trigger then runs a
single pass and starts nothing, as before 2026-10-10.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

USAGE_STATE_NAME = "news-radar/naver-usage"
USAGE_STATE_SCHEMA = "news-radar-naver-usage-v1"
CAP_ENV = "NEWS_RADAR_DAILY_CALL_CAP"
CHAIN_ENV = "NEWS_RADAR_CHAIN"
DEFAULT_DAILY_CAP = 5_000
KEEP_DAYS = 14
KST = ZoneInfo("Asia/Seoul")
_OFF_WORDS = frozenset({"off", "false", "0", "no", "stop", "disabled"})


class JsonState(Protocol):
    def read_json(self, name: str) -> dict[str, Any] | None: ...

    def write_json(self, name: str, payload: dict[str, Any]) -> object: ...


class LocalJsonState:
    """File-backed state for local runs (``--output``); one JSON file per state name."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, name: str) -> Path:
        return self.directory / (name.replace("/", "__") + ".json")

    def read_json(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, name: str, payload: dict[str, Any]) -> str:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return str(path)


def kst_today(now: datetime | None = None) -> date:
    return (now or datetime.now(KST)).astimezone(KST).date()


def chain_enabled(value: str | None = None) -> bool:
    raw = os.getenv(CHAIN_ENV, "") if value is None else value
    return str(raw).strip().casefold() not in _OFF_WORDS


def daily_cap(value: str | None = None) -> int:
    raw = os.getenv(CAP_ENV, "") if value is None else value
    try:
        cap = int(str(raw).strip() or DEFAULT_DAILY_CAP)
    except ValueError:
        return DEFAULT_DAILY_CAP
    return max(cap, 0)


def _days(payload: dict[str, Any] | None) -> dict[str, int]:
    if not payload or payload.get("schema") != USAGE_STATE_SCHEMA:
        return {}
    return {str(k): int(v or 0) for k, v in (payload.get("days") or {}).items()}


def used_today(state: JsonState, *, today: date | None = None) -> int:
    return _days(state.read_json(USAGE_STATE_NAME)).get((today or kst_today()).isoformat(), 0)


def record_calls(state: JsonState, calls: int, *, today: date | None = None) -> int:
    """Add ``calls`` to today's count and return the new total (one writer: the collect group)."""

    day = (today or kst_today()).isoformat()
    days = _days(state.read_json(USAGE_STATE_NAME))
    if calls <= 0:
        return days.get(day, 0)
    days[day] = days.get(day, 0) + int(calls)
    kept = dict(sorted(days.items())[-KEEP_DAYS:])
    state.write_json(USAGE_STATE_NAME, {"schema": USAGE_STATE_SCHEMA, "days": kept})
    return kept[day]
