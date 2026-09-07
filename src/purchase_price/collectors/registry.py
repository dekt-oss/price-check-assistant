from purchase_price.config import get_settings

from .base import PriceCollector
from .g2b_shopping import G2B_SHOPPING_BASE_URL
from .g2b_verified_search import VerifiedG2BShoppingSearchCollector
from .manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from .mock_public import MockPublicCollector


def build_collectors(
    *,
    include_mock: bool = False,
    include_manufacturer_public: bool = True,
    include_g2b: bool = True,
    g2b_lookback_days: int = 365,
) -> list[PriceCollector]:
    """Build the user-facing collector set.

    Mock evidence is development-only and opt-in. Verified G2B direct-price collection uses the
    shopping-service credential family. Bid/award/pre-spec Research is routed independently by the
    market-research service because those APIs may require a different approved subscription key.
    """

    collectors: list[PriceCollector] = []
    if include_manufacturer_public:
        collectors.append(ManufacturerPublicCatalogCollector())

    settings = get_settings()
    service_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if include_g2b and service_key:
        collectors.append(
            VerifiedG2BShoppingSearchCollector(
                service_key,
                lookback_days=g2b_lookback_days,
                base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
                timeout_seconds=settings.g2b_request_timeout_seconds,
                max_retries=settings.g2b_max_retries,
                request_budget=settings.g2b_search_request_budget,
            )
        )

    if include_mock:
        collectors.append(MockPublicCollector())
    return collectors
