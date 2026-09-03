from __future__ import annotations

from dataclasses import dataclass

from purchase_price.domain import MatchGrade

DIRECT_MATCH_GRADES = frozenset({MatchGrade.A, MatchGrade.B})


@dataclass(frozen=True)
class MatchEvaluation:
    total: int
    exact_grade_correct: int
    direct_true_positive: int
    direct_false_positive: int
    direct_false_negative: int
    direct_true_negative: int

    @property
    def exact_grade_accuracy(self) -> float | None:
        return self.exact_grade_correct / self.total if self.total else None

    @property
    def direct_precision(self) -> float | None:
        denominator = self.direct_true_positive + self.direct_false_positive
        return self.direct_true_positive / denominator if denominator else None

    @property
    def direct_recall(self) -> float | None:
        denominator = self.direct_true_positive + self.direct_false_negative
        return self.direct_true_positive / denominator if denominator else None


def evaluate_match_grades(
    expected: list[MatchGrade] | tuple[MatchGrade, ...],
    predicted: list[MatchGrade] | tuple[MatchGrade, ...],
) -> MatchEvaluation:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted grade sequences must have equal length")

    exact = 0
    tp = fp = fn = tn = 0
    for expected_grade, predicted_grade in zip(expected, predicted, strict=True):
        if expected_grade == predicted_grade:
            exact += 1

        expected_direct = expected_grade in DIRECT_MATCH_GRADES
        predicted_direct = predicted_grade in DIRECT_MATCH_GRADES
        if expected_direct and predicted_direct:
            tp += 1
        elif not expected_direct and predicted_direct:
            fp += 1
        elif expected_direct and not predicted_direct:
            fn += 1
        else:
            tn += 1

    return MatchEvaluation(
        total=len(expected),
        exact_grade_correct=exact,
        direct_true_positive=tp,
        direct_false_positive=fp,
        direct_false_negative=fn,
        direct_true_negative=tn,
    )
