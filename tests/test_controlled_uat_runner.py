import csv
from pathlib import Path

from purchase_price.scripts.run_controlled_uat import _write_outputs, run_controlled_uat


def test_controlled_uat_runner_executes_offline_cases_without_blockers() -> None:
    cases, summary = run_controlled_uat()

    assert len(cases) == 15
    assert summary["mode"] == "deterministic_offline_pre_uat"
    assert summary["automated_cases"] == 12
    assert summary["not_run_live_cases"] == 3
    assert summary["passed_automated_cases"] == 12
    assert summary["failed_automated_cases"] == 0
    assert summary["identity_false_positive_count"] == 0
    assert summary["comparison_false_positive_count"] == 0
    assert summary["comparison_false_negative_count"] == 1
    assert summary["zero_vs_failure_error_count"] == 0
    assert summary["provenance_secret_filter_and_fingerprint_ok"] is True
    assert summary["release_blocker_count"] == 0
    assert summary["live_required_cases"] == ["UAT-04", "UAT-14", "UAT-15"]
    assert all(
        case.assertion_status == "PASS" for case in cases if case.automated
    ), "every deterministic automated UAT case must remain green against the current base"


def test_controlled_uat_results_write_with_exact_template_schema(tmp_path: Path) -> None:
    cases, summary = run_controlled_uat()

    _write_outputs(tmp_path, cases, summary)

    with (tmp_path / "controlled-uat-results.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 15
    assert all(None not in row for row in rows)
    assert (tmp_path / "controlled-uat-summary.json").is_file()


def test_quantity_mismatch_is_recorded_as_known_conservative_false_negative() -> None:
    cases, _ = run_controlled_uat()
    uat11 = next(case for case in cases if case.row["case_id"] == "UAT-11")

    assert uat11.assertion_status == "PASS"
    assert uat11.row["candidate_gate_result"] == "비교 보류"
    assert uat11.row["false_negative_comparison"] == "true"
    assert "수량 불일치" in uat11.row["candidate_gate_reasons"]


def test_mfds_live_cases_are_explicitly_not_run_offline() -> None:
    cases, _ = run_controlled_uat()
    by_id = {case.row["case_id"]: case for case in cases}

    for case_id in ("UAT-04", "UAT-14", "UAT-15"):
        case = by_id[case_id]
        assert case.assertion_status == "NOT_RUN"
        assert case.automated is False
        assert case.row["extraction_status"] == "NOT_RUN_LIVE_REQUIRED"
