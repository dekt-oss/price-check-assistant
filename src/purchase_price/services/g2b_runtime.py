from __future__ import annotations

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, G2BShoppingCollector
from purchase_price.config import Settings


def build_configured_g2b_collector(settings: Settings) -> G2BShoppingCollector:
    """Build the G2B collector with the repository's configured timeout/retry policy.

    Every live G2B entry point should use this helper instead of relying on the collector's
    default client. This keeps diagnostics and production validation on the same network policy.
    """

    service_key = settings.data_go_kr_service_key
    if not service_key:
        raise ValueError("DATA_GO_KR_SERVICE_KEY is not configured")

    client = PublicDataPortalClient(
        service_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    return G2BShoppingCollector(
        service_key,
        base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        client=client,
    )
