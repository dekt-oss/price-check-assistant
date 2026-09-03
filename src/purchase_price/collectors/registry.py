from .base import PriceCollector
from .manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from .mock_public import MockPublicCollector


def build_collectors(
    *,
    include_mock: bool = True,
    include_manufacturer_public: bool = True,
) -> list[PriceCollector]:
    collectors: list[PriceCollector] = []
    if include_manufacturer_public:
        collectors.append(ManufacturerPublicCatalogCollector())
    if include_mock:
        collectors.append(MockPublicCollector())
    return collectors
