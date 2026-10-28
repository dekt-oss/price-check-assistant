"""Review E-02: the operations table and README agree with the workflows and the mapping CSV."""

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "operations" / "CURRENT_OPERATIONS.md").read_text(encoding="utf-8")
ROW = re.compile(r"^\| `(?P<file>[\w.-]+\.yml)` \| (?P<cron>[^|]+) \| (?P<timeout>\d+) \|", re.MULTILINE)


def _verified_count() -> tuple[int, int]:
    with (ROOT / "data" / "g2b_product_mappings.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return sum(row["mapping_status"] == "verified" for row in rows), len(rows)


def test_workflow_rows_match_the_workflow_files() -> None:
    rows = list(ROW.finditer(DOC))
    assert len(rows) >= 8
    for row in rows:
        workflow = (ROOT / ".github" / "workflows" / row["file"]).read_text(encoding="utf-8")
        cron = row["cron"].strip()
        if cron.startswith("`"):
            assert f'cron: "{cron.strip("`")}"' in workflow, row["file"]
        assert f"timeout-minutes: {row['timeout']}" in workflow, row["file"]


def test_mapping_counts_match_the_csv() -> None:
    verified, total = _verified_count()
    assert f"{total}개 중 **verified {verified}개**" in DOC
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"현재 verified mapping은 {verified}개입니다." in readme
