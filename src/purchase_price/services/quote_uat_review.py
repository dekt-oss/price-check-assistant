from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean

from purchase_price.services.quote_extraction import QuoteItem, parse_quote_decimal

TEXT_FIELDS = (
    "product_name",
    "manufacturer",
    "model_name",
    "specification",
    "unit",
    "vat_status",
)
DECIMAL_FIELDS = ("quantity", "unit_price", "total_amount")
UAT_FIELDS = TEXT_FIELDS + DECIMAL_FIELDS
_STRONG_IDENTITY_FIELDS = ("product_name", "model_name", "specification")
_GAP_COST = 1.0
_NO_ANCHOR_PENALTY = 1.2


@dataclass(frozen=True)
class QuoteUatCaseMetric:
    case_id: str
    strategy: str
    expected_item_count: int
    actual_item_count: int
    matched_item_count: int
    false_positive_item_count: int
    false_negative_item_count: int
    scored_fields: int
    field_errors: int
    error_fields: tuple[str, ...]
    extraction_failed: bool = False
    processing_seconds: float | None = None
    review_seconds: float | None = None

    @property
    def exact_item_count(self) -> bool:
        return self.expected_item_count == self.actual_item_count

    @property
    def item_precision(self) -> float | None:
        if self.actual_item_count == 0:
            return None
        return self.matched_item_count / self.actual_item_count

    @property
    def item_recall(self) -> float | None:
        if self.expected_item_count == 0:
            return None
        return self.matched_item_count / self.expected_item_count

    @property
    def field_error_rate(self) -> float | None:
        if self.scored_fields == 0:
            return None
        return self.field_errors / self.scored_fields

    @property
    def status(self) -> str:
        if self.extraction_failed:
            return "EXTRACTION_FAILED"
        if (
            self.false_positive_item_count == 0
            and self.false_negative_item_count == 0
            and self.field_errors == 0
        ):
            return "PASS"
        return "REVIEW_REQUIRED"

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "strategy": self.strategy,
            "expected_item_count": self.expected_item_count,
            "actual_item_count": self.actual_item_count,
            "matched_item_count": self.matched_item_count,
            "false_positive_item_count": self.false_positive_item_count,
            "false_negative_item_count": self.false_negative_item_count,
            "exact_item_count": self.exact_item_count,
            "item_precision": self.item_precision,
            "item_recall": self.item_recall,
            "scored_fields": self.scored_fields,
            "field_errors": self.field_errors,
            "field_error_rate": self.field_error_rate,
            "error_fields": list(self.error_fields),
            "extraction_failed": self.extraction_failed,
            "processing_seconds": self.processing_seconds,
            "review_seconds": self.review_seconds,
        }


@dataclass(frozen=True)
class _PairComparison:
    scored_fields: int
    field_errors: int
    error_fields: tuple[str, ...]
    alignment_cost: float


def quote_item_to_review_row(item: QuoteItem) -> dict[str, object]:
    return {
        "product_name": item.product_name,
        "manufacturer": item.manufacturer,
        "model_name": item.model_name,
        "specification": item.specification,
        "quantity": float(item.quantity) if item.quantity is not None else None,
        "unit": item.unit,
        "unit_price": float(item.unit_price) if item.unit_price is not None else None,
        "total_amount": float(item.total_amount) if item.total_amount is not None else None,
        "vat_status": item.vat_status,
    }


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _expected_decimal(value: object) -> Decimal | None:
    return parse_quote_decimal(value)


def _actual_field_value(actual: QuoteItem, field: str) -> object:
    return getattr(actual, field, None)


def _strong_anchor_match(expected: Mapping[str, object], actual: QuoteItem) -> bool:
    for field in _STRONG_IDENTITY_FIELDS:
        expected_value = _normalize_text(expected.get(field))
        actual_value = _normalize_text(_actual_field_value(actual, field))
        if expected_value and actual_value and expected_value == actual_value:
            return True

    expected_unit_price = _expected_decimal(expected.get("unit_price"))
    actual_unit_price = actual.unit_price
    expected_total = _expected_decimal(expected.get("total_amount"))
    actual_total = actual.total_amount
    if expected_unit_price is not None and actual_unit_price == expected_unit_price:
        if expected_total is None or actual_total == expected_total:
            return True
    return False


