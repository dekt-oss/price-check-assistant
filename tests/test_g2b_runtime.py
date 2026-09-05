import pytest

from purchase_price.config import Settings
from purchase_price.services.g2b_runtime import build_configured_g2b_collector


def test_build_configured_g2b_collector_applies_network_policy() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key="source-specific-key",
        g2b_shopping_base_url="https://example.test/g2b",
        g2b_request_timeout_seconds=7.5,
        g2b_max_retries=5,
    )

    collector = build_configured_g2b_collector(settings)

    assert collector.base_url == "https://example.test/g2b"
    assert collector.client.timeout_seconds == 7.5
    assert collector.client.max_retries == 5
    assert collector.client.service_key == "source-specific-key"


def test_build_configured_g2b_collector_falls_back_to_shared_market_key() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key=None,
    )

    collector = build_configured_g2b_collector(settings)

    assert collector.client.service_key == "market-key"


def test_build_configured_g2b_collector_falls_back_to_legacy_common_key() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key=None,
        g2b_service_key=None,
    )

    collector = build_configured_g2b_collector(settings)

    assert collector.client.service_key == "legacy-key"


def test_build_configured_g2b_collector_accepts_source_specific_key_without_fallbacks() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=None,
        g2b_service_key="source-specific-key",
    )

    collector = build_configured_g2b_collector(settings)

    assert collector.client.service_key == "source-specific-key"


def test_build_configured_g2b_collector_rejects_missing_key() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=None,
        g2b_service_key=None,
    )

    with pytest.raises(ValueError, match="G2B_SERVICE_KEY"):
        build_configured_g2b_collector(settings)
