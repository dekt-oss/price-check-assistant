from __future__ import annotations

from decimal import Decimal

from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.services.quote_uat_review import (
    build_redacted_uat_summary,
    compare_review_rows,
    quote_item_to_review_row,
    redacted_uat_summary_json,
)


def _item(**overrides: object) -> QuoteItem:
    values: dict[str, object] = {
        "source_sheet": "PDF 1페이지 표1",
        "source_row": 1,
        "product_name": "가스 마취기",
        "manufacturer": "Maquet",
        "model_name": "FLOW-C",
        "specification": "Flow-C",
        "quantity": Decimal("1"),
        "unit": "set",
        "unit_price": Decimal("66000000"),
        "total_amount": Decimal("66000000"),
        "vat_status": "포함",
    }
    values.update(overrides)
    return QuoteItem(**values)  # type: ignore[arg-type]


def test_quote_item_to_review_row_preserves_review_fields() -> None:
    row = quote_item_to_review_row(_item())

    assert row == {
        "product_name": "가스 마취기",
        "manufacturer": "Maquet",
        "model_name": "FLOW-C",
        "specification": "Flow-C",
        "quantity": 1.0,
        "unit": "set",
        "unit_price": 66000000.0,
        "total_amount": 66000000.0,
        "vat_status": "포함",
    }


def test_compare_review_rows_passes_exact_ground_truth() -> None:
    actual = (_item(),)
    expected = (quote_item_to_review_row(actual[0]),)

    metric = compare_review_rows(
        case_id="UAT-001",
        strategy="PDF 표 선/셀 구조",
        actual_items=actual,
        expected_rows=expected,
    )

    assert metric.status == "PASS"
    assert metric.exact_item_count is True
    assert metric.scored_fields == 9
    assert metric.field_errors == 0
    assert metric.error_fields == ()


def test_compare_review_rows_flags_price_and_missing_item() -> None:
    actual = (_item(),)
    expected = (
        {
            **quote_item_to_review_row(actual[0]),
            "unit_price": 65000000,
        },
        {
            "product_name": "Patient Monitor",
            "manufacturer": "Acme",
            "model_name": "PM-2",
            "specification": "15 inch",
            "quantity": 1,
            "unit": "set",
            "unit_price": 10000000,
            "total_amount": 10000000,
            "vat_status": "포함",
        },
    )

    metric = compare_review_rows(
        case_id="UAT-002",
        strategy="PDF 단어 X/Y 좌표 재구성",
        actual_items=actual,
        expected_rows=expected,
    )

    assert metric.status == "REVIEW_REQUIRED"
    assert metric.exact_item_count is False
    assert "unit_price" in metric.error_fields
    assert "product_name" in metric.error_fields
    assert metric.field_errors > 1


def test_blank_expected_fields_are_not_scored() -> None:
    metric = compare_review_rows(
        case_id="UAT-003",
        strategy="Excel(.xlsx) 헤더/행 추출",
        actual_items=(_item(),),
        expected_rows=({"product_name": "가스 마취기"},),
    )

    assert metric.scored_fields == 1
    assert metric.field_errors == 0
    assert metric.status == "PASS"


def test_extraction_failure_remains_failure_even_without_field_errors() -> None:
    metric = compare_review_rows(
        case_id="UAT-004",
        strategy="PDF 텍스트 레이어 없음(OCR 대상)",
        actual_items=(),
        expected_rows=(),
        extraction_failed=True,
    )

    assert metric.status == "EXTRACTION_FAILED"
    assert metric.extraction_failed is True


def test_redacted_summary_contains_no_quote_values_or_filenames() -> None:
    sensitive_product = "SECRET-MEDICAL-DEVICE"
    sensitive_file = "hospital-private-quote.pdf"
    sensitive_price = "987654321"
    actual = (
        _item(
            product_name=sensitive_product,
            unit_price=Decimal(sensitive_price),
            total_amount=Decimal(sensitive_price),
        ),
    )
    expected = (quote_item_to_review_row(actual[0]),)
    metric = compare_review_rows(
        case_id="UAT-005",
        strategy="PDF 표 선/셀 구조",
        actual_items=actual,
        expected_rows=expected,
    )

    summary = build_redacted_uat_summary((metric,), minimum_cases=5)
    payload = redacted_uat_summary_json((metric,), minimum_cases=5)

    assert summary["total_confirmed_cases"] == 1
    assert summary["minimum_case_target_met"] is False
    assert sensitive_product not in payload
    assert sensitive_price not in payload
    assert sensitive_file not in payload
    assert "UAT-005" in payload
