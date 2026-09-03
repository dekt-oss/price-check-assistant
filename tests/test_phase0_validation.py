from datetime import date
from decimal import Decimal

from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.phase0_validation import (
    build_source_evaluation,
    is_condition_complete_direct_evidence,
    summarize_phase0_by_source,
    summarize_phase0_evaluations,
)


def _price(
    *,
    grade: MatchGrade,
    evidence_type: EvidenceType,
    source_name: str = "source-a",
    traceable: bool = True,
    complete_conditions: bool = False,
) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="Maker",
        product_name="Product",
        model_name="MODEL-1",
        specification="spec",
        price=Decimal("1000"),
        evidence_type=evidence_type,
        source_type=SourceType.PROCUREMENT,
        source_name=source_name,
        source_url="https://example.test/evidence" if traceable else None,
        collected_at=date(2026, 9, 3),
        transaction_date=date(2026, 9, 1) if complete_conditions else None,
        quantity=Decimal("1") if complete_conditions else None,
        unit="EA" if complete_conditions else None,
        vat_status="included" if complete_conditions else None,
        conditions="delivery included" if complete_conditions else None,
        source_record_id="record-1" if traceable else None,
        original_title="Product, Maker, MODEL-1" if traceable else None,
        match_grade=grade,
    )


def test_source_evaluation_separates_direct_reference_and_traceability() -> None:
    direct = _price(
        grade=MatchGrade.A,
        evidence_type=EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        complete_conditions=True,
    )
    reference = _price(grade=MatchGrade.C, evidence_type=EvidenceType.PUBLIC_SALE_PRICE)
    excluded = _price(
        grade=MatchGrade.X,
        evidence_type=EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        traceable=False,
    )
    row = build_source_evaluation(
        benchmark_model="MODEL-1",
        product_name="Product",
        source_name="source-a",
        mapping_status="verified",
        evaluation_status="success",
        observations=(direct, reference, excluded),
        source_hit=True,
        records_seen=10,
        reported_total_count=10,
    )
    assert row.evidence_count == 3
    assert row.direct_evidence_count == 1
    assert row.reference_evidence_count == 1
    assert row.traceable_evidence_count == 2
    assert row.condition_complete_count == 1
    assert is_condition_complete_direct_evidence(direct) is True
    assert is_condition_complete_direct_evidence(reference) is False


def test_summary_keeps_unverified_mapping_out_of_source_hit_denominator() -> None:
    direct = _price(grade=MatchGrade.B, evidence_type=EvidenceType.CONTRACT_UNIT_PRICE)
    rows = (
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="g2b",
            mapping_status="verified", evaluation_status="success",
            observations=(direct,), source_hit=True,
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="g2b",
            mapping_status="verified", evaluation_status="success", source_hit=False,
        ),
        build_source_evaluation(
            benchmark_model="C", product_name="C product", source_name="g2b",
            mapping_status="unverified", evaluation_status="mapping_unverified",
        ),
    )
    summary = summarize_phase0_evaluations(rows, benchmark_products=3)
    assert summary.mapping_ready_products == 2
    assert summary.mapping_readiness_rate == 0.666667
    assert summary.successfully_evaluated_products == 2
    assert summary.evaluation_coverage_rate == 0.666667
    assert summary.source_hit_pairs == 1
    assert summary.successful_source_product_pairs == 2
    assert summary.source_hit_rate == 0.5
    assert summary.direct_evidence_products == 1
    assert summary.direct_evidence_product_rate == 0.5
    assert summary.not_evaluated_products == 1
    assert summary.multi_source_product_rate is None


def test_offline_rows_report_mapping_readiness_without_fake_source_metrics() -> None:
    rows = (
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="g2b",
            mapping_status="verified", evaluation_status="not_run_offline",
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="g2b",
            mapping_status="unverified", evaluation_status="mapping_unverified",
        ),
    )
    summary = summarize_phase0_evaluations(rows, benchmark_products=2)
    assert summary.mapping_ready_products == 1
    assert summary.mapping_readiness_rate == 0.5
    assert summary.successfully_evaluated_products == 0
    assert summary.evaluation_coverage_rate == 0.0
    assert summary.source_hit_rate is None
    assert summary.direct_evidence_product_rate is None
    assert summary.not_evaluated_products == 2


