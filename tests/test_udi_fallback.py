from __future__ import annotations

from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.services.mfds_udi import (
    MFDS_UDI_PRODUCT_INFO_BASE_URL,
    MFDS_UDI_PRODUCT_INFO_OPERATION,
    MfdsUdiCodeClient,
    MfdsUdiProductInfoClient,
    lookup_udi_with_fallback,
)

NOT_APPROVED = PublicDataClientError(
    "Public Data Portal request failed: HTTP 403 error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30"
)


def _page(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"items": list(items), "totalCount": len(items), "pageNo": 1, "numOfRows": 100},
        }
    }


class _Client:
    def __init__(self, result: dict[str, Any] | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        self.calls.append((base_url, endpoint, params))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


PRODUCT_ITEM = {
    "UDIDI_CD": "18800003462138",
    "PRDLST_NM": "환자 감시장치",
    "FOML_INFO": "M40",
    "PERMIT_NO": "제인 20-5001 호",
    "PRMSN_YMD": "2020-11-10",
    "MNFT_IPRT_ENTP_NM": "(주)메디아나",
}


def _run(product: _Client, code: _Client):
    return lookup_udi_with_fallback(
        "18800003462138",
        product_client=MfdsUdiProductInfoClient("x", client=product),
        code_client=MfdsUdiCodeClient("x", client=code),
    )


def test_product_info_service_answers_when_the_udi_code_service_is_not_approved() -> None:
    product, code = _Client(_page(PRODUCT_ITEM)), _Client(NOT_APPROVED)
    outcome = _run(product, code)
    assert outcome.state == "found"
    assert outcome.product_records[0].model_name == "M40"
    assert outcome.product_records[0].company_name == "(주)메디아나"
    assert product.calls == [
        (
            MFDS_UDI_PRODUCT_INFO_BASE_URL,
            MFDS_UDI_PRODUCT_INFO_OPERATION,
            {"UDIDI_CD": "18800003462138", "pageNo": 1, "numOfRows": 100},
        )
    ]
    assert code.calls == []  # not needed once the first service answered


def test_falls_back_to_the_udi_code_service_when_product_info_is_not_approved() -> None:
    code_item = {"UDIDI_CD": "18800003462138", "BSSH_NM": "업체", "INDT_DIVS_NM": "수입업"}
    outcome = _run(_Client(NOT_APPROVED), _Client(_page(code_item)))
    assert outcome.state == "found" and outcome.code_records[0].company_name == "업체"


def test_nothing_found_is_empty_only_when_a_service_really_answered() -> None:
    assert _run(_Client(_page()), _Client(NOT_APPROVED)).state == "empty"
    assert _run(_Client(NOT_APPROVED), _Client(_page())).state == "empty"


def test_both_services_not_approved_is_not_connected_never_not_found() -> None:
    outcome = _run(_Client(NOT_APPROVED), _Client(NOT_APPROVED))
    assert outcome.state == "not_connected"


def test_other_errors_are_failures_with_a_retry() -> None:
    outcome = _run(_Client(PublicDataClientError("HTTP 500 boom")), _Client(NOT_APPROVED))
    assert outcome.state == "failed" and "500" in outcome.error
