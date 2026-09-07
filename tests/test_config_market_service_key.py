from purchase_price.config import Settings


def test_market_service_key_is_shared_fallback_for_g2b_and_mfds() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key=None,
        mfds_service_key=None,
    )

    assert settings.resolved_g2b_service_key == "market-key"
    assert settings.resolved_g2b_shopping_service_key == "market-key"
    assert settings.resolved_g2b_research_service_key == "market-key"
    assert settings.resolved_mfds_service_key == "market-key"


def test_historical_g2b_key_stays_on_shopping_but_does_not_mask_new_research_key() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="new-research-key",
        g2b_service_key="old-shopping-key",
        mfds_service_key="mfds-key",
    )

    assert settings.resolved_g2b_service_key == "old-shopping-key"
    assert settings.resolved_g2b_shopping_service_key == "old-shopping-key"
    assert settings.resolved_g2b_research_service_key == "new-research-key"
    assert settings.g2b_shopping_key_source == "G2B_SERVICE_KEY"
    assert settings.g2b_research_key_source == "DATA_GO_KR_MARKET_SERVICE_KEY"
    assert settings.resolved_mfds_service_key == "mfds-key"


def test_dedicated_g2b_family_keys_take_precedence() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key="historical-key",
        g2b_shopping_service_key="shopping-key",
        g2b_research_service_key="research-key",
    )

    assert settings.resolved_g2b_shopping_service_key == "shopping-key"
    assert settings.resolved_g2b_research_service_key == "research-key"
    assert settings.g2b_shopping_key_source == "G2B_SHOPPING_SERVICE_KEY"
    assert settings.g2b_research_key_source == "G2B_RESEARCH_SERVICE_KEY"


def test_source_specific_keys_take_precedence_over_shared_market_key() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key="g2b-key",
        mfds_service_key="mfds-key",
    )

    # Backward-compatible G2B alias is shopping-oriented.
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
    assert settings.resolved_g2b_research_service_key == "legacy-key"
    assert settings.resolved_mfds_service_key == "legacy-key"
