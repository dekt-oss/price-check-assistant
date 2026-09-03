from __future__ import annotations

from dataclasses import dataclass

from purchase_price.domain import DIRECT_PRICE_EVIDENCE_TYPES, MatchGrade
from purchase_price.schemas import CollectedPrice


@dataclass(frozen=True)
class Phase0SourceEvaluation:
    benchmark_model: str
    product_name: str
    source_name: str
    mapping_status: str
    evaluation_status: str
    source_hit: bool | None = None
    records_seen: int | None = None
    reported_total_count: int | None = None
    evidence_count: int = 0
    direct_evidence_count: int = 0
    reference_evidence_count: int = 0
    traceable_evidence_count: int = 0
    condition_complete_count: int = 0
    elapsed_ms: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Phase0ValidationSummary:
    benchmark_products: int
    mapping_ready_products: int
    mapping_readiness_rate: float | None
    successfully_evaluated_products: int
    evaluation_coverage_rate: float | None
    attempted_source_product_pairs: int
    successful_source_product_pairs: int
    source_hit_pairs: int
    source_hit_rate: float | None
    direct_evidence_products: int
    direct_evidence_product_rate: float | None
    multi_source_products: int
    multi_source_product_rate: float | None
    evidence_records: int
    traceable_evidence_records: int
    traceability_rate: float | None
    direct_evidence_records: int
    condition_complete_direct_records: int
    condition_completeness_rate: float | None
    error_pairs: int
    collector_error_rate: float | None
    not_evaluated_products: int


@dataclass(frozen=True)
class Phase0PerSourceSummary:
    source_name: str
    benchmark_products: int
    mapping_ready_products: int
    mapping_readiness_rate: float | None
    attempted_pairs: int
    successful_pairs: int
    source_hit_pairs: int
    source_hit_rate: float | None
    direct_evidence_products: int
    direct_evidence_product_rate: float | None
    evidence_records: int
    traceable_evidence_records: int
    traceability_rate: float | None
    direct_evidence_records: int
    condition_complete_direct_records: int
    condition_completeness_rate: float | None
    error_pairs: int
    collector_error_rate: float | None
    average_elapsed_ms: float | None


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def is_direct_evidence(observation: CollectedPrice) -> bool:
    return (
        observation.match_grade in {MatchGrade.A, MatchGrade.B}
        and observation.evidence_type in DIRECT_PRICE_EVIDENCE_TYPES
    )


def is_reference_evidence(observation: CollectedPrice) -> bool:
    return observation.match_grade in {MatchGrade.C, MatchGrade.D}


def is_traceable_evidence(observation: CollectedPrice) -> bool:
    return bool(
        observation.source_name
        and observation.source_record_id
        and (observation.source_url or observation.original_title)
    )


def is_condition_complete_direct_evidence(observation: CollectedPrice) -> bool:
    """Return the Phase 0 v0 condition-completeness decision.

    The current normalized schema does not yet split install/shipping/options/warranty into
    individual columns. Until it does, v0 requires the structured fields that *are* available:
    quantity, unit, transaction date, VAT status, and a non-empty conditions string.
    This intentionally produces a conservative score rather than assuming missing conditions.
    """

    if not is_direct_evidence(observation):
        return False
    return bool(
        observation.quantity is not None
        and observation.unit
        and observation.transaction_date is not None
        and observation.vat_status
        and observation.conditions
    )


def build_source_evaluation(
    *,
    benchmark_model: str,
    product_name: str,
    source_name: str,
    mapping_status: str,
    evaluation_status: str,
    observations: tuple[CollectedPrice, ...] = (),
    source_hit: bool | None = None,
    records_seen: int | None = None,
    reported_total_count: int | None = None,
    elapsed_ms: int | None = None,
    reason: str | None = None,
) -> Phase0SourceEvaluation:
    return Phase0SourceEvaluation(
        benchmark_model=benchmark_model,
        product_name=product_name,
        source_name=source_name,
        mapping_status=mapping_status,
        evaluation_status=evaluation_status,
        source_hit=source_hit,
        records_seen=records_seen,
        reported_total_count=reported_total_count,
        evidence_count=len(observations),
        direct_evidence_count=sum(is_direct_evidence(row) for row in observations),
        reference_evidence_count=sum(is_reference_evidence(row) for row in observations),
        traceable_evidence_count=sum(is_traceable_evidence(row) for row in observations),
        condition_complete_count=sum(
            is_condition_complete_direct_evidence(row) for row in observations
        ),
        elapsed_ms=elapsed_ms,
        reason=reason,
    )


