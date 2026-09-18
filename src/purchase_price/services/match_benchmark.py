from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.match_evaluation import MatchEvaluation, evaluate_match_grades
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import grade_product_identity, parse_g2b_identity

DEFAULT_PRODUCTS_PATH = Path(__file__).resolve().parents[3] / "data" / "phase0_products.csv"
DEFAULT_GROUND_TRUTH_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "phase0_match_ground_truth.csv"
)


class MatchBenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True)
class BenchmarkPrediction:
    benchmark_model: str
    candidate_title: str
    expected_grade: MatchGrade
    predicted_grade: MatchGrade
    match_note: str


@dataclass(frozen=True)
class MatchBenchmarkResult:
    predictions: tuple[BenchmarkPrediction, ...]
    evaluation: MatchEvaluation
    registry_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkCoverage:
    registry_model_count: int
    reviewed_model_count: int
    direct_positive_row_count: int
    direct_positive_model_count: int
    models_without_ground_truth: tuple[str, ...]
    reviewed_models_without_direct_positive: tuple[str, ...]
    grade_counts: tuple[tuple[str, int], ...]


def load_phase0_product_queries(path: Path = DEFAULT_PRODUCTS_PATH) -> dict[str, ProductQuery]:
    """Load Phase 0 benchmark queries keyed by normalized model; duplicates fail closed."""

    if not path.exists():
        raise MatchBenchmarkError(f"Phase 0 product registry not found: {path}")

    queries: dict[str, ProductQuery] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"manufacturer", "product_name", "model_name", "specification"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise MatchBenchmarkError("Phase 0 product registry is missing required columns")

        for row in reader:
            model = (row.get("model_name") or "").strip()
            key = normalize_text(model)
            if not key:
                continue
            if key in queries:
                raise MatchBenchmarkError(f"duplicate Phase 0 model: {model!r}")
            queries[key] = ProductQuery(
                product_name=(row.get("product_name") or "").strip(),
                manufacturer=(row.get("manufacturer") or "").strip(),
                model_name=model,
                specification=(row.get("specification") or "").strip(),
            )
    return queries


def run_match_benchmark(
    *,
    products_path: Path = DEFAULT_PRODUCTS_PATH,
    ground_truth_path: Path = DEFAULT_GROUND_TRUTH_PATH,
) -> MatchBenchmarkResult:
    queries = load_phase0_product_queries(products_path)
    if not ground_truth_path.exists():
        raise MatchBenchmarkError(f"match ground truth not found: {ground_truth_path}")

    predictions: list[BenchmarkPrediction] = []
    expected: list[MatchGrade] = []
    predicted: list[MatchGrade] = []

    with ground_truth_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"benchmark_model", "candidate_title", "expected_grade"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise MatchBenchmarkError("match ground truth is missing required columns")

        for line_no, row in enumerate(reader, start=2):
            model = (row.get("benchmark_model") or "").strip()
            title = (row.get("candidate_title") or "").strip()
            grade_text = (row.get("expected_grade") or "").strip().upper()
            if not model and not title and not grade_text:
                continue
            if not model or not title or not grade_text:
                raise MatchBenchmarkError(f"incomplete ground-truth row at line {line_no}")

            query = queries.get(normalize_text(model))
            if query is None:
                raise MatchBenchmarkError(
                    f"ground-truth model is not in Phase 0 registry at line {line_no}: {model!r}"
                )
            try:
                expected_grade = MatchGrade(grade_text)
            except ValueError as exc:
                raise MatchBenchmarkError(
                    f"invalid expected grade at line {line_no}: {grade_text!r}"
                ) from exc

            identity = parse_g2b_identity(title)
            decision = grade_product_identity(query, identity)
            predictions.append(
                BenchmarkPrediction(
                    benchmark_model=model,
                    candidate_title=title,
                    expected_grade=expected_grade,
                    predicted_grade=decision.grade,
                    match_note=decision.note,
                )
            )
            expected.append(expected_grade)
            predicted.append(decision.grade)

    return MatchBenchmarkResult(
        predictions=tuple(predictions),
        evaluation=evaluate_match_grades(expected, predicted),
        registry_models=tuple(query.model_name for query in queries.values()),
    )


def summarize_benchmark_coverage(result: MatchBenchmarkResult) -> BenchmarkCoverage:
    """Describe what the reviewed ground truth actually covers without inventing confidence."""

    reviewed_models = tuple(
        dict.fromkeys(row.benchmark_model for row in result.predictions)
    )
    direct_positive_models = {
        row.benchmark_model
        for row in result.predictions
        if row.expected_grade in {MatchGrade.A, MatchGrade.B}
    }
    registry_models = result.registry_models or reviewed_models
    reviewed_set = set(reviewed_models)

    grade_counts = tuple(
        (
            grade.value,
            sum(1 for row in result.predictions if row.expected_grade == grade),
        )
        for grade in MatchGrade
    )
    return BenchmarkCoverage(
        registry_model_count=len(registry_models),
        reviewed_model_count=len(reviewed_models),
        direct_positive_row_count=sum(
            1
            for row in result.predictions
            if row.expected_grade in {MatchGrade.A, MatchGrade.B}
        ),
        direct_positive_model_count=len(direct_positive_models),
        models_without_ground_truth=tuple(
            model for model in registry_models if model not in reviewed_set
        ),
        reviewed_models_without_direct_positive=tuple(
            model for model in reviewed_models if model not in direct_positive_models
        ),
        grade_counts=grade_counts,
    )


def write_benchmark_summary(result: MatchBenchmarkResult, path: Path) -> None:
    """Write auditable benchmark metrics and factual coverage limits as JSON."""

    coverage = summarize_benchmark_coverage(result)
    evaluation = result.evaluation
    payload = {
        "rows": evaluation.total,
        "exact_grade_accuracy": evaluation.exact_grade_accuracy,
        "direct_precision": evaluation.direct_precision,
        "direct_recall": evaluation.direct_recall,
        "registry_model_count": coverage.registry_model_count,
        "reviewed_model_count": coverage.reviewed_model_count,
        "direct_positive_row_count": coverage.direct_positive_row_count,
        "direct_positive_model_count": coverage.direct_positive_model_count,
        "models_without_ground_truth": list(coverage.models_without_ground_truth),
        "reviewed_models_without_direct_positive": list(
            coverage.reviewed_models_without_direct_positive
        ),
        "grade_counts": dict(coverage.grade_counts),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


PREDICTION_FIELDS = (
    "benchmark_model",
    "candidate_title",
    "expected_grade",
    "predicted_grade",
    "match_note",
)


def write_benchmark_predictions(result: MatchBenchmarkResult, path: Path) -> None:
    """Persist every per-row decision so a benchmark run can be audited and reproduced."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PREDICTION_FIELDS))
        writer.writeheader()
        for row in result.predictions:
            writer.writerow(
                {
                    "benchmark_model": row.benchmark_model,
                    "candidate_title": row.candidate_title,
                    "expected_grade": row.expected_grade.value,
                    "predicted_grade": row.predicted_grade.value,
                    "match_note": row.match_note,
                }
            )
