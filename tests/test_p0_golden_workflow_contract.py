from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/p0-golden-apc-flow-uat.yml"


def test_golden_deterministic_gate_still_runs_on_pull_requests() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in source
    assert "Run deterministic golden safety gates" in source
    assert "pytest -q tests/test_p0_golden_uat_contract.py" in source


def test_golden_live_probe_is_manual_dispatch_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    live_step = (
        "- name: Run bounded live APC and FLOW probe\n"
        "        if: github.event_name == 'workflow_dispatch'\n"
    )
    assert live_step in source
    assert "--request-budget 24" in source


def test_golden_report_upload_remains_non_blocking_when_live_probe_is_skipped() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "- name: Print acceptance summary\n        if: always()" in source
    assert "- name: Upload golden UAT report\n        if: always()" in source
    assert "if-no-files-found: warn" in source
