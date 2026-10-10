"""Decide whether a finished News Radar collect run starts the next one (``gh workflow run``).

GitHub's "*/10" schedule fired the collector only at 03:02, 07:28 and 14:35 UTC on 2026-10-09
(plus two manual runs), so the 병원 News Radar page said "자동 확인이 1시간 넘게 멈춰 있습니다" most
of the day. Each collect run now loops for ~59 minutes (a pass every 30 minutes) and then starts
its own successor. The cron stays as a fallback that restarts the chain if it ever stops.

Prints ``dispatch`` or ``none`` on stdout and the reason on stderr. No dispatch when:

- the repository variable ``NEWS_RADAR_CHAIN`` is ``off`` (kill switch);
- the loop summary is missing, or the loop ran shorter than ``MIN_LOOP_SECONDS`` (a crash right
  after start must not turn into a run-every-minute loop);
- today's NAVER calls plus one more loop would cross the daily cap (KST day);
- another collect run of this workflow is already queued, waiting or running (it continues the
  chain; the job's concurrency group would make it wait anyway).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from purchase_price.services import news_radar_budget as budget

COLLECT_RUN_TITLE = "News Radar collect"
MIN_LOOP_SECONDS = 30 * 60
DISPATCH = "dispatch"
NONE = "none"


def _seconds_between(start: object, finish: object) -> float | None:
    try:
        begin = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(finish).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - begin).total_seconds()


def other_active_collect_runs(runs: Iterable[Mapping[str, Any]], own_run_id: str) -> list[str]:
    """IDs of collect runs (not digest runs) of this workflow that have not completed."""

    active = []
    for run in runs:
        run_id = str(run.get("databaseId") or "")
        if run_id == str(own_run_id) or str(run.get("status") or "") == "completed":
            continue
        if str(run.get("displayTitle") or "") != COLLECT_RUN_TITLE:
            continue
        active.append(run_id)
    return active


def choose_next_run(
    *,
    chain_enabled: bool,
    loop_summary: Mapping[str, Any] | None,
    runs: Iterable[Mapping[str, Any]],
    own_run_id: str,
    daily_cap: int,
) -> tuple[str, str]:
    if not chain_enabled:
        return NONE, "NEWS_RADAR_CHAIN=off: the chain is switched off"
    if not isinstance(loop_summary, Mapping) or not loop_summary:
        return NONE, "no loop summary: the collect step did not finish"
    elapsed = _seconds_between(loop_summary.get("started_at"), loop_summary.get("finished_at"))
    if elapsed is None or elapsed < MIN_LOOP_SECONDS:
        return NONE, f"the loop ran {elapsed or 0:.0f}s (< {MIN_LOOP_SECONDS}s): not restarting right away"
    used = loop_summary.get("naver_calls_today")
    keyword_count = int(loop_summary.get("keyword_count") or 0)
    passes_per_loop = max(1, len(loop_summary.get("passes") or []))
    next_loop_calls = keyword_count * passes_per_loop
    if used is not None and int(used) + next_loop_calls > daily_cap:
        return NONE, f"NAVER calls today {int(used):,} + next loop {next_loop_calls:,} > cap {daily_cap:,}"
    others = other_active_collect_runs(runs, own_run_id)
    if others:
        return NONE, "another collect run is queued or running: " + ", ".join(others)
    used_text = "unknown" if used is None else f"{int(used):,}"
    return DISPATCH, f"NAVER calls today {used_text} of cap {daily_cap:,}; starting the next run"


def _read_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop-summary", type=Path, required=True, help="collect_news_radar --summary-json")
    parser.add_argument("--runs-json", type=Path, help="gh run list --json databaseId,status,displayTitle")
    parser.add_argument("--run-id", default="", help="this run's GITHUB_RUN_ID")
    args = parser.parse_args(argv)

    runs = _read_json(args.runs_json)
    decision, reason = choose_next_run(
        chain_enabled=budget.chain_enabled(),
        loop_summary=_read_json(args.loop_summary),
        runs=runs if isinstance(runs, list) else [],
        own_run_id=args.run_id,
        daily_cap=budget.daily_cap(),
    )
    print(reason, file=sys.stderr)
    print(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
