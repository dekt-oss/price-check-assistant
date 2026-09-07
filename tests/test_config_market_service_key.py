from purchase_price.config import Settings


def test_market_service_key_is_shared_fallback_for_g2b_families_and_mfds() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key=None,
        g2b_shopping_service_key=None,
        g2b_research_service_key=None,
        g2b_catalog_service_key=None,
        g2b_lifecycle_service_key=None,
        mfds_service_key=None,
    )

    assert settings.resolved_g2b_shopping_service_key == "market-key"
    assert settings.resolved_g2b_research_service_key == "market-key"
    assert settings.resolved_g2b_catalog_service_key == "market-key"
    assert settings.resolved_g2b_lifecycle_service_key == "market-key"
    assert settings.resolved_g2b_service_key == "market-key"
    assert settings.resolved_mfds_service_key == "market-key"


def test_historical_g2b_key_can_serve_shopping_without_masking_market_research_key() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="research-market-key",
        g2b_service_key="historical-shopping-key",
        g2b_shopping_service_key=None,
        g2b_research_service_key=None,
    )

    assert settings.resolved_g2b_shopping_service_key == "historical-shopping-key"
    assert settings.resolved_g2b_research_service_key == "research-market-key"
    assert settings.resolved_g2b_catalog_service_key == "research-market-key"
    assert settings.resolved_g2b_lifecycle_service_key == "research-market-key"
    assert settings.g2b_shopping_key_source == "G2B_SERVICE_KEY"
    assert settings.g2b_research_key_source == "DATA_GO_KR_MARKET_SERVICE_KEY"


def test_dedicated_g2b_family_keys_take_precedence() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key="market-key",
        g2b_service_key="old-key",
        g2b_shopping_service_key="shopping-key",
        g2b_research_service_key="research-key",
        g2b_catalog_service_key="catalog-key",
        g2b_lifecycle_service_key="lifecycle-key",
        mfds_service_key="mfds-key",
    )

    assert settings.resolved_g2b_shopping_service_key == "shopping-key"
    assert settings.resolved_g2b_research_service_key == "research-key"
    assert settings.resolved_g2b_catalog_service_key == "catalog-key"
    assert settings.resolved_g2b_lifecycle_service_key == "lifecycle-key"
    assert settings.g2b_shopping_key_source == "G2B_SHOPPING_SERVICE_KEY"
    assert settings.g2b_research_key_source == "G2B_RESEARCH_SERVICE_KEY"
    assert settings.g2b_catalog_key_source == "G2B_CATALOG_SERVICE_KEY"
    assert settings.g2b_lifecycle_key_source == "G2B_LIFECYCLE_SERVICE_KEY"
    assert settings.resolved_mfds_service_key == "mfds-key"


def test_legacy_common_key_remains_supported() -> None:
    settings = Settings(
        data_go_kr_service_key="legacy-key",
        data_go_kr_market_service_key=None,
        g2b_service_key=None,
        g2b_shopping_service_key=None,
        g2b_research_service_key=None,
        g2b_catalog_service_key=None,
        g2b_lifecycle_service_key=None,
        mfds_service_key=None,
    )

    assert settings.resolved_g2b_shopping_service_key == "legacy-key"
    assert settings.resolved_g2b_research_service_key == "legacy-key"
    assert settings.resolved_g2b_catalog_service_key == "legacy-key"
    assert settings.resolved_g2b_lifecycle_service_key == "legacy-key"
    assert settings.resolved_mfds_service_key == "legacy-key"


def test_key_source_properties_never_return_secret_values() -> None:
    secret = "DO-NOT-SHOW-THIS-SECRET"
    settings = Settings(
        g2b_research_service_key=secret,
        g2b_shopping_service_key=secret,
        g2b_catalog_service_key=secret,
        g2b_lifecycle_service_key=secret,
    )

    payload = repr(
        {
            "shopping": settings.g2b_shopping_key_source,
            "research": settings.g2b_research_key_source,
            "catalog": settings.g2b_catalog_key_source,
            "lifecycle": settings.g2b_lifecycle_key_source,
        }
    )
    assert secret not in payload
    assert settings.g2b_shopping_key_source == "G2B_SHOPPING_SERVICE_KEY"
    assert settings.g2b_research_key_source == "G2B_RESEARCH_SERVICE_KEY"
    assert settings.g2b_catalog_key_source == "G2B_CATALOG_SERVICE_KEY"
    assert settings.g2b_lifecycle_key_source == "G2B_LIFECYCLE_SERVICE_KEY"
