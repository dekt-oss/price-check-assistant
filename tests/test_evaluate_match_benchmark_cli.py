import csv
from pathlib import Path

from purchase_price.scripts import evaluate_match_benchmark
from purchase_price.services.match_benchmark import run_match_benchmark


def test_cli_reports_and_writes_predictions(tmp_path: Path, capsys) -> None:
    output = tmp_path / "predictions.csv"

    code = evaluate_match_benchmark.main(["--fail-on-mismatch", "--output", str(output)])

    out = capsys.readouterr().out
    assert code == 0
    assert "rows=10" in out
    assert "direct_precision=N/A" in out
    assert "direct_positive_rows=0" in out
    assert "benchmark_status=ok" in out

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert all(row["expected_grade"] == row["predicted_grade"] for row in rows)
    assert all(row["match_note"].startswith("grade=") for row in rows)


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
