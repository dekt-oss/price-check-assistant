"""The News Radar chain decision and the daily NAVER call counter (no network)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from purchase_price.scripts import next_news_radar_run as nxt
from purchase_price.services import news_radar_budget as budget

LOOP = {
    "started_at": "2026-10-10T03:00:00+00:00",
    "finished_at": "2026-10-10T03:49:00+00:00",
    "keyword_count": 27,
    "naver_calls_today": 1_000,
    "passes": [{"status": "ok"}] * 5,
}
OWN = "111"


def _decide(**overrides):
    values = {
        "chain_enabled": True,
        "loop_summary": LOOP,
        "runs": [{"databaseId": 111, "status": "in_progress", "displayTitle": nxt.COLLECT_RUN_TITLE}],
        "own_run_id": OWN,
        "daily_cap": 20_000,
    }
    values.update(overrides)
    return nxt.choose_next_run(**values)


def test_dispatches_after_a_full_loop_with_budget_left_and_no_other_run() -> None:
    decision, reason = _decide()
    assert decision == nxt.DISPATCH and "1,000" in reason


def test_kill_switch_stops_the_chain() -> None:
    assert _decide(chain_enabled=False)[0] == nxt.NONE


@pytest.mark.parametrize("summary", [None, {}, [], {**LOOP, "finished_at": "2026-10-10T03:02:00+00:00"}])
def test_no_dispatch_without_a_full_loop(summary) -> None:
    assert _decide(loop_summary=summary)[0] == nxt.NONE


def test_budget_stops_the_chain_before_the_next_loop_would_cross_the_cap() -> None:
    # 27 keywords x 5 passes = 135 calls for the next loop.
    assert _decide(loop_summary={**LOOP, "naver_calls_today": 20_000 - 135})[0] == nxt.DISPATCH
    decision, reason = _decide(loop_summary={**LOOP, "naver_calls_today": 20_000 - 134})
    assert decision == nxt.NONE and "cap 20,000" in reason


def test_unknown_usage_still_dispatches() -> None:
    # The collector's own per-pass check still guards each pass.
    assert _decide(loop_summary={**LOOP, "naver_calls_today": None})[0] == nxt.DISPATCH


@pytest.mark.parametrize("status", ["queued", "in_progress", "pending", "waiting", "requested"])
def test_another_active_collect_run_continues_the_chain(status) -> None:
    runs = [
        {"databaseId": 111, "status": "in_progress", "displayTitle": nxt.COLLECT_RUN_TITLE},
        {"databaseId": 222, "status": status, "displayTitle": nxt.COLLECT_RUN_TITLE},
    ]
    decision, reason = _decide(runs=runs)
    assert decision == nxt.NONE and "222" in reason


def test_digest_and_finished_runs_do_not_block() -> None:
    runs = [
        {"databaseId": 333, "status": "in_progress", "displayTitle": "News Radar digest"},
        {"databaseId": 444, "status": "completed", "displayTitle": nxt.COLLECT_RUN_TITLE},
        {"databaseId": 111, "status": "in_progress", "displayTitle": nxt.COLLECT_RUN_TITLE},
    ]
    assert _decide(runs=runs)[0] == nxt.DISPATCH


def test_main_reads_files_and_prints_one_word(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv(budget.CHAIN_ENV, raising=False)
    monkeypatch.delenv(budget.CAP_ENV, raising=False)
    loop = tmp_path / "collect.json"
    loop.write_text(json.dumps(LOOP), encoding="utf-8")
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps([{"databaseId": 111, "status": "in_progress", "displayTitle": "x"}]), encoding="utf-8")
    assert nxt.main(["--loop-summary", str(loop), "--runs-json", str(runs), "--run-id", OWN]) == 0
    assert capsys.readouterr().out.strip() == "dispatch"

    monkeypatch.setenv(budget.CHAIN_ENV, "OFF")
    nxt.main(["--loop-summary", str(loop), "--runs-json", str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert captured.out.strip() == "none" and "NEWS_RADAR_CHAIN=off" in captured.err


@pytest.mark.parametrize(("value", "enabled"), [("", True), ("on", True), ("off", False), (" Off ", False), ("0", False)])
def test_chain_switch_values(value, enabled) -> None:
    assert budget.chain_enabled(value) is enabled


@pytest.mark.parametrize(("value", "cap"), [("", 20_000), ("5000", 5_000), ("abc", 20_000), ("-3", 0)])
def test_daily_cap_values(value, cap) -> None:
    assert budget.daily_cap(value) == cap


def test_usage_counter_adds_per_kst_day_and_keeps_two_weeks(tmp_path) -> None:
    state = budget.LocalJsonState(tmp_path)
    day = date(2026, 10, 10)
    assert budget.used_today(state, today=day) == 0
    assert budget.record_calls(state, 27, today=day) == 27
    assert budget.record_calls(state, 0, today=day) == 27
    assert budget.record_calls(state, 27, today=day) == 54
    for offset in range(1, 20):
        budget.record_calls(state, 1, today=date(2026, 10, 10 + offset))
    payload = state.read_json(budget.USAGE_STATE_NAME)
    assert payload["schema"] == budget.USAGE_STATE_SCHEMA and len(payload["days"]) == budget.KEEP_DAYS
    assert budget.used_today(state, today=date(2026, 10, 29)) == 1
