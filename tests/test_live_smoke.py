from datetime import date
from types import SimpleNamespace

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import Settings
from purchase_price.services.live_smoke import (
    LIVE_FAILURE,
    LIVE_SUCCESS,
    LIVE_SUCCESS_0,
    result_from_public_dict,
    run_g2b_live_smoke,
    run_mfds_model_live_smoke,
)


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
    defaults = {
        "g2b_service_key": None,
        "mfds_service_key": None,
        "data_go_kr_market_service_key": None,
        "data_go_kr_service_key": None,
    }
    defaults.update(values)
    return Settings(_env_file=None, **defaults)


def payload(items, total):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": items,
                "totalCount": total,
                "pageNo": 1,
                "numOfRows": 1,
            },
        }
    }


def test_g2b_live_smoke_bounded_and_success():
    client = FakePortalClient(payload([{"prdctIdntNoNm": "제습기"}], 7))
    result = run_g2b_live_smoke(
        "제습기",
        settings=settings(data_go_kr_market_service_key="secret", g2b_max_retries=2),
        portal_client=client,
        today=date(2026, 9, 5),
    )
    assert result.status == LIVE_SUCCESS
    assert len(client.calls) == 1
    assert result.logical_requests == 1
    assert result.max_http_attempts == 3
    params = client.calls[0][2]
    assert params["pageNo"] == 1 and params["numOfRows"] == 1


def test_g2b_zero_and_failure_are_distinct_and_secret_free():
    zero = run_g2b_live_smoke(
        "없음",
        settings=settings(g2b_service_key="key", g2b_max_retries=1),
        portal_client=FakePortalClient(payload([], 0)),
        today=date(2026, 9, 5),
    )
    secret = "DO-NOT-EXPOSE"
    failed = run_g2b_live_smoke(
        "제습기",
        settings=settings(g2b_service_key=secret, g2b_max_retries=1),
        portal_client=FakePortalClient(error=PublicDataClientError(secret)),
        today=date(2026, 9, 5),
    )
    assert zero.status == LIVE_SUCCESS_0
    assert failed.status == LIVE_FAILURE
    assert zero.max_http_attempts == 2
    assert failed.logical_requests == 1
    assert secret not in str(failed.to_public_dict())


def test_mfds_model_smoke_bounded_zero():
    client = FakeModelClient()
    result = run_mfds_model_live_smoke(
        "인공호흡기",
        settings=settings(data_go_kr_market_service_key="secret", mfds_max_retries=3),
        model_client=client,
    )
    assert result.status == LIVE_SUCCESS_0
    assert client.calls == [("인공호흡기", 1, 1)]
    assert result.logical_requests == 1
    assert result.max_http_attempts == 4


def test_public_result_roundtrip_keeps_request_budget_and_accepts_legacy_payload():
    result = run_g2b_live_smoke(
        "없음",
        settings=settings(g2b_service_key="key", g2b_max_retries=2),
        portal_client=FakePortalClient(payload([], 0)),
        today=date(2026, 9, 5),
    )
    restored = result_from_public_dict(result.to_public_dict())
    assert restored.logical_requests == 1
    assert restored.max_http_attempts == 3

    legacy = result.to_public_dict()
    legacy.pop("logical_requests")
    legacy.pop("max_http_attempts")
    restored_legacy = result_from_public_dict(legacy)
    assert restored_legacy.logical_requests == 0
    assert restored_legacy.max_http_attempts == 0
