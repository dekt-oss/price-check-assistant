from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

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


@dataclass(frozen=True)
class QuoteUatCaseMetric:
    case_id: str
    strategy: str
    expected_item_count: int
    actual_item_count: int
    scored_fields: int
    field_errors: int
    error_fields: tuple[str, ...]
    extraction_failed: bool = False

    @property
    def exact_item_count(self) -> bool:
        return self.expected_item_count == self.actual_item_count

    @property
    def field_error_rate(self) -> float | None:
        if self.scored_fields == 0:
            return None
        return self.field_errors / self.scored_fields

    @property
    def status(self) -> str:
        if self.extraction_failed:
            return "EXTRACTION_FAILED"
        if self.exact_item_count and self.field_errors == 0:
            return "PASS"
        return "REVIEW_REQUIRED"

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "strategy": self.strategy,
            "expected_item_count": self.expected_item_count,
            "actual_item_count": self.actual_item_count,
            "exact_item_count": self.exact_item_count,
            "scored_fields": self.scored_fields,
            "field_errors": self.field_errors,
            "field_error_rate": self.field_error_rate,
            "error_fields": list(self.error_fields),
            "extraction_failed": self.extraction_failed,
        }


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


def compare_review_rows(
    *,
    case_id: str,
    strategy: str,
    actual_items: Sequence[QuoteItem],
    expected_rows: Sequence[Mapping[str, object]],
    extraction_failed: bool = False,
) -> QuoteUatCaseMetric:
    scored_fields = 0
    field_errors = 0
    error_fields: set[str] = set()

    for row_index, expected in enumerate(expected_rows):
        actual = actual_items[row_index] if row_index < len(actual_items) else None
        for field in TEXT_FIELDS:
            expected_value = _normalize_text(expected.get(field))
            if not expected_value:
                continue
            scored_fields += 1
            actual_value = _normalize_text(getattr(actual, field, "") if actual else "")
            if expected_value != actual_value:
                field_errors += 1
                error_fields.add(field)

        for field in DECIMAL_FIELDS:
            expected_value = _expected_decimal(expected.get(field))
            if expected_value is None:
                continue
            scored_fields += 1
            actual_value = getattr(actual, field, None) if actual else None
            if expected_value != actual_value:
                field_errors += 1
                error_fields.add(field)

    return QuoteUatCaseMetric(
        case_id=case_id,
        strategy=strategy,
        expected_item_count=len(expected_rows),
        actual_item_count=len(actual_items),
        scored_fields=scored_fields,
        field_errors=field_errors,
        error_fields=tuple(sorted(error_fields)),
        extraction_failed=extraction_failed,
    )


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
    strategy_counts = Counter(metric.strategy for metric in metrics)

    return {
        "total_confirmed_cases": total_cases,
        "minimum_case_target": minimum_cases,
        "minimum_case_target_met": total_cases >= minimum_cases,
        "extraction_failures": extraction_failures,
        "extraction_failure_rate": extraction_failures / total_cases if total_cases else None,
        "exact_item_count_cases": exact_item_count_cases,
        "exact_item_count_rate": exact_item_count_cases / total_cases if total_cases else None,
        "scored_fields": scored_fields,
        "field_errors": field_errors,
        "field_error_rate": field_errors / scored_fields if scored_fields else None,
        "strategy_counts": dict(sorted(strategy_counts.items())),
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
