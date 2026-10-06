from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataTransportError
from purchase_price.services import mfds_api_keys
from purchase_price.services.mfds_api_keys import (
    KeyFallbackJsonClient,
    is_key_not_registered,
    mfds_service_key_candidates,
)

NOT_REGISTERED = PublicDataClientError(
    "Public Data Portal request failed: HTTP 403 error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR "
    "auth=등록되지 않은 서비스키 code=30"
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    mfds_api_keys.reset_working_keys()


class FakeKeyClient:
    def __init__(self, key: str, approved: dict[str, set[str]], calls: list[tuple[str, str]]) -> None:
        self.key = key
        self.approved = approved
        self.calls = calls

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((self.key, base_url))
        if base_url not in self.approved.get(self.key, set()):
            raise NOT_REGISTERED
        return {"key": self.key}


def _client(approved: dict[str, set[str]], calls: list[tuple[str, str]]) -> KeyFallbackJsonClient:
    return KeyFallbackJsonClient(
        ["key-a", "key-b"],
        client_factory=lambda key: FakeKeyClient(key, approved, calls),
    )


def test_falls_back_to_the_key_approved_for_the_service_and_remembers_it() -> None:
    approved = {"key-a": {"product"}, "key-b": {"model", "license"}}
    calls: list[tuple[str, str]] = []

    with _client(approved, calls) as client:
        assert client.get_json("product", "op") == {"key": "key-a"}
        assert client.get_json("model", "op") == {"key": "key-b"}
        assert client.get_json("model", "op") == {"key": "key-b"}

    # The second model call went straight to key-b.
    assert calls == [
        ("key-a", "product"),
        ("key-a", "model"),
        ("key-b", "model"),
        ("key-b", "model"),
    ]


def test_raises_not_registered_when_no_key_is_approved() -> None:
    with _client({}, []) as client, pytest.raises(PublicDataClientError, match="code=30"):
        client.get_json("udi", "op")


def test_other_errors_are_not_retried_with_another_key() -> None:
    calls: list[str] = []

    class Failing:
        def __init__(self, key: str) -> None:
            self.key = key

        def get_json(self, *args, **kwargs):
            calls.append(self.key)
            raise PublicDataTransportError("ReadTimeout")

    client = KeyFallbackJsonClient(["key-a", "key-b"], client_factory=Failing)
    with pytest.raises(PublicDataTransportError):
        client.get_json("model", "op")
    assert calls == ["key-a"]


def test_is_key_not_registered() -> None:
    assert is_key_not_registered(NOT_REGISTERED) is True
    assert is_key_not_registered(PublicDataTransportError("timeout")) is False
    assert is_key_not_registered(ValueError("code=30")) is False


def test_key_candidates_are_ordered_and_deduplicated() -> None:
    settings = SimpleNamespace(
        mfds_service_key="A",
        mfds_recall_service_key="B",
        data_go_kr_market_service_key=None,
        data_go_kr_service_key="A",
        g2b_research_service_key=" B ",
    )

    assert mfds_service_key_candidates(settings) == ("A", "B")


def test_dashboard_defers_model_info_and_routes_keys() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "mfds = research_mfds_for_workspace(query, track_b)" not in source
    assert '"deferred"' in source
    assert "식약처에서 확인 (약 30초)" in source
    assert "_MFDS_MODEL_INFO_CACHE" in source
    assert "client=mfds_model_info_json_client(settings)" in source
    assert "client=mfds_json_client(get_settings())" in source
    assert 'mfds_metric = "조회 대기"' in source


def test_mfds_pages_route_clients_through_key_fallback() -> None:
    for page in (
        "pages/4_의료기기_시장조사.py",
        "pages/4_의료기기_조회.py",
        "pages/5_의료기기_안전_공급사.py",
        "pages/6_의료기기_UDI.py",
        "src/purchase_price/ui/quote_review_steps.py",
        "src/purchase_price/services/mfds_workspace.py",
    ):
        source = Path(page).read_text(encoding="utf-8")
        assert "resolved_mfds_service_key" not in source, page
        assert "mfds_service_key_candidates" in source, page
