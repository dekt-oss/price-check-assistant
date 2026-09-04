"""A failed data.go.kr call must never look like a product with no procurement history.

The G2B shopping service answers a malformed request with a `nkoneps.com.response.ResponseError`
envelope rather than the documented `response` / `OpenAPI_ServiceResponse` shapes. Because
`unwrap_g2b_page()` falls back to the payload itself when there is no `response` key, that
envelope produced an empty page with no error: the user surface reported "no evidence found"
for a call that had actually failed. These tests pin the fail-closed behaviour.
"""

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError, _payload_error_fields
from purchase_price.collectors.g2b_shopping import unwrap_g2b_page

# Captured from a live 2026-09-04 call that omitted required parameters.
LIVE_ERROR_PAYLOAD = {
    "nkoneps.com.response.ResponseError": {
        "header": {"resultCode": "08", "resultMsg": "필수값 입력 에러"}
    }
}


def test_response_error_envelope_is_not_reported_as_an_empty_page() -> None:
    with pytest.raises(PublicDataClientError) as excinfo:
        unwrap_g2b_page(LIVE_ERROR_PAYLOAD)

    assert "08" in str(excinfo.value)
    assert "필수값 입력 에러" in str(excinfo.value)


def test_response_error_envelope_without_a_known_header_still_fails_closed() -> None:
    with pytest.raises(PublicDataClientError):
        unwrap_g2b_page({"nkoneps.com.response.ResponseError": {"unexpected": "shape"}})


def test_successful_page_is_still_unwrapped_normally() -> None:
    page = unwrap_g2b_page(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {"items": [{"prdctIdntNo": "1"}], "totalCount": 1, "pageNo": 1},
            }
        }
    )

    assert len(page.items) == 1
    assert page.total_count == 1


def test_client_error_extraction_recognizes_the_response_error_envelope() -> None:
    """Without this the client treats a failed call as a successful payload."""

    err_msg, auth_msg, code = _payload_error_fields(LIVE_ERROR_PAYLOAD)

    assert code == "08"
    assert err_msg == "필수값 입력 에러"
    assert auth_msg is None


def test_client_error_extraction_still_ignores_a_successful_response() -> None:
    fields = _payload_error_fields(
        {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}}}
    )

    assert fields == (None, None, None)
