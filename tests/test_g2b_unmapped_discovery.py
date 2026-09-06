from datetime import date

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import (
    build_g2b_discovery_terms,
    build_g2b_research_terms,
    discover_unmapped_g2b_candidates,
)


def test_flow_c_quote_builds_conservative_g2b_discovery_terms() -> None:
    assert build_g2b_discovery_terms("가스 마취기(Anesthesia Machine)") == (
        "가스 마취기",
        "마취기",
    )


def test_research_terms_add_compact_and_curated_candidates() -> None:
    flow_terms = build_g2b_research_terms(
        ProductQuery(product_name="가스 마취기", model_name="Flow-C"),
        curated_terms=(),
    )
    assert flow_terms == ("가스 마취기", "마취기", "가스마취기")

    gms_terms = build_g2b_research_terms(
        ProductQuery(product_name="약품냉장고", manufacturer="GMS", model_name="GMSR-182")
    )
    assert "의약품냉장고" in gms_terms
    assert "실험실용일반냉장고" in gms_terms


def test_empty_product_name_has_no_discovery_terms() -> None:
    assert build_g2b_discovery_terms("") == ()


def test_unmapped_discovery_ranks_exact_model_but_keeps_category_research(monkeypatch) -> None:
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
        curated_terms=(),
        today=date(2026, 9, 5),
    )

    assert result.status == "success"
    assert result.request_count == 3
    assert len(calls) == 3
    assert {call["detail_product_name"] for call in calls} == {
        "가스 마취기",
        "마취기",
        "가스마취기",
    }
    assert all(call["num_of_rows"] == 100 for call in calls)
    assert len(result.candidates) == 2
    exact, broad = result.candidates
    assert exact.title == "마취기, Maquet, Flow-C, Base Unit"
    assert exact.relevance == "모델 표기 후보"
    assert exact.score > broad.score
    assert broad.title == "마취기, Other, X-100"
    assert broad.relevance == "분류 후보"
    assert broad.price == 30000000
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
        curated_terms=(),
        today=date(2026, 9, 5),
    )

    assert result.status == "success_0"
    # Five one-year windows x three research terms, one request each.
    assert result.request_count == 15
    assert len(windows) == 15
    assert all((end - begin).days <= 364 for begin, end in windows)


def test_unmapped_discovery_isolates_one_failed_research_term(monkeypatch) -> None:
    class PartialCollector:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_specific_item_page(self, **kwargs):
            if kwargs["detail_product_name"] == "마취기":
                raise PublicDataClientError("bounded test failure")

            class Page:
                items = (
                    {
                        "dtilPrdctClsfcNoNm": "가스마취기",
                        "dtilPrdctClsfcNo": "42182001",
                        "cntrctDlvrDivNm": "납품요구",
                        "cntrctDlvrReqDate": "20260801",
                        "cntrctDlvrReqNo": "FLOW-1",
                        "prdctIdntNo": "P-FLOW-1",
                        "prdctIdntNoNm": "가스마취기, Maquet, Flow-C",
                        "prdctUprc": "66000000",
                        "prdctQty": "1",
                        "prdctUnit": "대",
                        "prdctAmt": "66000000",
                    },
                )
                total_count = 1

            return Page(), {}

    monkeypatch.setattr(
        "purchase_price.services.g2b_unmapped_discovery.G2BShoppingCollector",
        PartialCollector,
    )

    result = discover_unmapped_g2b_candidates(
        ProductQuery(product_name="가스 마취기", manufacturer="Maquet", model_name="Flow-C"),
        service_key="secret-key",
        lookback_days=30,
        pages_per_term_window=1,
        curated_terms=(),
        today=date(2026, 9, 5),
    )

    assert result.status == "partial"
    assert result.failed_query_count == 1
    assert result.error_types == ("PublicDataClientError",)
    assert len(result.candidates) == 1
    assert result.candidates[0].relevance == "모델 표기 후보"
