"""Decide whether a backfill run should start the next run itself.

GitHub's scheduled runs were delayed by over two hours or skipped on 2026-10-05/06, which
left the MFDS backfills idle most of the day. A run that ends cleanly with the first cycle
still unfinished now dispatches the next run directly. It never chains after an error,
a quota stop, a run that collected nothing, a finished cycle, or once the first cycle has
been verified (the normal schedule takes over then), so it cannot loop on a failure.

Prints "continue" or "stop: <reason>".
"""

from __future__ import annotations

import argparse
import glob
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def decide(reports: Sequence[dict[str, Any]], *, first_cycle: bool) -> tuple[bool, str]:
    if not first_cycle:
        return False, "first cycle already verified; regular schedule only"
    if not reports:
        return False, "no chunk ran"
    statuses = [str(report.get("status") or "") for report in reports]
    if any(status != "SUCCESS" for status in statuses):
        return False, f"chunk status {','.join(statuses)}"
    if not sum(int(report.get("pages_collected") or 0) for report in reports):
        return False, "no pages collected"
    if reports[-1].get("cycle_completed"):
        return False, "cycle completed"
    return True, "first cycle unfinished and every chunk succeeded"


def _load(pattern: str) -> list[dict[str, Any]]:
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in sorted(glob.glob(pattern))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", required=True, help="glob of per-chunk sync reports")
    parser.add_argument("--first-cycle", required=True, choices=("true", "false"))
    args = parser.parse_args()
    go, reason = decide(_load(args.reports), first_cycle=args.first_cycle == "true")
    print("continue" if go else f"stop: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
