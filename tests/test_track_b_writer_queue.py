"""Review C-03: Track B writer runs wait in line instead of replacing each other."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITERS = (
    "track-b-daily-backfill.yml",
    "track-b-history-backfill.yml",
    "track-b-r2-serving-index.yml",
    "track-b-supplemental.yml",
)


def test_every_writer_shares_the_group_and_queues_all_waiting_runs() -> None:
    for name in WRITERS:
        concurrency = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))["concurrency"]
        assert "'track-b-r2-pipeline'" in concurrency["group"], name
        # queue: max cannot be combined with cancel-in-progress: true (GitHub validation error).
        assert concurrency["cancel-in-progress"] is False, name
        assert concurrency["queue"] == "max", name


def test_no_other_workflow_joins_the_writer_group() -> None:
    joined = sorted(
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if "track-b-r2-pipeline" in path.read_text(encoding="utf-8")
    )
    assert joined == sorted(WRITERS)
