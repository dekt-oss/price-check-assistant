from datetime import date

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates


def test_research_failure_preserves_diagnostic_message(monkeypatch) -> None:
    class FailedCollector:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_specific_item_page(self, **kwargs):
            raise PublicDataClientError(
                "Public Data Portal transport failure after retries: ConnectTimeout: timed out"
            )

    monkeypatch.setattr(
        "purchase_price.services.g2b_unmapped_discovery.G2BShoppingCollector",
        FailedCollector,
    )

    result = discover_unmapped_g2b_candidates(
        ProductQuery(product_name="심전도기", manufacturer="GE", model_name="MAC5"),
        service_key="secret-key",
        lookback_days=30,
        pages_per_term_window=1,
        request_budget=2,
        curated_terms=("심전도계",),
        today=date(2026, 9, 6),
    )

    assert result.status == "failure"
    assert result.error_types == ("PublicDataClientError",)
    assert result.error_messages == (
        "Public Data Portal transport failure after retries: ConnectTimeout: timed out",
    )
