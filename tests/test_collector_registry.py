from purchase_price.collectors.g2b_verified_search import VerifiedG2BShoppingSearchCollector
from purchase_price.collectors.manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from purchase_price.collectors.mock_public import MockPublicCollector
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings


def _clear_public_data_keys(monkeypatch) -> None:
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "")
    monkeypatch.setenv("G2B_SERVICE_KEY", "")
    monkeypatch.setenv("MFDS_SERVICE_KEY", "")


def test_default_registry_excludes_mock_collector(monkeypatch) -> None:
    _clear_public_data_keys(monkeypatch)
    get_settings.cache_clear()
    try:
        collectors = build_collectors()
        assert any(isinstance(collector, ManufacturerPublicCatalogCollector) for collector in collectors)
        assert not any(isinstance(collector, MockPublicCollector) for collector in collectors)
        assert not any(isinstance(collector, VerifiedG2BShoppingSearchCollector) for collector in collectors)
    finally:
        get_settings.cache_clear()


def test_configured_registry_enables_verified_g2b_without_mock(monkeypatch) -> None:
    _clear_public_data_keys(monkeypatch)
    monkeypatch.setenv("G2B_SERVICE_KEY", "g2b-test-service-key")
    get_settings.cache_clear()
    try:
        collectors = build_collectors(g2b_lookback_days=30)
        assert any(isinstance(collector, ManufacturerPublicCatalogCollector) for collector in collectors)
        g2b = next(
            collector
            for collector in collectors
            if isinstance(collector, VerifiedG2BShoppingSearchCollector)
        )
        assert g2b.lookback_days == 30
        assert not any(isinstance(collector, MockPublicCollector) for collector in collectors)
    finally:
        get_settings.cache_clear()


def test_legacy_common_key_still_enables_g2b(monkeypatch) -> None:
    _clear_public_data_keys(monkeypatch)
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "legacy-test-service-key")
    get_settings.cache_clear()
    try:
        collectors = build_collectors()
        assert any(isinstance(collector, VerifiedG2BShoppingSearchCollector) for collector in collectors)
    finally:
        get_settings.cache_clear()


def test_source_specific_keys_take_precedence_over_legacy_common_key(monkeypatch) -> None:
    _clear_public_data_keys(monkeypatch)
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "legacy-key")
    monkeypatch.setenv("G2B_SERVICE_KEY", "new-g2b-key")
    monkeypatch.setenv("MFDS_SERVICE_KEY", "new-mfds-key")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.resolved_g2b_service_key == "new-g2b-key"
        assert settings.resolved_mfds_service_key == "new-mfds-key"
    finally:
        get_settings.cache_clear()


def test_g2b_can_be_explicitly_disabled_even_when_key_is_configured(monkeypatch) -> None:
    _clear_public_data_keys(monkeypatch)
    monkeypatch.setenv("G2B_SERVICE_KEY", "test-service-key")
    get_settings.cache_clear()
    try:
        collectors = build_collectors(include_g2b=False)
        assert not any(isinstance(collector, VerifiedG2BShoppingSearchCollector) for collector in collectors)
    finally:
        get_settings.cache_clear()


def test_mock_collector_remains_explicitly_available_for_development(monkeypatch) -> None:
    _clear_public_data_keys(monkeypatch)
    get_settings.cache_clear()
    try:
        collectors = build_collectors(include_mock=True)
        assert any(isinstance(collector, MockPublicCollector) for collector in collectors)
    finally:
        get_settings.cache_clear()
