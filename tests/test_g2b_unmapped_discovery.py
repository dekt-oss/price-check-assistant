from datetime import date

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import (
    build_g2b_discovery_terms,
    discover_unmapped_g2b_candidates,
)


def test_flow_c_quote_builds_conservative_g2b_discovery_terms() -> None:
    assert build_g2b_discovery_terms("가스 마취기(Anesthesia Machine)") == (
        "가스 마취기",
        "마취기",
    )


def test_empty_product_name_has_no_discovery_terms() -> None:
    assert build_g2b_discovery_terms("") == ()


def test_unmapped_discovery_filters_to_model_and_never_returns_raw_rows(monkeypatch) -> None:
    calls: list[dict] = []

    class StubCollector:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_specific_item_page(self, **kwargs):
            calls.append(kwargs)

            class Page:
                items = (
                    {
                        "dtilPrdctClsfcNoNm": "마취기",
                        "dtilPrdctClsfcNo": "42182001",
                        "cntrctDlvrDivNm": "납품요구",
                        "cntrctDlvrReqDate": "20260801",
                        "cntrctDlvrReqNo": "FLOW-1",
                        "prdctIdntNo": "P-FLOW-1",
                        "prdctIdntNoNm": "마취기, Maquet, Flow-C, Base Unit",
                        "prdctUprc": "66000000",
                        "prdctQty": "1",
                        "prdctUnit": "대",
                        "prdctAmt": "66000000",
                    },
                    {
                        "dtilPrdctClsfcNoNm": "마취기",
                        "dtilPrdctClsfcNo": "42182001",
                        "cntrctDlvrDivNm": "납품요구",
                        "cntrctDlvrReqDate": "20260802",
                        "cntrctDlvrReqNo": "OTHER-1",
                        "prdctIdntNo": "P-OTHER-1",
                        "prdctIdntNoNm": "마취기, Other, X-100",
                        "prdctUprc": "30000000",
                        "prdctQty": "1",
                        "prdctUnit": "대",
                        "prdctAmt": "30000000",
                    },
                )
                total_count = 2

            return Page(), {"secret": "must-not-leak"}

    monkeypatch.setattr(
        "purchase_price.services.g2b_unmapped_discovery.G2BShoppingCollector",
        StubCollector,
    )

    result = discover_unmapped_g2b_candidates(
        ProductQuery(
            product_name="가스 마취기(Anesthesia Machine)",
            manufacturer="Maquet",
            model_name="Flow-C",
        ),
        service_key="secret-key",
        lookback_days=365,
        pages_per_term_window=1,
        today=date(2026, 9, 5),
    )

    assert result.status == "success"
    assert result.request_count == 2
    assert len(calls) == 2
    assert {call["detail_product_name"] for call in calls} == {"가스 마취기", "마취기"}
    assert all(call["num_of_rows"] == 100 for call in calls)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.title == "마취기, Maquet, Flow-C, Base Unit"
    assert candidate.classification_name == "마취기"
    assert candidate.price == 66000000
    assert not hasattr(result, "raw_payload")


def test_unmapped_discovery_searches_multi_year_period_in_year_bounded_windows(monkeypatch) -> None:
    windows: list[tuple[date, date]] = []

    class EmptyCollector:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_specific_item_page(self, **kwargs):
            windows.append((kwargs["begin_date"], kwargs["end_date"]))

            class Page:
                items = ()
                total_count = 0

            return Page(), {}

    monkeypatch.setattr(
        "purchase_price.services.g2b_unmapped_discovery.G2BShoppingCollector",
        EmptyCollector,
    )

    result = discover_unmapped_g2b_candidates(
        ProductQuery(product_name="가스 마취기", model_name="Flow-C"),
        service_key="secret-key",
        lookback_days=1825,
        pages_per_term_window=1,
        today=date(2026, 9, 5),
    )

    assert result.status == "success_0"
    # Five one-year windows x two discovery terms, one request each.
    assert result.request_count == 10
    assert len(windows) == 10
    assert all((end - begin).days <= 364 for begin, end in windows)