def _compare_pair(expected: Mapping[str, object], actual: QuoteItem) -> _PairComparison:
    scored_fields = 0
    field_errors = 0
    error_fields: set[str] = set()

    for field in TEXT_FIELDS:
        expected_value = _normalize_text(expected.get(field))
        if not expected_value:
            continue
        scored_fields += 1
        actual_value = _normalize_text(_actual_field_value(actual, field))
        if expected_value != actual_value:
            field_errors += 1
            error_fields.add(field)

    for field in DECIMAL_FIELDS:
        expected_value = _expected_decimal(expected.get(field))
        if expected_value is None:
            continue
        scored_fields += 1
        actual_value = _actual_field_value(actual, field)
        if expected_value != actual_value:
            field_errors += 1
            error_fields.add(field)

    mismatch_rate = field_errors / scored_fields if scored_fields else 1.0
    alignment_cost = mismatch_rate
    if not _strong_anchor_match(expected, actual):
        alignment_cost += _NO_ANCHOR_PENALTY

    return _PairComparison(
        scored_fields=scored_fields,
        field_errors=field_errors,
        error_fields=tuple(sorted(error_fields)),
        alignment_cost=alignment_cost,
    )


def _align_rows(
    expected_rows: Sequence[Mapping[str, object]],
    actual_items: Sequence[QuoteItem],
) -> tuple[tuple[int, int, _PairComparison], ...]:
    """Align expected and actual rows without cascading errors after one missing/extra item.

    Quote tables are ordered, so a sequence alignment is preferable to arbitrary permutation.
    A row with an exact product/model/specification anchor (or exact price anchor) is cheap to
    pair even when another field is wrong. Completely unrelated rows are more expensive than
    one expected gap plus one actual gap, so they become explicit FN/FP items instead of a large
    block of misleading field errors.
    """

    expected_count = len(expected_rows)
    actual_count = len(actual_items)
    pair_cache: dict[tuple[int, int], _PairComparison] = {}

    def pair(i: int, j: int) -> _PairComparison:
        key = (i, j)
        if key not in pair_cache:
            pair_cache[key] = _compare_pair(expected_rows[i], actual_items[j])
        return pair_cache[key]

    costs = [[0.0] * (actual_count + 1) for _ in range(expected_count + 1)]
    ops = [[""] * (actual_count + 1) for _ in range(expected_count + 1)]
    for i in range(1, expected_count + 1):
        costs[i][0] = i * _GAP_COST
        ops[i][0] = "missing"
    for j in range(1, actual_count + 1):
        costs[0][j] = j * _GAP_COST
        ops[0][j] = "extra"

    for i in range(1, expected_count + 1):
        for j in range(1, actual_count + 1):
            candidates = (
                (costs[i - 1][j - 1] + pair(i - 1, j - 1).alignment_cost, 0, "pair"),
                (costs[i - 1][j] + _GAP_COST, 1, "missing"),
                (costs[i][j - 1] + _GAP_COST, 2, "extra"),
            )
            best_cost, _, best_op = min(candidates, key=lambda item: (item[0], item[1]))
            costs[i][j] = best_cost
            ops[i][j] = best_op

    aligned: list[tuple[int, int, _PairComparison]] = []
    i = expected_count
    j = actual_count
    while i or j:
        op = ops[i][j]
        if op == "pair":
            comparison = pair(i - 1, j - 1)
            aligned.append((i - 1, j - 1, comparison))
            i -= 1
            j -= 1
        elif op == "missing":
            i -= 1
        elif op == "extra":
            j -= 1
        else:  # pragma: no cover - defensive guard for an impossible DP state
            raise RuntimeError("quote UAT row alignment entered an invalid state")

    aligned.reverse()
    return tuple(aligned)


