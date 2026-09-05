from purchase_price.scripts.run_mfds_live_validation import build_validation_report
from purchase_price.services.mfds_device_intelligence import (
    parse_business_record,
    parse_model_record,
)


def _model(
    *,
    permit: str,
    model: str = "MODEL-1",
    cancellation: str = "",
    export: str = "아니오",
):
    return parse_model_record(
        {
            "INDT_NM": "수입업",
            "MEDDEV_ITEM_NO": permit,
            "PRDLST_NM": "심장충격기",
            "TYPE_INFO": model,
            "RTRCN_DSCTN_DIVS_CD": cancellation,
            "EXPORT_YN": export,
        }
    )


def test_exact_active_expectation_requires_unambiguous_active_identity() -> None:
    report = build_validation_report(
        product_name="심장충격기",
        model_name="MODEL-1",
        company_name="",
        model_records=(_model(permit="수허 00-0001"),),
        business_records=(),
        expectation="exact-active",
    )

    assert report["expectation_met"] is True
    assert report["exact_identity_confirmed"] is True
    assert report["exact_identity_ambiguous"] is False
    assert report["active_exact_count"] == 1
    assert report["inactive_or_export_exact_count"] == 0


def test_exact_ambiguous_expectation_requires_multiple_permits() -> None:
    report = build_validation_report(
        product_name="심장충격기",
        model_name="MODEL-1",
        company_name="",
        model_records=(
            _model(permit="수허 00-0001"),
            _model(permit="수허 00-0002"),
        ),
        business_records=(),
        expectation="exact-ambiguous",
    )

    assert report["expectation_met"] is True
    assert report["exact_identity_ambiguous"] is True
    assert report["exact_match_count"] == 2


def test_exact_inactive_expectation_rejects_active_candidate() -> None:
    inactive = build_validation_report(
        product_name="심장충격기",
        model_name="MODEL-1",
        company_name="",
        model_records=(_model(permit="수허 00-0001", cancellation="취하"),),
        business_records=(),
        expectation="exact-inactive",
    )
    mixed = build_validation_report(
        product_name="심장충격기",
        model_name="MODEL-1",
        company_name="",
        model_records=(
            _model(permit="수허 00-0001", cancellation="취하"),
            _model(permit="수허 00-0001"),
        ),
        business_records=(),
        expectation="exact-inactive",
    )

    assert inactive["expectation_met"] is True
    assert inactive["active_exact_count"] == 0
    assert inactive["inactive_or_export_exact_count"] == 1
    assert mixed["expectation_met"] is False


def test_api_only_treats_zero_records_as_success_not_failure() -> None:
    report = build_validation_report(
        product_name="심장충격기",
        model_name="",
        company_name="",
        model_records=(),
        business_records=(),
        expectation="api-only",
    )

    assert report["expectation_met"] is True
    assert report["model_lookup_status"] == "success_0"
    assert report["exact_identity_confirmed"] is False
    assert "안전" in report["safety_note"]


def test_business_lookup_reports_active_status_without_calling_it_official_distributor() -> None:
    business = parse_business_record(
        {
            "ENTRPS": "예시메디칼",
            "INDUTY_TYPE": "수입업",
            "BIZ_STTUS": "영업",
            "MEDDEV_ENTP_NO": "12345",
        }
    )
    report = build_validation_report(
        product_name="심장충격기",
        model_name="",
        company_name="예시메디칼",
        model_records=(),
        business_records=(business,),
        expectation="api-only",
    )

    assert report["business_lookup_status"] == "success"
    assert report["active_business_record_count"] == 1
    assert report["business_matches"][0]["industry_type"] == "수입업"
