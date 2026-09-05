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
        processing_seconds=0.25,
        review_seconds=12.0,
    )

    assert metric.status == "PASS"
    assert metric.exact_item_count is True
    assert metric.matched_item_count == 1
    assert metric.false_positive_item_count == 0
    assert metric.false_negative_item_count == 0
    assert metric.item_precision == 1.0
    assert metric.item_recall == 1.0
    assert metric.scored_fields == 9
    assert metric.field_errors == 0
    assert metric.error_fields == ()
    assert metric.processing_seconds == 0.25
    assert metric.review_seconds == 12.0


def test_compare_review_rows_separates_price_error_from_missing_item() -> None:
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
    assert metric.matched_item_count == 1
    assert metric.false_positive_item_count == 0
    assert metric.false_negative_item_count == 1
    assert metric.field_errors == 1
    assert metric.error_fields == ("unit_price",)


def test_alignment_avoids_cascading_field_errors_when_first_actual_item_is_extra() -> None:
    expected_a = _item(product_name="A", model_name="A-1", specification="A-spec")
    expected_b = _item(
        product_name="B",
        model_name="B-1",
        specification="B-spec",
        unit_price=Decimal("200"),
        total_amount=Decimal("200"),
    )
    extra = _item(
        product_name="WRONG",
        manufacturer="Other",
        model_name="X-9",
        specification="X-spec",
        unit_price=Decimal("999"),
        total_amount=Decimal("999"),
    )

    metric = compare_review_rows(
        case_id="UAT-ALIGN-EXTRA",
        strategy="PDF 로컬 OCR(Tesseract kor+eng)",
        actual_items=(extra, expected_a, expected_b),
        expected_rows=(
            quote_item_to_review_row(expected_a),
            quote_item_to_review_row(expected_b),
        ),
    )

    assert metric.matched_item_count == 2
    assert metric.false_positive_item_count == 1
    assert metric.false_negative_item_count == 0
    assert metric.field_errors == 0
    assert metric.item_precision == 2 / 3
    assert metric.item_recall == 1.0


def test_alignment_avoids_cascading_field_errors_when_expected_item_is_missing() -> None:
    expected_a = _item(product_name="A", model_name="A-1", specification="A-spec")
    expected_b = _item(
        product_name="B",
        model_name="B-1",
        specification="B-spec",
        unit_price=Decimal("200"),
        total_amount=Decimal("200"),
    )

    metric = compare_review_rows(
        case_id="UAT-ALIGN-MISSING",
        strategy="Excel(.xlsx) 헤더/행 추출",
        actual_items=(expected_b,),
        expected_rows=(
            quote_item_to_review_row(expected_a),
            quote_item_to_review_row(expected_b),
        ),
    )

    assert metric.matched_item_count == 1
    assert metric.false_positive_item_count == 0
    assert metric.false_negative_item_count == 1
    assert metric.field_errors == 0
    assert metric.item_precision == 1.0
    assert metric.item_recall == 0.5


def test_unrelated_equal_count_rows_are_fp_and_fn_not_false_field_alignment() -> None:
    actual = _item(
        product_name="WRONG",
        manufacturer="Other",
        model_name="X-9",
        specification="X-spec",
        quantity=Decimal("7"),
        unit="box",
        unit_price=Decimal("999"),
        total_amount=Decimal("6993"),
        vat_status="별도",
    )
    expected = _item(
        product_name="Expected",
        manufacturer="Expected Co",
        model_name="E-1",
        specification="E-spec",
        quantity=Decimal("1"),
        unit="set",
        unit_price=Decimal("100"),
        total_amount=Decimal("100"),
        vat_status="포함",
    )

    metric = compare_review_rows(
        case_id="UAT-UNRELATED",
        strategy="PDF 텍스트 fallback",
        actual_items=(actual,),
        expected_rows=(quote_item_to_review_row(expected),),
    )

    assert metric.exact_item_count is True
    assert metric.matched_item_count == 0
    assert metric.false_positive_item_count == 1
    assert metric.false_negative_item_count == 1
    assert metric.scored_fields == 0
    assert metric.field_errors == 0
    assert metric.status == "REVIEW_REQUIRED"


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
        strategy="PDF OCR 실행 불가",
        actual_items=(),
        expected_rows=(),
        extraction_failed=True,
        processing_seconds=1.5,
    )

    assert metric.status == "EXTRACTION_FAILED"
    assert metric.extraction_failed is True
    assert metric.processing_seconds == 1.5


def test_redacted_summary_reports_fp_fn_precision_recall_and_strategy_timing() -> None:
    first = compare_review_rows(
        case_id="UAT-005",
        strategy="PDF 로컬 OCR(Tesseract kor+eng)",
        actual_items=(_item(),),
        expected_rows=(quote_item_to_review_row(_item()),),
        processing_seconds=2.0,
        review_seconds=20.0,
    )
    second = compare_review_rows(
        case_id="UAT-006",
        strategy="PDF 로컬 OCR(Tesseract kor+eng)",
        actual_items=(),
        expected_rows=(quote_item_to_review_row(_item()),),
        processing_seconds=3.0,
        review_seconds=40.0,
    )

    summary = build_redacted_uat_summary((first, second), minimum_cases=2)
    strategy = summary["strategy_metrics"]["PDF 로컬 OCR(Tesseract kor+eng)"]  # type: ignore[index]

    assert summary["minimum_case_target_met"] is True
    assert summary["matched_items"] == 1
    assert summary["false_positive_items"] == 0
    assert summary["false_negative_items"] == 1
    assert summary["item_precision"] == 1.0
    assert summary["item_recall"] == 0.5
    assert summary["average_processing_seconds"] == 2.5
    assert summary["total_review_seconds"] == 60.0
    assert summary["average_review_seconds"] == 30.0
    assert strategy["cases"] == 2
    assert strategy["false_negative_items"] == 1
    assert strategy["item_recall"] == 0.5
    assert strategy["average_processing_seconds"] == 2.5


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
        case_id="UAT-007",
        strategy="PDF 표 선/셀 구조",
        actual_items=actual,
        expected_rows=expected,
        processing_seconds=0.5,
        review_seconds=10.0,
    )

    summary = build_redacted_uat_summary((metric,), minimum_cases=5)
    payload = redacted_uat_summary_json((metric,), minimum_cases=5)

    assert summary["total_confirmed_cases"] == 1
    assert summary["minimum_case_target_met"] is False
    assert sensitive_product not in payload
    assert sensitive_price not in payload
    assert sensitive_file not in payload
    assert "UAT-007" in payload
