"""Pick the Track B collection job to start after a serving-index sync.

GitHub's schedule did not keep the collectors running on 2026-10-09: the daily run
("10 18 * * *") had fired only every second day, starting up to five hours late, and the
three-hourly history backfill fired once in twelve hours, so the index stood at
2026-10-05 and the backfill sat idle. The sync job now chains the next job itself: the daily
collection when the index is more than two days behind, otherwise the next history batch,
and nothing when the history is complete or today's call allowance is spent (the cron
schedules still run as a fallback).

Prints one of ``daily``, ``history`` or ``none``.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from purchase_price.config import Settings
from purchase_price.services.g2b_daily_usage import kst_today, remaining_today
from purchase_price.services.track_b_history_state import HISTORY_STATE_NAME
from purchase_price.services.track_b_pipeline_state import STATE_NAME as DAILY_STATE_NAME

DAILY_LAG_DAYS = 2
DAILY_MIN_GAP = timedelta(hours=20)
MIN_REMAINING_CALLS = 2_000


def choose_next_job(
    *,
    covered_through: date | None,
    today: date,
    last_daily_started: datetime | None,
    now: datetime,
    history_complete: bool,
    remaining_calls: int,
) -> str:
    if remaining_calls < MIN_REMAINING_CALLS:
        return "none"
    daily_due = covered_through is None or covered_through < today - timedelta(days=DAILY_LAG_DAYS)
    daily_recent = last_daily_started is not None and now - last_daily_started < DAILY_MIN_GAP
    if daily_due and not daily_recent:
        return "daily"
    if not history_complete:
        return "history"
    return "none"


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--last-daily-started",
        default="",
        help="createdAt of the latest non-PR daily run (ISO 8601), empty when unknown",
    )
    args = parser.parse_args(argv)

    from purchase_price.storage.r2_state import R2OperationalStateStore

    store = R2OperationalStateStore.from_settings(Settings())
    daily = store.read_json(DAILY_STATE_NAME) or {}
    history = store.read_json(HISTORY_STATE_NAME) or {}
    now = datetime.now().astimezone()
    print(
        choose_next_job(
            covered_through=_date(daily.get("rolling_covered_through")),
            today=kst_today(),
            last_daily_started=_timestamp(args.last_daily_started),
            now=now,
            history_complete=bool(history.get("complete")),
            remaining_calls=remaining_today(store),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
