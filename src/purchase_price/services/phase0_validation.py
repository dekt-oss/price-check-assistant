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

    successful_models = {row.benchmark_model for row in successful}
    direct_models = {
        row.benchmark_model for row in successful if row.direct_evidence_count > 0
    }
    not_evaluated_models = {
        row.benchmark_model for row in rows if row.evaluation_status not in {"success", "error"}
    }

    integrated_sources = {row.source_name for row in rows if row.source_name}
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

    # Multi-source coverage is not a meaningful metric until at least two independent source
    # adapters are represented in the evaluation input. Returning None prevents a misleading 0%.
    multi_source_rate = (
        _ratio(len(multi_source_models), len(successful_models))
        if len(integrated_sources) >= 2
        else None
    )

    return Phase0ValidationSummary(
        benchmark_products=benchmark_products,
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
