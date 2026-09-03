import pytest

from purchase_price.config import Settings
from purchase_price.services.g2b_runtime import build_configured_g2b_collector


def test_build_configured_g2b_collector_applies_network_policy() -> None:
    settings = Settings(
        data_go_kr_service_key="test-service-key",
        g2b_shopping_base_url="https://example.test/g2b",
        g2b_request_timeout_seconds=7.5,
        g2b_max_retries=5,
    )

    collector = build_configured_g2b_collector(settings)

    assert collector.base_url == "https://example.test/g2b"
    assert collector.client.timeout_seconds == 7.5
    assert collector.client.max_retries == 5
    assert collector.client.service_key == "test-service-key"


def test_build_configured_g2b_collector_rejects_missing_key() -> None:
    settings = Settings(data_go_kr_service_key=None)

    with pytest.raises(ValueError, match="DATA_GO_KR_SERVICE_KEY"):
        build_configured_g2b_collector(settings)
