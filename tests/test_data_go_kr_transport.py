import httpx
import pytest

from purchase_price.clients import data_go_kr
from purchase_price.clients.data_go_kr import (
    PublicDataClientError,
    PublicDataPortalClient,
    PublicDataTransportError,
)


class TimeoutClient:
    calls = 0

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str, *, params: dict):
        type(self).calls += 1
        request = httpx.Request("GET", url, params=params)
        raise httpx.ConnectTimeout(
            f"timed out serviceKey={params['serviceKey']}", request=request
        )


def test_exhausted_transport_retry_is_wrapped_and_secret_redacted(monkeypatch) -> None:
    TimeoutClient.calls = 0
    monkeypatch.setattr(data_go_kr.httpx, "Client", TimeoutClient)
    client = PublicDataPortalClient(
        "phase0-secret-value",
        timeout_seconds=0.01,
        max_retries=2,
    )

    with pytest.raises(PublicDataClientError) as exc_info:
        client.get_json("https://example.test/api", "endpoint", pageNo=1)

    message = str(exc_info.value)
    assert TimeoutClient.calls == 2
    assert "transport failure after retries" in message
    assert "ConnectTimeout" in message
    assert "phase0-secret-value" not in message


def test_connect_circuit_prevents_repeated_network_wait_after_exhaustion(monkeypatch) -> None:
    TimeoutClient.calls = 0
    monkeypatch.setattr(data_go_kr.httpx, "Client", TimeoutClient)
    client = PublicDataPortalClient(
        "phase0-secret-value",
        timeout_seconds=0.01,
        max_retries=1,
        connect_circuit_breaker=True,
    )

    with pytest.raises(PublicDataTransportError) as first_exc:
        client.get_json("https://example.test/api", "endpoint", pageNo=1)

    assert TimeoutClient.calls == 1
    assert "transport failure after retries" in str(first_exc.value)

    with pytest.raises(PublicDataTransportError) as second_exc:
        client.get_json("https://example.test/api", "another-endpoint", pageNo=1)

    assert TimeoutClient.calls == 1
    message = str(second_exc.value)
    assert "connection circuit open" in message
    assert "phase0-secret-value" not in message
