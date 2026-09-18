from __future__ import annotations

import argparse
import sys
from pathlib import Path

from purchase_price.services.match_benchmark import (
    run_match_benchmark,
    summarize_benchmark_coverage,
    write_benchmark_predictions,
    write_benchmark_summary,
)


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the F3 matcher against the human-reviewed ground truth. Precision/recall "
            "print N/A when the ground truth has no A/B positives; they are never estimated."
        )
    )
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Exit 1 when any predicted grade differs from the human-reviewed grade.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write every row's expected/predicted grade and match_note to this CSV.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Write benchmark metrics and ground-truth coverage limits to this JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_match_benchmark()
    evaluation = result.evaluation

    print(f"rows={evaluation.total}")
    print(f"exact_grade_accuracy={_pct(evaluation.exact_grade_accuracy)}")
    print(f"direct_precision={_pct(evaluation.direct_precision)}")
    print(f"direct_recall={_pct(evaluation.direct_recall)}")
    positives = evaluation.direct_true_positive + evaluation.direct_false_negative
    print(f"direct_positive_rows={positives}")

    coverage = summarize_benchmark_coverage(result)
    print(f"registry_models={coverage.registry_model_count}")
    print(f"reviewed_models={coverage.reviewed_model_count}")
    print(f"direct_positive_models={coverage.direct_positive_model_count}")
    print(
        "models_without_ground_truth="
        + (",".join(coverage.models_without_ground_truth) or "-")
    )
    print(
        "reviewed_models_without_direct_positive="
        + (",".join(coverage.reviewed_models_without_direct_positive) or "-")
    )

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

    if args.output is not None:
        write_benchmark_predictions(result, args.output)
        print(f"predictions={args.output}")
    if args.summary_output is not None:
        write_benchmark_summary(result, args.summary_output)
        print(f"summary={args.summary_output}")

    if mismatches and args.fail_on_mismatch:
        print(f"benchmark_status=failed mismatches={len(mismatches)}")
        return 1
    print("benchmark_status=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
