from __future__ import annotations

from purchase_price.services.match_benchmark import run_match_benchmark


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def main() -> None:
    result = run_match_benchmark()
    evaluation = result.evaluation

    print(f"rows={evaluation.total}")
    print(f"exact_grade_accuracy={_pct(evaluation.exact_grade_accuracy)}")
    print(f"direct_precision={_pct(evaluation.direct_precision)}")
    print(f"direct_recall={_pct(evaluation.direct_recall)}")

    mismatches = [
        row for row in result.predictions if row.expected_grade != row.predicted_grade
    ]
    if mismatches:
        print("mismatches:")
        for row in mismatches:
            print(
                f"- model={row.benchmark_model} expected={row.expected_grade.value} "
                f"predicted={row.predicted_grade.value} title={row.candidate_title!r} "
                f"note={row.match_note}"
            )


if __name__ == "__main__":
    main()
