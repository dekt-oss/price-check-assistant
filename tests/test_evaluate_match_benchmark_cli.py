import csv
import json
from pathlib import Path

from purchase_price.scripts import evaluate_match_benchmark
from purchase_price.services.match_benchmark import run_match_benchmark

DIRECT_GRADES = {"A", "B"}


def test_cli_reports_and_writes_predictions(tmp_path: Path, capsys) -> None:
    output = tmp_path / "predictions.csv"
    summary_output = tmp_path / "summary.json"
    expected = run_match_benchmark()

    code = evaluate_match_benchmark.main(
        [
            "--fail-on-mismatch",
            "--output",
            str(output),
            "--summary-output",
            str(summary_output),
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    positives = sum(
        1 for row in expected.predictions if row.expected_grade.value in DIRECT_GRADES
    )
    assert f"rows={len(expected.predictions)}" in out
    assert f"direct_positive_rows={positives}" in out
    assert "registry_models=" in out
    assert "reviewed_models=" in out
    assert "direct_positive_models=" in out
    assert "models_without_ground_truth=" in out
    assert "reviewed_models_without_direct_positive=" in out
    assert "benchmark_status=ok" in out

    # Precision/recall must read N/A exactly while no A/B positive exists to measure, and must
    # stop reading N/A once one does. Pinning today's 100.0% would break on the next positive.
    if positives == 0:
        assert "direct_precision=N/A" in out
        assert "direct_recall=N/A" in out
    else:
        assert "direct_precision=N/A" not in out
        assert "direct_recall=N/A" not in out

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(expected.predictions)
    assert all(row["expected_grade"] == row["predicted_grade"] for row in rows)
    assert all(row["match_note"].startswith("grade=") for row in rows)

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["rows"] == len(expected.predictions)
    assert summary["direct_positive_row_count"] == positives
    assert summary["registry_model_count"] >= summary["reviewed_model_count"]
    assert "models_without_ground_truth" in summary
    assert "reviewed_models_without_direct_positive" in summary


def test_cli_fails_when_strict_and_prediction_mismatches(monkeypatch, capsys) -> None:
    real = run_match_benchmark()
    first = real.predictions[0]
    flipped = first.__class__(
        benchmark_model=first.benchmark_model,
        candidate_title=first.candidate_title,
        expected_grade=first.expected_grade,
        predicted_grade=first.expected_grade.__class__("A"),
        match_note=first.match_note,
    )
    fake = real.__class__(predictions=(flipped, *real.predictions[1:]), evaluation=real.evaluation)
    monkeypatch.setattr(evaluate_match_benchmark, "run_match_benchmark", lambda: fake)

    assert evaluate_match_benchmark.main(["--fail-on-mismatch"]) == 1
    assert "benchmark_status=failed mismatches=1" in capsys.readouterr().out
    assert evaluate_match_benchmark.main([]) == 0
