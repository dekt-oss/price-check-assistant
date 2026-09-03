import httpx
import pytest

from purchase_price.clients.data_go_kr import (
    PublicDataPortalClient,
    _http_error_message,
    _payload_error_fields,
    normalize_service_key,
)


def test_service_key_is_required():
    with pytest.raises(ValueError, match="DATA_GO_KR_SERVICE_KEY"):
        PublicDataPortalClient("")


def test_base_url_is_required():
    client = PublicDataPortalClient("fake-key")
    with pytest.raises(ValueError, match="base URL"):
        client.get_json("", "endpoint")


def test_encoded_service_key_is_normalized_once():
    assert normalize_service_key("abc%2Bdef%2Fghi%3D") == "abc+def/ghi="
    assert PublicDataPortalClient("abc%2Bdef%2Fghi%3D").service_key == "abc+def/ghi="


def test_decoded_service_key_is_kept():
    assert normalize_service_key("abc+def/ghi=") == "abc+def/ghi="


def test_data_go_kr_auth_error_is_sanitized():
    secret = "abc+def/ghi="
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://example.invalid/api"),
        json={
            "OpenAPI_ServiceResponse": {
                "cmmMsgHeader": {
                    "errMsg": "SERVICE_ACCESS_DENIED_ERROR",
                    "returnAuthMsg": "서비스 접근거부",
                    "returnReasonCode": "30",
                }
            }
        },
    )

    message = _http_error_message(response, secret)

    assert "HTTP 403" in message
    assert "SERVICE_ACCESS_DENIED_ERROR" in message
    assert "서비스 접근거부" in message
    assert "code=30" in message
    assert secret not in message


def test_http_200_error_envelope_is_detected():
    payload = {
        "OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {
                "errMsg": "HTTP_ERROR",
                "returnAuthMsg": "HTTP 에러",
                "returnReasonCode": "04",
            }
        }
    }

    assert _payload_error_fields(payload) == ("HTTP_ERROR", "HTTP 에러", "04")


def test_success_header_is_not_treated_as_error():
    payload = {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"}}}

    assert _payload_error_fields(payload) == (None, None, None)
