"""Review C-03: Track B writer runs wait in line instead of replacing each other."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITERS = (
    "track-b-daily-backfill.yml",
    "track-b-history-backfill.yml",
    "track-b-r2-serving-index.yml",
    "track-b-supplemental.yml",
)


def _concurrency_block(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    block = text.split("
concurrency:
", 1)[1]
    return block.split("

", 1)[0]


def test_every_writer_shares_the_group_and_queues_all_waiting_runs() -> None:
    for name in WRITERS:
        block = _concurrency_block(name)
        assert "|| 'track-b-r2-pipeline' }}" in block, name
        # queue: max cannot be combined with cancel-in-progress: true (GitHub validation error).
        assert "
  cancel-in-progress: false" in block, name
        assert "
  queue: max" in block, name


def test_no_other_workflow_joins_the_writer_group() -> None:
    joined = sorted(
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if "track-b-r2-pipeline" in path.read_text(encoding="utf-8")
    )
    assert joined == sorted(WRITERS)
