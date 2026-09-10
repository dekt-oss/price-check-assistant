from __future__ import annotations

from datetime import date

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataTransportError
from purchase_price.scripts.probe_db_collection_feasibility import (
    DEVELOPMENT_DAILY_TRAFFIC_LIMIT,
    GOLDEN_DETAIL_CODES,
    _budget,
    _safe_text,
    _track_b_params,
    classify_exception,
)


def test_safe_text_redacts_service_key_query_value() -> None:
    text = _safe_text("GET /x?foo=1&serviceKey=SECRET%2BVALUE&bar=2")
    assert "SECRET" not in text
    assert "serviceKey=***" in text


def test_exception_classification_keeps_zero_result_out_of_error_path() -> None:
    assert classify_exception(PublicDataClientError("resultCode=08 필수값 입력 에러")) == "INVALID_PARAMETER"
    assert classify_exception(PublicDataClientError("SERVICE_ACCESS_DENIED_ERROR code=20")) == "AUTH_ERROR"
    assert classify_exception(PublicDataClientError("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR code=22")) == "RATE_LIMIT"
    assert classify_exception(PublicDataTransportError("connect timeout")) == "TRANSPORT_ERROR"
    assert classify_exception(PublicDataClientError("unexpected upstream envelope")) == "SOURCE_ERROR"


def test_track_b_exact_code_contract_uses_10_digit_selector_and_can_omit_final_filter() -> None:
    params = _track_b_params(
        begin=date(2025, 9, 11),
        end=date(2026, 9, 10),
        detail_code=GOLDEN_DETAIL_CODES[0],
        rows=999,
    )
    assert params["dtilPrdctClsfcNo"] == "4110449801"
    assert params["inqryBgnDate"] == "20250911"
    assert params["inqryEndDate"] == "20260910"
    assert params["numOfRows"] == 999
    assert "dtilPrdctClsfcNoNm" not in params
    assert "fnlCntrctDlvrReqChgOrdYn" not in params


def test_budget_never_fills_unverified_tracks_with_guesses() -> None:
    budget = _budget(
        {"estimated_pages_per_7d_window": 4},
        {
            "max_tested_num_of_rows": 999,
            "golden_counts": {code: 1 for code in GOLDEN_DETAIL_CODES},
        },
    )
    assert budget["development_daily_limit_documented"] == DEVELOPMENT_DAILY_TRAFFIC_LIMIT
    assert budget["track_a_30d_calls_if_daily_7d_replay"] == 120
    assert budget["track_b_golden_7_code_one_year_backfill_calls"] == 7
    assert budget["track_c_30d_calls"] == "미검증"
    assert budget["unit10_full_dictionary_calls"] == "미검증"
    assert budget["measured_subtotal_excluding_unverified_tracks"] == 127
