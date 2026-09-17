from datetime import UTC, datetime

from purchase_price.scripts.audit_g2b_track_b_historical import (
    build_segment_coverage,
    completed_code_set,
)
from purchase_price.scripts.collect_g2b_track_b_r2 import CollectionCursor
from purchase_price.services.g2b_target_code_snapshot import TargetCodeSnapshot


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
