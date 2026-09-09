from decimal import Decimal

from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.services.quote_uat_review import (
    build_redacted_uat_summary,
    compare_review_rows,
    evaluate_uat_release_gate,
    quote_item_to_review_row,
    redacted_uat_summary_json,
)


def _item(**overrides: object) -> QuoteItem:
    values: dict[str, object] = {
        "source_sheet": "PDF 1페이지",
        "source_row": 1,
        "product_name": "가스 마취기",
        "manufacturer": "Maquet",
        "model_name": "FLOW-C",
        "specification": "FLOW-C",
        "quantity": Decimal("1"),
        "unit": "set",
        "unit_price": Decimal("66000000"),
        "total_amount": Decimal("66000000"),
        "vat_status": "포함",
        "delivery_condition": "배송 포함",
        "installation_condition": "설치 포함",
        "option_condition": "Desflurane",
        "warranty_condition": "3년",
        "maintenance_condition": "별도 계약",
        "other_conditions": "납기 30일",
    }
    values.update(overrides)
    return QuoteItem(**values)  # type: ignore[arg-type]


def test_exact_commercial_ground_truth_is_scored_and_passes() -> None:
    actual = _item()
    expected = quote_item_to_review_row(actual)

    metric = compare_review_rows(
        case_id="COMM-1",
        strategy="pdf_commercial",
        actual_items=(actual,),
        expected_rows=(expected,),
    )

    assert metric.status == "PASS"
    assert metric.commercial_scored_fields == 6
    assert metric.field_errors == 0
    assert metric.error_fields == ()


def test_warranty_conflict_is_counted_as_commercial_field_error() -> None:
    actual = _item(warranty_condition="1년")
    expected = quote_item_to_review_row(_item(warranty_condition="3년"))

    metric = compare_review_rows(
        case_id="COMM-2",
        strategy="pdf_commercial",
        actual_items=(actual,),
        expected_rows=(expected,),
    )

    assert metric.status == "REVIEW_REQUIRED"
    assert metric.commercial_scored_fields == 6
    assert metric.field_errors == 1
    assert metric.error_fields == ("warranty_condition",)


def test_blank_expected_commercial_fields_are_not_scored() -> None:
    actual = _item()
    expected = {
        "product_name": actual.product_name,
        "model_name": actual.model_name,
        "unit_price": float(actual.unit_price or 0),
    }

    metric = compare_review_rows(
        case_id="COMM-3",
        strategy="pdf_commercial",
        actual_items=(actual,),
        expected_rows=(expected,),
    )

    assert metric.status == "PASS"
    assert metric.commercial_scored_fields == 0
    gate = evaluate_uat_release_gate((metric,), minimum_cases=1, required_strategies=frozenset({"pdf_commercial"}))
    assert gate["release_ready"] is False
    assert gate["missing_strategies"] == ["pdf_commercial"]
    assert "pdf_commercial requires scored commercial ground truth" in gate["blockers"]


def test_one_scored_commercial_case_qualifies_commercial_strategy_coverage() -> None:
    metric = compare_review_rows(
        case_id="COMM-4",
        strategy="pdf_commercial",
        actual_items=(_item(),),
        expected_rows=(quote_item_to_review_row(_item()),),
    )

    gate = evaluate_uat_release_gate(
        (metric,),
        minimum_cases=1,
        required_strategies=frozenset({"pdf_commercial"}),
    )

    assert gate["release_ready"] is True
    assert gate["covered_strategies"] == ["pdf_commercial"]


def test_redacted_output_never_contains_commercial_condition_values() -> None:
    secrets = (
        "SECRET-DELIVERY-CONDITION",
        "SECRET-INSTALL-CONDITION",
        "SECRET-OPTION-CONDITION",
        "SECRET-WARRANTY-CONDITION",
        "SECRET-MAINTENANCE-CONDITION",
        "SECRET-OTHER-CONDITION",
    )
    actual = _item(
        delivery_condition=secrets[0],
        installation_condition=secrets[1],
        option_condition=secrets[2],
        warranty_condition=secrets[3],
        maintenance_condition=secrets[4],
        other_conditions=secrets[5],
    )
    metric = compare_review_rows(
        case_id="COMM-PRIVATE",
        strategy="pdf_commercial",
        actual_items=(actual,),
        expected_rows=(quote_item_to_review_row(actual),),
    )

    summary = build_redacted_uat_summary((metric,), minimum_cases=1)
    payload = redacted_uat_summary_json((metric,), minimum_cases=1)

    assert summary["commercial_scored_fields"] == 6
    assert "commercial_scored_fields" in payload
    for secret in secrets:
        assert secret not in payload
