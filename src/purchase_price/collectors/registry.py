from .base import PriceCollector
from .manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from .mock_public import MockPublicCollector


def build_collectors(
    *,
    include_mock: bool = False,
    include_manufacturer_public: bool = True,
) -> list[PriceCollector]:
    """Build the user-facing collector set.

    Mock evidence is development-only and therefore opt-in. Production/user-facing callers must
    never receive synthetic prices merely because they used the default registry configuration.
    """

    collectors: list[PriceCollector] = []
    if include_manufacturer_public:
        collectors.append(ManufacturerPublicCatalogCollector())
    if include_mock:
        collectors.append(MockPublicCollector())
    return collectors
