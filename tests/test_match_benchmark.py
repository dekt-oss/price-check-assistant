from pathlib import Path

import pytest

from purchase_price.domain import MatchGrade
from purchase_price.services.match_benchmark import (
    MatchBenchmarkError,
    run_match_benchmark,
    summarize_benchmark_coverage,
)

PRODUCTS = """category,manufacturer,product_name,model_name,specification,status,notes
의료장비,Stephan,인공호흡기,Sophie,운반형,benchmark 확정,test
전산비품,삼성전자,노트북컴퓨터,NT960XJG-K72AG,32GB 1TB,benchmark 확정,test
"""


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_benchmark_runner_scores_ground_truth_rows(tmp_path: Path) -> None:
    products = tmp_path / "products.csv"
    truth = tmp_path / "truth.csv"
    _write(products, PRODUCTS)
    _write(
        truth,
        'benchmark_model,source_name,source_record_id,candidate_title,expected_grade,review_note,evidence_url\n'
        'Sophie,g2b,1,"인공호흡기, Stephan, Sophie, 운반형",A,test,https://example.test/1\n'
        'NT960XJG-K72AG,g2b,2,"노트북컴퓨터, Other Vendor, NT960XJG-K72AG, 32GB 1TB",X,test,https://example.test/2\n',
    )

    result = run_match_benchmark(products_path=products, ground_truth_path=truth)

    assert result.evaluation.total == 2
    assert result.evaluation.exact_grade_accuracy == 1.0
    assert result.evaluation.direct_precision == 1.0
    assert result.evaluation.direct_recall == 1.0
    assert [row.predicted_grade for row in result.predictions] == [MatchGrade.A, MatchGrade.X]


def test_empty_ground_truth_does_not_fabricate_metrics(tmp_path: Path) -> None:
    products = tmp_path / "products.csv"
    truth = tmp_path / "truth.csv"
    _write(products, PRODUCTS)
    _write(
        truth,
        "benchmark_model,source_name,source_record_id,candidate_title,expected_grade,review_note,evidence_url\n",
    )

    result = run_match_benchmark(products_path=products, ground_truth_path=truth)

    assert result.evaluation.total == 0
    assert result.evaluation.direct_precision is None
    assert result.evaluation.direct_recall is None


def test_unknown_benchmark_model_is_rejected(tmp_path: Path) -> None:
    products = tmp_path / "products.csv"
    truth = tmp_path / "truth.csv"
    _write(products, PRODUCTS)
    _write(
        truth,
        'benchmark_model,source_name,source_record_id,candidate_title,expected_grade,review_note,evidence_url\n'
        'UNKNOWN,g2b,1,"인공호흡기, Stephan, Sophie",A,test,https://example.test/1\n',
    )

    with pytest.raises(MatchBenchmarkError, match="not in Phase 0 registry"):
        run_match_benchmark(products_path=products, ground_truth_path=truth)


def test_benchmark_coverage_separates_reviewed_positive_and_unreviewed_models(
    tmp_path: Path,
) -> None:
    products = tmp_path / "products.csv"
    truth = tmp_path / "truth.csv"
    _write(
        products,
        PRODUCTS
        + "전산비품,FUJIFILM,레이저프린터,ApeosPrint C5570 GK,A3,benchmark 확정,test\n",
    )
    _write(
        truth,
        'benchmark_model,source_name,source_record_id,candidate_title,expected_grade,review_note,evidence_url\n'
        'Sophie,g2b,1,"인공호흡기, Stephan, Sophie, 운반형",A,test,https://example.test/1\n'
        'NT960XJG-K72AG,g2b,2,"노트북컴퓨터, Samsung, OTHER",X,test,https://example.test/2\n',
    )

    result = run_match_benchmark(products_path=products, ground_truth_path=truth)
    coverage = summarize_benchmark_coverage(result)

    assert coverage.registry_model_count == 3
    assert coverage.reviewed_model_count == 2
    assert coverage.direct_positive_row_count == 1
    assert coverage.direct_positive_model_count == 1
    assert coverage.models_without_ground_truth == ("ApeosPrint C5570 GK",)
    assert coverage.reviewed_models_without_direct_positive == ("NT960XJG-K72AG",)
    assert dict(coverage.grade_counts)["A"] == 1
    assert dict(coverage.grade_counts)["X"] == 1
