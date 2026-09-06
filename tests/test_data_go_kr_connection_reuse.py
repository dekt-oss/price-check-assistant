import httpx

from purchase_price.clients import data_go_kr
from purchase_price.clients.data_go_kr import PublicDataPortalClient


class CountingClient:
    instances = 0
    calls = 0

    def __init__(self, *, timeout: float) -> None:
        type(self).instances += 1
        self.timeout = timeout

    def get(self, url: str, *, params: dict):
        type(self).calls += 1
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            200,
            json={"response": {"header": {"resultCode": "00"}, "body": {}}},
            request=request,
        )

    def close(self) -> None:
        pass


def test_public_data_client_reuses_one_http_client(monkeypatch) -> None:
    CountingClient.instances = 0
    CountingClient.calls = 0
    monkeypatch.setattr(data_go_kr.httpx, "Client", CountingClient)

    client = PublicDataPortalClient("secret-value", timeout_seconds=1, max_retries=1)
    client.get_json("https://example.test/api", "first", pageNo=1)
    client.get_json("https://example.test/api", "second", pageNo=1)
    client.close()

    assert CountingClient.instances == 1
    assert CountingClient.calls == 2
