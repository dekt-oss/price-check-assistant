from __future__ import annotations

import pytest

from purchase_price.clients.data_go_kr import (
    PublicDataClientError,
    PublicDataTransportError,
    call_with_server_retry,
    is_server_side_error,
)

PORTAL_504 = "Public Data Portal request failed: HTTP 504 error=SERVICETIMEOUT_ERROR auth=서비스 연결실패 에러 code=05"


def test_server_side_errors_are_recognized() -> None:
    assert is_server_side_error(PublicDataClientError(PORTAL_504))
    assert is_server_side_error(PublicDataClientError("Public Data Portal request failed: HTTP 502"))
    assert not is_server_side_error(PublicDataClientError("API error: code=30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))
    assert not is_server_side_error(PublicDataClientError("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS code=22"))
    assert not is_server_side_error(PublicDataTransportError("ReadTimeout"))
    assert not is_server_side_error(ValueError(PORTAL_504))


def test_retry_recovers_after_server_errors() -> None:
    calls = []
    waits = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise PublicDataClientError(PORTAL_504)
        return {"ok": True}

    assert call_with_server_retry(flaky, delays=(1, 2), sleep=waits.append) == {"ok": True}
    assert waits == [1, 2]


def test_retry_gives_up_and_does_not_retry_other_errors() -> None:
    waits = []

    def always_504():
        raise PublicDataClientError(PORTAL_504)

    with pytest.raises(PublicDataClientError):
        call_with_server_retry(always_504, delays=(1, 2), sleep=waits.append)
    assert waits == [1, 2]

    waits.clear()

    def unauthorized():
        raise PublicDataClientError("code=30")

    with pytest.raises(PublicDataClientError):
        call_with_server_retry(unauthorized, delays=(1, 2), sleep=waits.append)
    assert waits == []


def test_transport_failures_are_retried_too() -> None:
    calls = []
    waits = []

    def connect_timeout_then_ok():
        calls.append(1)
        if len(calls) == 1:
            raise PublicDataTransportError("ConnectTimeout: timed out")
        return {"ok": True}

    assert call_with_server_retry(connect_timeout_then_ok, delays=(5,), sleep=waits.append) == {"ok": True}
    assert waits == [5]
