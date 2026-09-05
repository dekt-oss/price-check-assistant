from purchase_price.collectors.base import CollectorSkipped
from purchase_price.collectors.g2b_verified_search import VerifiedG2BShoppingSearchCollector
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.search import search_all


class NeverCalledG2BCollector:
    def fetch_specific_item_page(self, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError(f"unexpected live G2B call: {kwargs}")


def test_g2b_period_policy_defaults_to_one_year_and_supports_five_years() -> None:
    assert G2B_DEFAULT_LOOKBACK_DAYS == 365
    assert G2B_LOOKBACK_OPTIONS == (365, 730, 1095, 1825)
    assert g2b_lookback_label(365) == "최근 1년 (기본)"
    assert g2b_lookback_label(1825) == "최근 5년"


def test_unmapped_exact_model_is_not_reported_as_success_zero() -> None:
    collector = VerifiedG2BShoppingSearchCollector(
        collector=NeverCalledG2BCollector(),  # type: ignore[arg-type]
        mappings=(),
        lookback_days=365,
    )

    run = search_all(
        ProductQuery(
            product_name="가스 마취기(Anesthesia Machine)",
            manufacturer="Maquet",
            model_name="Flow-C",
        ),
        [collector],
    )

    assert run.results == []
    assert run.errors == []
    assert len(run.source_statuses) == 1
    status = run.source_statuses[0]
    assert status.skipped is True
    assert status.succeeded is False
    assert status.status_label == "미검색"
    assert "Flow-C" in (status.note or "")
    assert "mapping" in (status.note or "")


def test_verified_collector_raises_skip_before_any_api_call_for_unmapped_model() -> None:
    collector = VerifiedG2BShoppingSearchCollector(
        collector=NeverCalledG2BCollector(),  # type: ignore[arg-type]
        mappings=(),
    )

    try:
        collector.search(ProductQuery(model_name="Flow-C"))
    except CollectorSkipped as exc:
        assert "직접가격 API를 호출하지 않음" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("CollectorSkipped was not raised")


def test_registry_default_g2b_window_is_one_year(monkeypatch) -> None:
    monkeypatch.setenv("G2B_SERVICE_KEY", "g2b-test-service-key")
    monkeypatch.setenv("DATA_GO_KR_MARKET_SERVICE_KEY", "")
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "")
    get_settings.cache_clear()
    try:
        collectors = build_collectors(include_manufacturer_public=False)
        g2b = next(
            collector
            for collector in collectors
            if isinstance(collector, VerifiedG2BShoppingSearchCollector)
        )
        assert g2b.lookback_days == 365
    finally:
        get_settings.cache_clear()
