from datetime import UTC, datetime

from purchase_price.scripts.audit_g2b_track_b_historical import (
    HistoricalAuditAccumulator,
    build_segment_coverage,
    completed_code_set,
)
from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor
from purchase_price.services.g2b_target_code_snapshot import TargetCodeSnapshot
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage


def _snapshot() -> TargetCodeSnapshot:
    return TargetCodeSnapshot(
        segments=("42", "41"),
        codes=("4200000001", "4200000002", "4100000001"),
        generated_at=datetime(2026, 9, 13, tzinfo=UTC).isoformat(),
        dictionary_requests=1,
    )


def test_completed_code_set_uses_only_fully_completed_cursor_codes() -> None:
    snapshot = _snapshot()

    assert completed_code_set(snapshot, CollectionCursor(2, 1)) == {
        "4200000001",
        "4200000002",
    }
    assert completed_code_set(snapshot, CollectionCursor(2, 3)) == {
        "4200000001",
        "4200000002",
    }


def test_segment_coverage_separates_query_page_row_price_and_serving_coverage() -> None:
    snapshot = _snapshot()
    coverage = build_segment_coverage(
        snapshot=snapshot,
        cursor=CollectionCursor(2, 1),
        classification_counts={
            "4200000001": {
                "raw_rows": 3,
                "normalized_rows": 3,
                "price_candidates": 2,
            },
            "4200000002": {
                "raw_rows": 0,
                "normalized_rows": 0,
                "price_candidates": 0,
            },
        },
        page_codes={"4200000001", "4200000002"},
        serving_by_code={
            "4200000001": {"rows": 3, "positive_price_rows": 2},
        },
    )

    assert coverage["42"] == {
        "target_codes": 2,
        "query_completed_codes": 2,
        "query_completed_pct": 100.0,
        "codes_with_raw_page": 2,
        "codes_with_rows": 1,
        "codes_with_price_observation": 1,
        "raw_rows": 3,
        "normalized_rows": 3,
        "price_observations": 2,
        "serving_rows": 3,
        "serving_positive_price_rows": 2,
    }
    assert coverage["41"]["target_codes"] == 1
    assert coverage["41"]["query_completed_codes"] == 0
    assert coverage["41"]["codes_with_raw_page"] == 0


def _raw_page(product_name: str) -> TrackBRawPage:
    payload = {
        "schema": "g2b-track-b-page-v1",
        "operation": "getSpcifyPrdlstPrcureInfoList",
        "request": {
            "detail_code": "4200000001",
            "begin_date": "2025-09-12",
            "end_date": "2026-09-11",
            "page_no": 1,
            "page_size": 999,
            "inquiry_div": "1",
            "product_div": "2",
            "final_change_order_filter": "OMITTED",
        },
        "response": {
            "total_count": 1,
            "page_no": 1,
            "num_of_rows": 999,
            "items": [
                {
                    "cntrctDlvrReqNo": "R26TEST",
                    "cntrctDlvrReqChgOrd": "00",
                    "prdctSno": "1",
                    "cntrctDlvrReqDate": "20260715",
                    "dtilPrdctClsfcNo": "4200000001",
                    "prdctIdntNoNm": product_name,
                    "prdctQty": "1",
                    "prdctUprc": "1000",
                    "prdctAmt": "1000",
                }
            ],
        },
    }
    return TrackBRawPage(payload=payload)


def test_historical_audit_quarantines_cross_page_identity_conflict() -> None:
    audit = HistoricalAuditAccumulator()
    audit.add_page(_raw_page("제품 A"))
    audit.add_page(_raw_page("제품 B"))

    report = audit.as_dict()

    assert report["normalized_records"] == 1
    assert report["price_candidates"] == 1
    assert report["identity_counts"]["conflict"] == 1
    assert report["issue_counts"]["CROSS_PAGE_IDENTITY_CONFLICT"] == 1
