from purchase_price.scripts.diagnose_r2_zero_recall import (
    _target_code_status,
    classify_zero_cause,
)
from purchase_price.services.g2b_product_mapping import G2BProductMapping


def _mapping(*, verified: bool = True, code: str | None = "4217210101"):
    return G2BProductMapping(
        model_name="M1",
        product_name="P1",
        detail_product_name="detail" if code else None,
        detail_product_code=code,
        mapping_status="verified" if verified else "unverified",
        evidence_url=None,
        notes=None,
    )


def test_negative_control_is_explicit() -> None:
    assert (
        classify_zero_cause(
            case_id="example_negative_control",
            mapping=None,
            target_code_status="not_applicable",
            current_detail_rows=0,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "EXPECTED_NEGATIVE_CONTROL"
    )


def test_missing_and_unverified_mapping_are_distinct() -> None:
    assert (
        classify_zero_cause(
            case_id="missing",
            mapping=None,
            target_code_status="not_applicable",
            current_detail_rows=0,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "MAPPING_NOT_REGISTERED"
    )
    assert (
        classify_zero_cause(
            case_id="unverified",
            mapping=_mapping(verified=False, code=None),
            target_code_status="not_applicable",
            current_detail_rows=0,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "MAPPING_UNVERIFIED"
    )


def test_target_coverage_and_historical_pending_are_distinct() -> None:
    mapping = _mapping()
    assert (
        classify_zero_cause(
            case_id="coverage",
            mapping=mapping,
            target_code_status="not_in_snapshot",
            current_detail_rows=0,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "TARGET_CODE_COVERAGE_GAP"
    )
    assert (
        classify_zero_cause(
            case_id="pending",
            mapping=mapping,
            target_code_status="pending",
            current_detail_rows=0,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "HISTORICAL_TARGET_NOT_COMPLETE"
    )


def test_collected_class_distinguishes_no_rows_model_absence_and_matcher_gap() -> None:
    mapping = _mapping()
    assert (
        classify_zero_cause(
            case_id="no_rows",
            mapping=mapping,
            target_code_status="collected",
            current_detail_rows=0,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "MAPPED_CLASS_NO_SERVING_ROWS"
    )
    assert (
        classify_zero_cause(
            case_id="not_observed",
            mapping=mapping,
            target_code_status="collected",
            current_detail_rows=10,
            global_exact_model_rows=0,
            global_title_literal_rows=0,
        )
        == "MAPPED_CLASS_MODEL_NOT_OBSERVED"
    )
    assert (
        classify_zero_cause(
            case_id="matcher",
            mapping=mapping,
            target_code_status="collected",
            current_detail_rows=10,
            global_exact_model_rows=1,
            global_title_literal_rows=0,
        )
        == "MATCHER_OR_IDENTITY_RULE_GAP"
    )


def test_target_code_status_uses_cursor_position() -> None:
    codes = ("4100000001", "4200000001", "4300000001")
    assert (
        _target_code_status(
            "4100000001",
            target_codes=codes,
            collection_cursor_index=1,
            backfill_complete=False,
        )
        == "collected"
    )
    assert (
        _target_code_status(
            "4200000001",
            target_codes=codes,
            collection_cursor_index=1,
            backfill_complete=False,
        )
        == "partial"
    )
    assert (
        _target_code_status(
            "4300000001",
            target_codes=codes,
            collection_cursor_index=1,
            backfill_complete=False,
        )
        == "pending"
    )
    assert (
        _target_code_status(
            "9999999999",
            target_codes=codes,
            collection_cursor_index=1,
            backfill_complete=False,
        )
        == "not_in_snapshot"
    )
