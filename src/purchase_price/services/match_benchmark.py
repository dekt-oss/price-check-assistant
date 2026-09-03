from __future__ import annotations

import csv
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


def _load_product_queries(path: Path) -> dict[str, ProductQuery]:
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
    queries = _load_product_queries(products_path)
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
    )