def summarize_phase0_evaluations(
    rows: tuple[Phase0SourceEvaluation, ...],
    *,
    benchmark_products: int,
) -> Phase0ValidationSummary:
    attempted = tuple(row for row in rows if row.evaluation_status in {"success", "error"})
    successful = tuple(row for row in rows if row.evaluation_status == "success")
    errors = tuple(row for row in rows if row.evaluation_status == "error")

    all_models = {row.benchmark_model for row in rows}
    attempted_models = {row.benchmark_model for row in attempted}
    successful_models = {row.benchmark_model for row in successful}
    mapping_ready_models = {
        row.benchmark_model for row in rows if row.mapping_status.casefold() == "verified"
    }
    direct_models = {
        row.benchmark_model for row in successful if row.direct_evidence_count > 0
    }
    not_evaluated_models = all_models - attempted_models

    # A second source adapter should only activate Multi-source Rate after it has produced at
    # least one successful evaluation. Merely having a placeholder/unverified row must not turn
    # an unavailable metric into a misleading 0%.
    successfully_integrated_sources = {row.source_name for row in successful if row.source_name}
    evidence_sources_by_model: dict[str, set[str]] = {}
    for row in successful:
        if row.evidence_count <= 0:
            continue
        evidence_sources_by_model.setdefault(row.benchmark_model, set()).add(row.source_name)
    multi_source_models = {
        model for model, sources in evidence_sources_by_model.items() if len(sources) >= 2
    }

    evidence_records = sum(row.evidence_count for row in successful)
    traceable_records = sum(row.traceable_evidence_count for row in successful)
    direct_records = sum(row.direct_evidence_count for row in successful)
    condition_complete = sum(row.condition_complete_count for row in successful)
    source_hits = sum(row.source_hit is True for row in successful)

    multi_source_rate = (
        _ratio(len(multi_source_models), len(successful_models))
        if len(successfully_integrated_sources) >= 2
        else None
    )

    return Phase0ValidationSummary(
        benchmark_products=benchmark_products,
        mapping_ready_products=len(mapping_ready_models),
        mapping_readiness_rate=_ratio(len(mapping_ready_models), benchmark_products),
        successfully_evaluated_products=len(successful_models),
        evaluation_coverage_rate=_ratio(len(successful_models), benchmark_products),
        attempted_source_product_pairs=len(attempted),
        successful_source_product_pairs=len(successful),
        source_hit_pairs=source_hits,
        source_hit_rate=_ratio(source_hits, len(successful)),
        direct_evidence_products=len(direct_models),
        direct_evidence_product_rate=_ratio(len(direct_models), len(successful_models)),
        multi_source_products=len(multi_source_models),
        multi_source_product_rate=multi_source_rate,
        evidence_records=evidence_records,
        traceable_evidence_records=traceable_records,
        traceability_rate=_ratio(traceable_records, evidence_records),
        direct_evidence_records=direct_records,
        condition_complete_direct_records=condition_complete,
        condition_completeness_rate=_ratio(condition_complete, direct_records),
        error_pairs=len(errors),
        collector_error_rate=_ratio(len(errors), len(attempted)),
        not_evaluated_products=len(not_evaluated_models),
    )


def summarize_phase0_by_source(
    rows: tuple[Phase0SourceEvaluation, ...],
    *,
    benchmark_products: int,
) -> tuple[Phase0PerSourceSummary, ...]:
    """Summarize evidence coverage independently for every source adapter.

    Mapping-unverified and offline-skipped rows stay visible as readiness gaps but never enter
    source-hit or collector-error denominators. This prevents a source with incomplete mapping
    coverage from looking like it searched the product and found nothing.
    """

    summaries: list[Phase0PerSourceSummary] = []
    for source_name in sorted({row.source_name for row in rows if row.source_name}):
        source_rows = tuple(row for row in rows if row.source_name == source_name)
        attempted = tuple(
            row for row in source_rows if row.evaluation_status in {"success", "error"}
        )
        successful = tuple(row for row in source_rows if row.evaluation_status == "success")
        errors = tuple(row for row in source_rows if row.evaluation_status == "error")
        mapping_ready_models = {
            row.benchmark_model
            for row in source_rows
            if row.mapping_status.casefold() == "verified"
        }
        successful_models = {row.benchmark_model for row in successful}
        direct_models = {
            row.benchmark_model for row in successful if row.direct_evidence_count > 0
        }
        source_hits = sum(row.source_hit is True for row in successful)
        evidence_records = sum(row.evidence_count for row in successful)
        traceable_records = sum(row.traceable_evidence_count for row in successful)
        direct_records = sum(row.direct_evidence_count for row in successful)
        condition_complete = sum(row.condition_complete_count for row in successful)
        elapsed_values = [row.elapsed_ms for row in attempted if row.elapsed_ms is not None]
        average_elapsed_ms = (
            round(sum(elapsed_values) / len(elapsed_values), 2) if elapsed_values else None
        )

        summaries.append(
            Phase0PerSourceSummary(
                source_name=source_name,
                benchmark_products=benchmark_products,
                mapping_ready_products=len(mapping_ready_models),
                mapping_readiness_rate=_ratio(len(mapping_ready_models), benchmark_products),
                attempted_pairs=len(attempted),
                successful_pairs=len(successful),
                source_hit_pairs=source_hits,
                source_hit_rate=_ratio(source_hits, len(successful)),
                direct_evidence_products=len(direct_models),
                direct_evidence_product_rate=_ratio(
                    len(direct_models), len(successful_models)
                ),
                evidence_records=evidence_records,
                traceable_evidence_records=traceable_records,
                traceability_rate=_ratio(traceable_records, evidence_records),
                direct_evidence_records=direct_records,
                condition_complete_direct_records=condition_complete,
                condition_completeness_rate=_ratio(condition_complete, direct_records),
                error_pairs=len(errors),
                collector_error_rate=_ratio(len(errors), len(attempted)),
                average_elapsed_ms=average_elapsed_ms,
            )
        )

    return tuple(summaries)
