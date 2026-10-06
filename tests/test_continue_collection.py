from __future__ import annotations

import json
from pathlib import Path

import pytest

from purchase_price.scripts import continue_collection as cc


def _report(status="SUCCESS", pages=600, done=False):
    return {"status": status, "pages_collected": pages, "cycle_completed": done}


@pytest.mark.parametrize(
    ("reports", "first_cycle", "expected"),
    [
        ([_report(), _report()], True, True),
        ([_report(), _report(done=True)], True, False),
        ([_report(), _report(status="SOURCE_QUOTA_EXCEEDED")], True, False),
        ([_report(status="SOURCE_TRANSPORT_ERROR")], True, False),
        ([_report(pages=0)], True, False),
        ([], True, False),
        ([_report()], False, False),
    ],
)
def test_continue_only_after_clean_progress_in_the_first_cycle(reports, first_cycle, expected) -> None:
    go, _reason = cc.decide(reports, first_cycle=first_cycle)
    assert go is expected


def test_cli_prints_decision(tmp_path: Path, capsys, monkeypatch) -> None:
    for n, report in enumerate([_report(), _report()], start=1):
        (tmp_path / f"sync-{n}.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["continue_collection", "--reports", str(tmp_path / "sync-*.json"), "--first-cycle", "true"],
    )
    cc.main()
    assert capsys.readouterr().out.strip() == "continue"


def test_both_workflows_self_continue_on_main_only() -> None:
    for name, dispatch in (
        ("mfds-identity-index.yml", "gh workflow run mfds-identity-index.yml --ref main"),
        ("mfds-item-status-index.yml", "gh workflow run mfds-item-status-index.yml --ref main"),
    ):
        text = Path(".github/workflows", name).read_text(encoding="utf-8")
        assert "python -m purchase_price.scripts.continue_collection" in text
        assert dispatch in text
        assert "github.ref == 'refs/heads/main'" in text
        assert "actions: write" in text
