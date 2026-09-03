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


def test_httpx_request_log_never_contains_service_key(caplog):
    """httpx logs the full request URL at INFO; the client must mask serviceKey in it."""
    import logging

    from purchase_price.clients.data_go_kr import harden_http_logging

    secret = "SECRETKEY-1234567890"
    harden_http_logging()
    httpx_logger = logging.getLogger("httpx")
    previous_level = httpx_logger.level
    httpx_logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG, logger="httpx"):
            httpx_logger.info(
                'HTTP Request: %s %s "%s"',
                "GET",
                f"https://example.invalid/op?serviceKey={secret}&type=json&pageNo=1",
                "HTTP/1.1 200 OK",
            )
    finally:
        httpx_logger.setLevel(previous_level)

    assert caplog.records, "log record should still be emitted"
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in joined
    assert "serviceKey=***" in joined
    assert "pageNo=1" in joined


def test_http_transport_loggers_default_to_warning():
    import logging

    from purchase_price.clients.data_go_kr import harden_http_logging

    harden_http_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_service_key_redaction_covers_encoded_and_quoted_urls():
    from purchase_price.clients.data_go_kr import redact_service_key_query

    encoded = "https://x/op?serviceKey=abc%2Bdef%3D&pageNo=1"
    assert redact_service_key_query(encoded) == "https://x/op?serviceKey=***&pageNo=1"
    assert redact_service_key_query('url="https://x/op?servicekey=abc"') == (
        'url="https://x/op?servicekey=***"'
    )
