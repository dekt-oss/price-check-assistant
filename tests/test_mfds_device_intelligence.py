from __future__ import annotations

from typing import Any

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.services.mfds_device_intelligence import (
    MFDS_BUSINESS_LICENSE_BASE_URL,
    MFDS_BUSINESS_LICENSE_OPERATION,
    MFDS_MODEL_INFO_BASE_URL,
    MFDS_MODEL_INFO_OPERATION,
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
    parse_business_record,
    parse_model_record,
    resolve_exact_model_identity,
    unwrap_mfds_page,
)


class StubClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        self.calls.append((base_url, endpoint, params))
        if not self.payloads:
            raise AssertionError("no stub payload left")
        return self.payloads.pop(0)


def _page(items: list[dict[str, Any]], *, total: int | None = None) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": items},
                "pageNo": 1,
                "numOfRows": 100,
                "totalCount": total if total is not None else len(items),
            },
        }
    }


def test_unwrap_mfds_page_accepts_single_item_object() -> None:
    payload = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": {"PRDLST_NM": "심장충격기"}},
                "totalCount": 1,
                "pageNo": 1,
                "numOfRows": 10,
            },
        }
    }

    page = unwrap_mfds_page(payload)

    assert page.total_count == 1
    assert page.items == ({"PRDLST_NM": "심장충격기"},)


def test_unwrap_mfds_page_fails_closed_on_error_header() -> None:
    payload = {
        "response": {
            "header": {"resultCode": "10", "resultMsg": "INVALID REQUEST"},
            "body": {},
        }
    }

    with pytest.raises(PublicDataClientError, match="resultCode=10"):
        unwrap_mfds_page(payload)


def test_parse_model_record_marks_active_domestic_candidate() -> None:
    record = parse_model_record(
        {
            "MDEQ_PRDLST_SN": "123",
            "INST_AREA_DIVS_NM": "서울청",
            "INDT_NM": "수입업",
            "PRMSN_DCLR_DIVS_NM": "허가",
            "MEDDEV_ITEM_NO": "수허 00-0000",
            "PRDLST_NM": "심장충격기",
            "PRMSN_YMD": "2020-01-02",
            "RTRCN_DSCTN_DIVS_CD": "",
            "DSCTN_RTRCN_YMD": "",
            "PRDT_NM_INFO": "Example Device",
            "TYPE_INFO": "MODEL-1",
            "EXPORT_YN": "아니오",
        }
    )

    assert record.product_name == "심장충격기"
    assert record.model_name == "MODEL-1"
    assert record.permit_date is not None
    assert record.active_for_domestic_candidate is True


def test_parse_model_record_excludes_cancelled_or_export_only_candidate() -> None:
    cancelled = parse_model_record(
        {
            "PRDLST_NM": "심장충격기",
            "TYPE_INFO": "MODEL-X",
            "RTRCN_DSCTN_DIVS_CD": "취하",
            "EXPORT_YN": "아니오",
        }
    )
    export_only = parse_model_record(
        {
            "PRDLST_NM": "심장충격기",
            "TYPE_INFO": "MODEL-Y",
            "EXPORT_YN": "예",
        }
    )

    assert cancelled.active_for_domestic_candidate is False
    assert export_only.active_for_domestic_candidate is False


def test_model_client_uses_official_product_name_filter() -> None:
    stub = StubClient([_page([{"PRDLST_NM": "심장충격기", "TYPE_INFO": "MODEL-1"}])])
    client = MfdsModelInfoClient("dummy", client=stub)

    records = client.search_models("심장충격기")

    assert records[0].model_name == "MODEL-1"
    base_url, operation, params = stub.calls[0]
    assert base_url == MFDS_MODEL_INFO_BASE_URL
    assert operation == MFDS_MODEL_INFO_OPERATION
    assert params["PRDLST_NM"] == "심장충격기"


def test_model_client_paginates_until_total_count() -> None:
    first = _page(
        [{"PRDLST_NM": "품목", "TYPE_INFO": f"M{i}"} for i in range(100)],
        total=101,
    )
    first["response"]["body"]["pageNo"] = 1
    second = _page([{"PRDLST_NM": "품목", "TYPE_INFO": "M100"}], total=101)
    second["response"]["body"]["pageNo"] = 2
    stub = StubClient([first, second])
    client = MfdsModelInfoClient("dummy", client=stub)

    records = client.search_models("품목", max_pages=3, num_of_rows=100)

    assert len(records) == 101
    assert stub.calls[1][2]["pageNo"] == 2


def test_parse_business_record_combines_address_and_exposes_status() -> None:
    record = parse_business_record(
        {
            "ENTRPS": "예시메디칼",
            "INDUTY_TYPE": "수입업",
            "BIZ_STTUS": "",
            "PRMISN_DT": "20200102",
            "ADRES1": "부산광역시",
            "ADRES2": "해운대구 1",
            "MEDDEV_ENTP_NO": "제123호",
        }
    )

    assert record.company_name == "예시메디칼"
    assert record.address == "부산광역시 해운대구 1"
    assert record.is_active is True


def test_business_client_uses_official_company_filter() -> None:
    stub = StubClient(
        [
            _page(
                [
                    {
                        "ENTRPS": "예시메디칼",
                        "INDUTY_TYPE": "판매업",
                        "BIZ_STTUS": "",
                    }
                ]
            )
        ]
    )
    client = MfdsBusinessLicenseClient("dummy", client=stub)

    records = client.search_company("예시메디칼")

    assert records[0].industry_type == "판매업"
    base_url, operation, params = stub.calls[0]
    assert base_url == MFDS_BUSINESS_LICENSE_BASE_URL
    assert operation == MFDS_BUSINESS_LICENSE_OPERATION
    assert params["Entrps"] == "예시메디칼"


def test_exact_model_identity_uses_existing_normalized_exact_contract() -> None:
    records = (
        parse_model_record(
            {
                "PRDLST_NM": "심장충격기",
                "TYPE_INFO": "Efficia DFM-100",
                "MEDDEV_ITEM_NO": "수허 12-3456",
                "EXPORT_YN": "아니오",
            }
        ),
    )

    resolution = resolve_exact_model_identity(records, "efficia dfm100")

    assert resolution.confirmed is True
    assert resolution.ambiguous is False
    assert resolution.exact_matches[0].permit_number == "수허 12-3456"


def test_exact_model_identity_rejects_substring_and_semantic_near_match() -> None:
    records = (
        parse_model_record(
            {
                "PRDLST_NM": "심장충격기",
                "TYPE_INFO": "Efficia DFM100 Plus",
                "MEDDEV_ITEM_NO": "수허 12-9999",
            }
        ),
    )

    resolution = resolve_exact_model_identity(records, "Efficia DFM100")

    assert resolution.confirmed is False
    assert resolution.exact_matches == ()


def test_exact_model_identity_marks_multiple_permits_as_ambiguous() -> None:
    records = tuple(
        parse_model_record(
            {
                "PRDLST_NM": "심장충격기",
                "TYPE_INFO": "MODEL-1",
                "MEDDEV_ITEM_NO": permit,
            }
        )
        for permit in ("수허 10-0001", "수허 10-0002")
    )

    resolution = resolve_exact_model_identity(records, "MODEL 1")

    assert resolution.confirmed is True
    assert resolution.ambiguous is True
    assert len(resolution.exact_matches) == 2
