from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from purchase_price.services import g2b_daily_usage as usage

TODAY = date(2026, 10, 9)


class _States:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    def read_json(self, name):
        return self.values.get(name)

    def write_json(self, name, payload) -> None:
        self.values[name] = json.loads(json.dumps(payload))


def test_calls_add_up_per_kst_day_and_old_days_are_dropped() -> None:
    states = _States()
    usage.record_calls(states, 900, today=TODAY)
    assert usage.record_calls(states, 1909, today=TODAY) == 2809
    for offset in range(1, 20):
        usage.record_calls(states, 1, today=date(2026, 10, 9 + offset) if offset < 23 else TODAY)

    days = states.values[usage.USAGE_STATE_NAME]["days"]
    assert len(days) == usage.KEEP_DAYS
    assert usage.used_today(states, today=date(2026, 10, 28)) == 1


def test_remaining_respects_the_cap_from_the_environment(monkeypatch) -> None:
    states = _States()
    usage.record_calls(states, 79_500, today=TODAY)

    monkeypatch.delenv(usage.CAP_ENV, raising=False)
    assert usage.remaining_today(states, today=TODAY) == 500
    monkeypatch.setenv(usage.CAP_ENV, "70000")
    assert usage.remaining_today(states, today=TODAY) == 0
    monkeypatch.setenv(usage.CAP_ENV, "not-a-number")
    assert usage.daily_cap() == usage.DEFAULT_DAILY_CAP


def test_history_runner_stops_when_the_day_is_spent(monkeypatch, tmp_path: Path) -> None:
    from purchase_price.scripts import run_g2b_track_b_history as runner
    from purchase_price.services.track_b_history_state import HISTORY_STATE_NAME, TrackBHistoryState
    from tests.test_track_b_history_state import _MemoryStates, _summary, _wire_runner

    states = _MemoryStates()
    budgets: list[int] = []

    def fake_collect(**kwargs):
        budgets.append(kwargs["request_budget"])
        state = TrackBHistoryState.from_payload(states.values[HISTORY_STATE_NAME])
        return _summary(state, next_index=1, requests=kwargs["request_budget"])

    _wire_runner(monkeypatch, tmp_path, states, fake_collect)
    monkeypatch.setenv(usage.CAP_ENV, "2500")
    exit_code = runner.run(
        request_budget=2000, output=tmp_path / "s.json", max_minutes=300, pause=lambda _s: None
    )

    report = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert budgets == [2000, 500]  # the second batch is cut to what is left of the cap
    assert report["stop_reason"] == "DAILY_CALL_CAP_REACHED"
    assert usage.used_today(states) == 2500