def compare_review_rows(
    *,
    case_id: str,
    strategy: str,
    actual_items: Sequence[QuoteItem],
    expected_rows: Sequence[Mapping[str, object]],
    extraction_failed: bool = False,
    processing_seconds: float | None = None,
    review_seconds: float | None = None,
) -> QuoteUatCaseMetric:
    aligned = _align_rows(expected_rows, actual_items)
    scored_fields = sum(comparison.scored_fields for _, _, comparison in aligned)
    field_errors = sum(comparison.field_errors for _, _, comparison in aligned)
    error_fields = sorted(
        {
            field
            for _, _, comparison in aligned
            for field in comparison.error_fields
        }
    )
    matched_item_count = len(aligned)
    false_negative_item_count = max(0, len(expected_rows) - matched_item_count)
    false_positive_item_count = max(0, len(actual_items) - matched_item_count)

    return QuoteUatCaseMetric(
        case_id=case_id,
        strategy=strategy,
        expected_item_count=len(expected_rows),
        actual_item_count=len(actual_items),
        matched_item_count=matched_item_count,
        false_positive_item_count=false_positive_item_count,
        false_negative_item_count=false_negative_item_count,
        scored_fields=scored_fields,
        field_errors=field_errors,
        error_fields=tuple(error_fields),
        extraction_failed=extraction_failed,
        processing_seconds=processing_seconds,
        review_seconds=review_seconds,
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _average(values: Sequence[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return mean(usable) if usable else None


def _strategy_summary(metrics: Sequence[QuoteUatCaseMetric]) -> dict[str, dict[str, object]]:
    grouped: defaultdict[str, list[QuoteUatCaseMetric]] = defaultdict(list)
    for metric in metrics:
        grouped[metric.strategy].append(metric)

    summary: dict[str, dict[str, object]] = {}
    for strategy, group in sorted(grouped.items()):
        matched_items = sum(metric.matched_item_count for metric in group)
        actual_items = sum(metric.actual_item_count for metric in group)
        expected_items = sum(metric.expected_item_count for metric in group)
        scored_fields = sum(metric.scored_fields for metric in group)
        field_errors = sum(metric.field_errors for metric in group)
        summary[strategy] = {
            "cases": len(group),
            "passed_cases": sum(metric.status == "PASS" for metric in group),
            "extraction_failures": sum(metric.extraction_failed for metric in group),
            "matched_items": matched_items,
            "false_positive_items": sum(metric.false_positive_item_count for metric in group),
            "false_negative_items": sum(metric.false_negative_item_count for metric in group),
            "item_precision": _rate(matched_items, actual_items),
            "item_recall": _rate(matched_items, expected_items),
            "field_error_rate": _rate(field_errors, scored_fields),
            "average_processing_seconds": _average(
                [metric.processing_seconds for metric in group]
            ),
            "average_review_seconds": _average([metric.review_seconds for metric in group]),
        }
    return summary


def build_redacted_uat_summary(
    metrics: Sequence[QuoteUatCaseMetric],
    *,
    minimum_cases: int = 5,
) -> dict[str, object]:
    total_cases = len(metrics)
    extraction_failures = sum(metric.extraction_failed for metric in metrics)
    exact_item_count_cases = sum(metric.exact_item_count for metric in metrics)
    scored_fields = sum(metric.scored_fields for metric in metrics)
    field_errors = sum(metric.field_errors for metric in metrics)
    matched_items = sum(metric.matched_item_count for metric in metrics)
    expected_items = sum(metric.expected_item_count for metric in metrics)
    actual_items = sum(metric.actual_item_count for metric in metrics)
    false_positive_items = sum(metric.false_positive_item_count for metric in metrics)
    false_negative_items = sum(metric.false_negative_item_count for metric in metrics)
    strategy_counts = Counter(metric.strategy for metric in metrics)

    return {
        "total_confirmed_cases": total_cases,
        "minimum_case_target": minimum_cases,
        "minimum_case_target_met": total_cases >= minimum_cases,
        "extraction_failures": extraction_failures,
        "extraction_failure_rate": _rate(extraction_failures, total_cases),
        "exact_item_count_cases": exact_item_count_cases,
        "exact_item_count_rate": _rate(exact_item_count_cases, total_cases),
        "expected_items": expected_items,
        "actual_items": actual_items,
        "matched_items": matched_items,
        "false_positive_items": false_positive_items,
        "false_negative_items": false_negative_items,
        "item_precision": _rate(matched_items, actual_items),
        "item_recall": _rate(matched_items, expected_items),
        "scored_fields": scored_fields,
        "field_errors": field_errors,
        "field_error_rate": _rate(field_errors, scored_fields),
        "average_processing_seconds": _average(
            [metric.processing_seconds for metric in metrics]
        ),
        "total_review_seconds": sum(
            metric.review_seconds for metric in metrics if metric.review_seconds is not None
        ),
        "average_review_seconds": _average([metric.review_seconds for metric in metrics]),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "strategy_metrics": _strategy_summary(metrics),
        "cases": [metric.to_redacted_dict() for metric in metrics],
        "privacy_note": (
            "이 결과에는 파일명, 견적 원문, 제품명, 제조사명, 모델명, 규격, 단가, 총액의 실제 값을 기록하지 않음"
        ),
    }


def redacted_uat_summary_json(
    metrics: Sequence[QuoteUatCaseMetric],
    *,
    minimum_cases: int = 5,
) -> str:
    return json.dumps(
        build_redacted_uat_summary(metrics, minimum_cases=minimum_cases),
        ensure_ascii=False,
        indent=2,
    )
