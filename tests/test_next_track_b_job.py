"""The index sync chains the next collector because GitHub's schedule skipped most runs."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from purchase_price.scripts.next_track_b_job import choose_next_job

TODAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 13, 40, tzinfo=UTC)


def _choose(**overrides) -> str:
    values = {
        "covered_through": date(2026, 10, 8),
        "today": TODAY,
        "last_daily_started": NOW - timedelta(hours=30),
        "now": NOW,
        "history_complete": False,
        "remaining_calls": 50_000,
    }
    values.update(overrides)
    return choose_next_job(**values)


def test_stale_index_starts_the_daily_collection() -> None:
    assert _choose(covered_through=date(2026, 10, 5)) == "daily"
    assert _choose(covered_through=None) == "daily"


def test_daily_is_not_restarted_within_twenty_hours() -> None:
    assert _choose(covered_through=date(2026, 10, 5), last_daily_started=NOW - timedelta(hours=2)) == "history"


def test_fresh_index_continues_the_history_until_complete() -> None:
    assert _choose() == "history"
    assert _choose(history_complete=True) == "none"


def test_spent_allowance_starts_nothing() -> None:
    assert _choose(covered_through=date(2026, 10, 1), remaining_calls=1_999) == "none"


def test_sync_job_dispatches_the_chosen_job() -> None:
    text = Path(".github/workflows/track-b-r2-serving-index.yml").read_text(encoding="utf-8")
    assert "actions: write" in text
    assert "python -m purchase_price.scripts.next_track_b_job" in text
    assert "gh workflow run track-b-daily-backfill.yml" in text
    assert "gh workflow run track-b-history-backfill.yml" in text
