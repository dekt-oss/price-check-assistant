from purchase_price.collectors.manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from purchase_price.collectors.mock_public import MockPublicCollector
from purchase_price.collectors.registry import build_collectors


def test_default_registry_excludes_mock_collector() -> None:
    collectors = build_collectors()
    assert any(isinstance(collector, ManufacturerPublicCatalogCollector) for collector in collectors)
    assert not any(isinstance(collector, MockPublicCollector) for collector in collectors)


def test_mock_collector_remains_explicitly_available_for_development() -> None:
    collectors = build_collectors(include_mock=True)
    assert any(isinstance(collector, MockPublicCollector) for collector in collectors)
