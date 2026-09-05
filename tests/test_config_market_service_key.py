from purchase_price.config import Settings


def test_market_service_key_is_shared_fallback_for_g2b_and_mfds() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key=None,
        mfds_service_key=None,
    )

    assert settings.resolved_g2b_service_key == "market-key"
    assert settings.resolved_mfds_service_key == "market-key"


def test_source_specific_keys_take_precedence_over_shared_market_key() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key="g2b-key",
        mfds_service_key="mfds-key",
    )

    assert settings.resolved_g2b_service_key == "g2b-key"
    assert settings.resolved_mfds_service_key == "mfds-key"


def test_legacy_common_key_remains_supported() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key=None,
        g2b_service_key=None,
        mfds_service_key=None,
    )

    assert settings.resolved_g2b_service_key == "legacy-key"
    assert settings.resolved_mfds_service_key == "legacy-key"
