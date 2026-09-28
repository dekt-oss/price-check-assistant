from __future__ import annotations

import sqlite3

from purchase_price.domain import (
    IdentityEvidenceStatus,
    MfdsItemAuthorizationType,
    PriceEvidenceStatus,
    SafetyEvidenceStatus,
)
from purchase_price.services.mfds_identity_index import (
    classify_mfds_item_number,
    lookup_identity,
    parse_mfds_product_info_record,
    upsert_identity_records,
)
from purchase_price.services.safety_support import build_manual_safety_check_state
from purchase_price.services.track_b_db_quote_comparison import TrackBQuoteComparison


def _identity_record(
    *,
    permit_number: str,
    model: str,
    company: str,
    udi: str,
    product: str = "채혈기",
):
    return parse_mfds_product_info_record(
        {
            "UDIDI_CD": udi,
            "PRDLST_NM": product,
            "MDEQ_CLSF_NO": "A66020.01",
            "CLSF_NO_GRAD_CD": "1",
            "PERMIT_NO": permit_number,
            "PRMSN_YMD": "20220101",
            "FOML_INFO": model,
            "PRDT_NM_INFO": model,
            "MNFT_IPRT_ENTP_NM": company,
        },
        source_payload_sha256="a" * 64,
    )


def test_case_a_notification_identity_preserves_c101_and_udi() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_identity_records(
        connection,
        [
            _identity_record(
                permit_number="수신 22-2177호",
                model="C101",
                company="책임주체A",
                udi="08800000002177",
            )
        ],
    )
    connection.commit()

    result = lookup_identity(connection, "수신22-2177호")

    assert result.identity_status == IdentityEvidenceStatus.FOUND
    assert result.match_type == "permit"
    assert result.model_names == ("C101",)
    assert result.records[0].udi_di == "08800000002177"
    assert result.records[0].registered_company == "책임주체A"
    assert (
        classify_mfds_item_number(result.records[0].permit_number)
        == MfdsItemAuthorizationType.NOTIFICATION
    )


def test_case_b_multi_model_permit_keeps_every_registered_model() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_identity_records(
        connection,
        [
            _identity_record(
                permit_number="수신 22-2177호",
                model="C101",
                company="책임주체A",
                udi="UDI-1",
            ),
            _identity_record(
                permit_number="수신 22-2177호",
                model="C102",
                company="책임주체A",
                udi="UDI-2",
            ),
        ],
    )
    connection.commit()

    result = lookup_identity(connection, "수신22-2177호")

    assert result.identity_status == IdentityEvidenceStatus.FOUND
    assert result.model_names == ("C101", "C102")
    assert len(result.records) == 2


def test_case_c_exact_zero_keeps_zero_semantics_and_search_keys() -> None:
    result = TrackBQuoteComparison(
        status="success_0",
        candidates=(),
        examined=12,
        search_keys=("모델: C101", "품목: 채혈기"),
    )

    assert result.evidence_status == PriceEvidenceStatus.ZERO
    assert result.search_keys == ("모델: C101", "품목: 채혈기")


def test_case_d_track_b_unavailable_is_not_zero() -> None:
    result = TrackBQuoteComparison(
        status="unavailable",
        candidates=(),
        examined=0,
        search_keys=("모델: C101",),
    )

    assert result.evidence_status == PriceEvidenceStatus.UNAVAILABLE
    assert result.evidence_status != PriceEvidenceStatus.ZERO


def test_case_e_same_model_across_multiple_identity_keys_is_ambiguous() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_identity_records(
        connection,
        [
            _identity_record(
                permit_number="수신 22-2177호",
                model="C101",
                company="책임주체A",
                udi="UDI-1",
            ),
            _identity_record(
                permit_number="수신 24-9999호",
                model="C101",
                company="책임주체B",
                udi="UDI-2",
            ),
        ],
    )
    connection.commit()

    result = lookup_identity(connection, "C101")

    assert result.match_type == "model"
    assert result.identity_status == IdentityEvidenceStatus.AMBIGUOUS
    assert result.permit_numbers == ("수신 22-2177호", "수신 24-9999호")


def test_case_f_safety_without_connected_official_api_is_not_connected() -> None:
    state = build_manual_safety_check_state(
        model_name="C101",
        permit_numbers=["수신 22-2177호"],
    )

    assert state.evidence_status == SafetyEvidenceStatus.NOT_CONNECTED
    assert "식약처 품목번호: 수신 22-2177호" in state.search_keys
    assert "안전함" not in state.message
