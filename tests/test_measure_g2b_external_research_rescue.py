from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from purchase_price.scripts.measure_g2b_external_research_rescue import build_report


def test_external_research_rescues_delivery_index_zero() -> None:
    recall = {
        "schema": "r2-search-recall-report-v1",
        "cases": [
            {
                "case_id": "rotapro",
                "tier": "ZERO",
                "expected_surface": "external_research",
                "query": {
                    "product_name": "혈관박리카테터장치",
                    "manufacturer": "Boston Scientific",
                    "model_name": "ROTAPRO",
                    "specification": "ROTAPRO",
                },
            }
        ],
    }
    mapping = SimpleNamespace(
        model_name="ROTAPRO",
        detail_product_code="4220341801",
    )
    record = SimpleNamespace(
        source_type="bid_notice",
        source_record_id="R26BK01737978",
        title="혈관박리카테터장치 구입",
        product_name="혈관박리카테터장치",
        model_name=None,
        original_specification=None,
        detail_product_code="4220341801",
        published_date=date(2026, 9, 21),
        amount=40000000,
        source_url="https://example.invalid/g2b",
    )
    bundle = SimpleNamespace(
        sources=(
            SimpleNamespace(source="bid_notice", status="success", records=(record,)),
        ),
        records=(record,),
    )

    def research(query, **kwargs):
        assert query.model_name == "ROTAPRO"
        assert kwargs["lookback_days"] == 90
        return bundle

    report = build_report(
        recall,
        mappings=(mapping,),
        service_key="test-key",
        research=research,
    )

    assert report["status"] == "SUCCESS"
    assert report["rescued_case_count"] == 1
    assert report["cases"][0]["status"] == "RESEARCH_RESCUED"
    assert report["cases"][0]["matching_record_count"] == 1


def test_external_research_is_not_required_after_delivery_index_recovers() -> None:
    recall = {
        "schema": "r2-search-recall-report-v1",
        "cases": [
            {
                "case_id": "rotapro",
                "tier": "DIRECT_AB",
                "expected_surface": "external_research",
                "query": {
                    "product_name": "혈관박리카테터장치",
                    "manufacturer": "Boston Scientific",
                    "model_name": "ROTAPRO",
                    "specification": "ROTAPRO",
                },
            }
        ],
    }

    def research(*args, **kwargs):
        raise AssertionError("research must not run after direct recovery")

    report = build_report(
        recall,
        mappings=(),
        service_key="test-key",
        research=research,
    )

    assert report["status"] == "SUCCESS"
    assert report["cases"][0]["status"] == "DELIVERY_INDEX_RECOVERED"
