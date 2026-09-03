import pytest

from purchase_price.domain import MatchGrade
from purchase_price.services.match_evaluation import evaluate_match_grades


def test_direct_precision_and_recall_are_computed_separately_from_exact_grade_accuracy() -> None:
    result = evaluate_match_grades(
        [MatchGrade.A, MatchGrade.B, MatchGrade.C, MatchGrade.X],
        [MatchGrade.A, MatchGrade.C, MatchGrade.B, MatchGrade.X],
    )

    assert result.total == 4
    assert result.exact_grade_correct == 2
    assert result.exact_grade_accuracy == 0.5
    assert result.direct_true_positive == 1
    assert result.direct_false_positive == 1
    assert result.direct_false_negative == 1
    assert result.direct_true_negative == 1
    assert result.direct_precision == 0.5
    assert result.direct_recall == 0.5


def test_empty_evaluation_has_no_fabricated_metrics() -> None:
    result = evaluate_match_grades([], [])

    assert result.total == 0
    assert result.exact_grade_accuracy is None
    assert result.direct_precision is None
    assert result.direct_recall is None


def test_evaluation_rejects_different_sequence_lengths() -> None:
    with pytest.raises(ValueError, match="equal length"):
        evaluate_match_grades([MatchGrade.A], [])
