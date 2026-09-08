from datetime import date

from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates


def test_target_detail_code_runs_before_broad_terms_and_stays_research_only(monkeypatch) -> None:
    calls: list[dict] = []

    class StubCollector:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def fetch_specific_item_page(self, **kwargs):
            calls.append(kwargs)

            class Page:
                items = (
                    {
                        "dtilPrdctClsfcNoNm": "이산화탄소배양기",
                        "dtilPrdctClsfcNo": "4110449801",
                        "cntrctDlvrDivNm": "납품요구",
                        "cntrctDlvrReqDate": "20260801",
                        "cntrctDlvrReqNo": "CO2-1",
                        "prdctIdntNo": "P-CO2-1",
                        "prdctIdntNoNm": "이산화탄소배양기, ASTEC, APC-30D, Water Jacket",
                        "prdctUprc": "8000000",
                        "prdctQty": "1",
                        "prdctUnit": "대",
                        "prdctAmt": "8000000",
                    },
                )
                total_count = 1

            return Page(), {}

    monkeypatch.setattr(
        "purchase_price.services.g2b_unmapped_discovery.G2BShoppingCollector",
        StubCollector,
    )

    result = discover_unmapped_g2b_candidates(
        ProductQuery(
            product_name="CO₂ Incubator(Water Jacket)",
            manufacturer="ASTEC",
            model_name="APC-30D",
        ),
        service_key="secret-key",
        lookback_days=365,
        pages_per_term_window=1,
        request_budget=1,
        curated_terms=(),
        target_detail_product_codes=("4110449801",),
        today=date(2026, 9, 8),
    )

    assert calls[0]["detail_product_code"] == "4110449801"
    assert "detail_product_name" not in calls[0]
    assert result.targeted_detail_codes == ("4110449801",)
    assert result.candidates
    candidate = result.candidates[0]
    assert candidate.classification_code == "4110449801"
    assert candidate.search_term == "code:4110449801"
    assert "세부품명번호 서버필터 일치" in candidate.match_reason
    assert candidate.relevance == "모델 표기 후보"
    assert not isinstance(candidate, CollectedPrice)


def test_target_detail_codes_reject_invalid_code_before_network() -> None:
    try:
        discover_unmapped_g2b_candidates(
            ProductQuery(product_name="CO2 Incubator"),
            service_key="unused",
            lookback_days=30,
            target_detail_product_codes=("411044980",),
            today=date(2026, 9, 8),
        )
    except ValueError as exc:
        assert "10-digit PPS codes" in str(exc)
    else:
        raise AssertionError("invalid target code must fail closed")
