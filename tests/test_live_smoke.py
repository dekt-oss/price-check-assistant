from datetime import date
from types import SimpleNamespace

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import Settings
from purchase_price.services.live_smoke import LIVE_FAILURE, LIVE_SUCCESS, LIVE_SUCCESS_0, run_g2b_live_smoke, run_mfds_model_live_smoke


class FakePortalClient:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload or {}, error, []
    def get_json(self, base_url, operation, **params):
        self.calls.append((base_url, operation, params))
        if self.error:
            raise self.error
        return self.payload


class FakeModelClient:
    def __init__(self, items=(), total_count=0):
        self.items, self.total_count, self.calls = items, total_count, []
    def fetch_page(self, *, product_name, page_no, num_of_rows):
        self.calls.append((product_name, page_no, num_of_rows))
        return SimpleNamespace(items=self.items, total_count=self.total_count)


def settings(**values):
    defaults = {"g2b_service_key": None, "mfds_service_key": None, "data_go_kr_market_service_key": None, "data_go_kr_service_key": None}
    defaults.update(values)
    return Settings(_env_file=None, **defaults)


def payload(items, total):
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": {"items": items, "totalCount": total, "pageNo": 1, "numOfRows": 1}}}


def test_g2b_live_smoke_bounded_and_success():
    client = FakePortalClient(payload([{"prdctIdntNoNm": "제습기"}], 7))
    result = run_g2b_live_smoke("제습기", settings=settings(data_go_kr_market_service_key="secret"), portal_client=client, today=date(2026, 9, 5))
    assert result.status == LIVE_SUCCESS
    assert len(client.calls) == 1
    params = client.calls[0][2]
    assert params["pageNo"] == 1 and params["numOfRows"] == 1


def test_g2b_zero_and_failure_are_distinct_and_secret_free():
    zero = run_g2b_live_smoke("없음", settings=settings(g2b_service_key="key"), portal_client=FakePortalClient(payload([], 0)), today=date(2026, 9, 5))
    secret = "DO-NOT-EXPOSE"
    failed = run_g2b_live_smoke("제습기", settings=settings(g2b_service_key=secret), portal_client=FakePortalClient(error=PublicDataClientError(secret)), today=date(2026, 9, 5))
    assert zero.status == LIVE_SUCCESS_0
    assert failed.status == LIVE_FAILURE
    assert secret not in str(failed.to_public_dict())


def test_mfds_model_smoke_bounded_zero():
    client = FakeModelClient()
    result = run_mfds_model_live_smoke("인공호흡기", settings=settings(data_go_kr_market_service_key="secret"), model_client=client)
    assert result.status == LIVE_SUCCESS_0
    assert client.calls == [("인공호흡기", 1, 1)]