def test_summary_reports_multi_source_only_when_two_sources_are_successful() -> None:
    evidence_a = _price(
        grade=MatchGrade.A, evidence_type=EvidenceType.PUBLIC_SALE_PRICE, source_name="source-a"
    )
    evidence_b = _price(
        grade=MatchGrade.B, evidence_type=EvidenceType.CONTRACT_UNIT_PRICE, source_name="source-b"
    )
    rows = (
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="source-a",
            mapping_status="verified", evaluation_status="success",
            observations=(evidence_a,), source_hit=True,
        ),
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="source-b",
            mapping_status="verified", evaluation_status="success",
            observations=(evidence_b,), source_hit=True,
        ),
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="source-c",
            mapping_status="unverified", evaluation_status="mapping_unverified",
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="source-a",
            mapping_status="verified", evaluation_status="success", source_hit=True,
        ),
    )
    summary = summarize_phase0_evaluations(rows, benchmark_products=2)
    assert summary.multi_source_products == 1
    assert summary.multi_source_product_rate == 0.5
    assert summary.source_hit_rate == 1.0
    assert summary.not_evaluated_products == 0


def test_mixed_source_readiness_is_unique_by_product_and_local_success_counts() -> None:
    direct = _price(
        grade=MatchGrade.A,
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_name="manufacturer-record",
    )
    rows = (
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="g2b",
            mapping_status="verified", evaluation_status="not_run_offline",
        ),
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="manufacturer",
            mapping_status="missing", evaluation_status="mapping_unverified",
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="g2b",
            mapping_status="unverified", evaluation_status="mapping_unverified",
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="manufacturer",
            mapping_status="verified", evaluation_status="success",
            observations=(direct,), source_hit=True,
        ),
    )
    summary = summarize_phase0_evaluations(rows, benchmark_products=2)
    assert summary.mapping_ready_products == 2
    assert summary.mapping_readiness_rate == 1.0
    assert summary.successfully_evaluated_products == 1
    assert summary.evaluation_coverage_rate == 0.5
    assert summary.source_hit_rate == 1.0
    assert summary.direct_evidence_product_rate == 1.0
    assert summary.multi_source_product_rate is None
    assert summary.not_evaluated_products == 1


def test_per_source_summary_keeps_denominators_and_latency_separate() -> None:
    direct = _price(
        grade=MatchGrade.A,
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_name="manufacturer-record",
        complete_conditions=False,
    )
    rows = (
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="manufacturer",
            mapping_status="verified", evaluation_status="success",
            observations=(direct,), source_hit=True, elapsed_ms=10,
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="manufacturer",
            mapping_status="verified", evaluation_status="error", elapsed_ms=30,
        ),
        build_source_evaluation(
            benchmark_model="A", product_name="A product", source_name="g2b",
            mapping_status="unverified", evaluation_status="mapping_unverified",
        ),
        build_source_evaluation(
            benchmark_model="B", product_name="B product", source_name="g2b",
            mapping_status="unverified", evaluation_status="mapping_unverified",
        ),
    )
    summaries = {
        item.source_name: item
        for item in summarize_phase0_by_source(rows, benchmark_products=2)
    }
    manufacturer = summaries["manufacturer"]
    g2b = summaries["g2b"]
    assert manufacturer.mapping_ready_products == 2
    assert manufacturer.mapping_readiness_rate == 1.0
    assert manufacturer.attempted_pairs == 2
    assert manufacturer.successful_pairs == 1
    assert manufacturer.source_hit_pairs == 1
    assert manufacturer.source_hit_rate == 1.0
    assert manufacturer.direct_evidence_products == 1
    assert manufacturer.direct_evidence_product_rate == 1.0
    assert manufacturer.traceability_rate == 1.0
    assert manufacturer.condition_completeness_rate == 0.0
    assert manufacturer.error_pairs == 1
    assert manufacturer.collector_error_rate == 0.5
    assert manufacturer.average_elapsed_ms == 20.0
    assert g2b.mapping_ready_products == 0
    assert g2b.attempted_pairs == 0
    assert g2b.successful_pairs == 0
    assert g2b.source_hit_rate is None
    assert g2b.collector_error_rate is None
    assert g2b.average_elapsed_ms is None
