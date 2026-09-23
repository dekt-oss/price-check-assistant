import sqlite3

from purchase_price.services.mfds_identity_index import (
    lookup_identity,
    lookup_same_product,
    parse_mfds_product_info_record,
    upsert_identity_records,
)


def _record(**overrides):
    payload = {
        "UDIDI_CD": "08800000000001",
        "PRDLST_NM": "심장충격기",
        "MDEQ_CLSF_NO": "A17010.01",
        "CLSF_NO_GRAD_CD": "3",
        "PERMIT_NO": "수허 24-1234 호",
        "PRMSN_YMD": "20240101",
        "FOML_INFO": "CN-6000",
        "PRDT_NM_INFO": "CN-6000",
        "MNFT_IPRT_ENTP_NM": "등록업체A",
    }
    payload.update(overrides)
    return parse_mfds_product_info_record(payload, source_payload_sha256="a" * 64)


def test_identity_index_supports_permit_model_company_and_product_reverse_lookup() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_identity_records(
        connection,
        [
            _record(),
            _record(
                UDIDI_CD="08800000000002",
                PERMIT_NO="수허 24-1234 호",
                FOML_INFO="CN-6000 Plus",
            ),
        ],
    )
    connection.commit()

    permit = lookup_identity(connection, "수허24-1234호")
    assert permit.status == "success"
    assert permit.match_type == "permit"
    assert permit.model_names == ("CN-6000", "CN-6000 Plus")
    assert permit.companies == ("등록업체A",)

    model = lookup_identity(connection, "CN-6000")
    assert model.match_type == "model"
    assert model.permit_numbers == ("수허 24-1234 호",)

    company = lookup_identity(connection, "등록업체A")
    assert company.match_type == "company"
    assert len(company.records) == 2

    same_product = lookup_same_product(connection, "심장충격기")
    assert len(same_product) == 2


def test_identity_index_does_not_fuzzy_match_model_or_permit() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_identity_records(connection, [_record()])
    connection.commit()

    assert lookup_identity(connection, "CN-600").status == "success_0"
    assert lookup_identity(connection, "24-123").status == "success_0"


def test_identity_upsert_refreshes_same_identity_without_duplicate() -> None:
    connection = sqlite3.connect(":memory:")
    upsert_identity_records(connection, [_record(PRDT_NM_INFO="old")])
    connection.commit()
    upsert_identity_records(connection, [_record(PRDT_NM_INFO="new")])
    connection.commit()

    rows = lookup_identity(connection, "CN-6000").records
    assert len(rows) == 1
    assert rows[0].trade_name == "new"
