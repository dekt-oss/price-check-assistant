from datetime import date
from decimal import Decimal

from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.scripts.run_phase0_validation import (
    _mapping_status_for_query,
    _retained_evidence_reason,
    _safe_error_detail,
    _source_hit,
)
from purchase_price.services.g2b_product_mapping import G2BProductMapping
from purchase_price.services.phase0_validation import (
    build_source_evaluation,
    summarize_phase0_evaluations,
)


def _price(grade: MatchGrade, source_name: str = "source-a") -> CollectedPrice:
    return CollectedPrice(
        manufacturer="Maker",
        product_name="Product",
        model_name="MODEL-1",
        specification=None,
        price=Decimal("1000"),
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.OTHER,
        source_name=source_name,
        source_url="https://example.test/item",
        collected_at=date(2026, 9, 4),
        source_record_id="record-1",
        original_title="Product, Maker, MODEL-1",
        match_grade=grade,
    )


def test_source_hit_falls_back_to_records_when_total_count_missing() -> None:
    assert _source_hit(reported_total_count=None, records_seen=2) is True
    assert _source_hit(reported_total_count=None, records_seen=0) is False
    assert _source_hit(reported_total_count=0, records_seen=2) is False


def test_x_only_candidates_get_explicit_shortage_reason() -> None:
    reason = _retained_evidence_reason((_price(MatchGrade.X),))
    assert reason is not None
    assert "remained X" in reason


def test_verified_mapping_wins_over_unverified_duplicate_model() -> None:
    query = ProductQuery(product_name="Product", model_name="MODEL-1")
    mappings = (
        G2BProductMapping(
            model_name="MODEL-1",
            product_name="Product",
            detail_product_name=None,
            detail_product_code=None,
            mapping_status="unverified",
        ),
        G2BProductMapping(
            model_name="MODEL-1",
            product_name="Product",
            detail_product_name="세부품명",
            detail_product_code="12345678",
            mapping_status="verified",
        ),
    )

    assert _mapping_status_for_query(query, mappings) == "verified"


def test_safe_error_detail_masks_service_key_query() -> None:
    detail = _safe_error_detail(RuntimeError("request failed ?serviceKey=SECRET123&x=1"))
    assert "SECRET123" not in detail
    assert "serviceKey=***" in detail


def test_x_only_rows_do_not_create_multi_source_evidence() -> None:
    rows = (
        build_source_evaluation(
            benchmark_model="MODEL-1",
            product_name="Product",
            source_name="source-a",
            mapping_status="verified",
            evaluation_status="success",
            observations=(_price(MatchGrade.X, "source-a"),),
            source_hit=True,
        ),
        build_source_evaluation(
            benchmark_model="MODEL-1",
            product_name="Product",
            source_name="source-b",
            mapping_status="verified",
            evaluation_status="success",
            observations=(_price(MatchGrade.X, "source-b"),),
            source_hit=True,
        ),
    )

    summary = summarize_phase0_evaluations(rows, benchmark_products=1)
    assert summary.multi_source_products == 0
    assert summary.multi_source_product_rate == 0.0
