from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from purchase_price.ui.production_runtime_compat import (
    _guard_contract_enrichment,
    mfds_recall_error_kind,
    mfds_recall_exception_result,
    normalize_mfds_recall_lookup,
    run_market_research_hot_reload_safe,
)


def test_legacy_contract_helper_disables_independent_search_without_new_keyword() -> None:
    captured: dict[str, object] = {}

    def legacy_contract_helper(
        bundle: object,
        *,
        independent_terms: tuple[str, ...],
        timeout_seconds: float,
        max_retries: int,
    ) -> object:
        captured.update(
            independent_terms=independent_terms,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return bundle

    guarded = _guard_contract_enrichment(legacy_contract_helper)
    marker = object()

    assert (
        guarded(
            marker,
            independent_terms=("심장충격기",),
            timeout_seconds=20.0,
            max_retries=2,
        )
        is marker
    )
    assert captured == {
        "independent_terms": (),
        "timeout_seconds": 12.0,
        "max_retries": 1,
    }


def test_current_contract_helper_forces_explicit_deferred_mode() -> None:
    captured: dict[str, object] = {}

    def current_contract_helper(
        bundle: object,
        *,
        independent_terms: tuple[str, ...],
        timeout_seconds: float,
        max_retries: int,
        allow_independent_search: bool = True,
    ) -> object:
        captured.update(
            independent_terms=independent_terms,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            allow_independent_search=allow_independent_search,
        )
        return bundle

    guarded = _guard_contract_enrichment(current_contract_helper)
    marker = object()

    assert (
        guarded(
            marker,
            independent_terms=("심장충격기",),
            timeout_seconds=20.0,
            max_retries=2,
            allow_independent_search=True,
        )
        is marker
    )
    assert captured == {
        "independent_terms": ("심장충격기",),
        "timeout_seconds": 12.0,
        "max_retries": 1,
        "allow_independent_search": False,
    }


def test_mfds_code_30_failure_is_recovered_as_not_authorized() -> None:
    result = SimpleNamespace(
        status="failure",
        records=(),
        error_type="PublicDataClientError",
        error_message=(
            "Public Data Portal API error: "
            "error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30"
        ),
    )

    normalized = normalize_mfds_recall_lookup(result)

    assert normalized.status == "not_authorized"
    assert normalized.records == ()
    assert normalized.error_type == "PublicDataClientError"


def test_mfds_non_authorization_failure_remains_failure() -> None:
    result = SimpleNamespace(
        status="failure",
        error_type="PublicDataClientError",
        error_message="synthetic timeout",
    )

    assert normalize_mfds_recall_lookup(result) is result


def test_uncaught_mfds_code_30_exception_keeps_not_authorized_semantics() -> None:
    result = mfds_recall_exception_result(
        RuntimeError("SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30"),
        model_name="Efficia DFM100",
        product_name="심장 충격기",
    )

    assert result.status == "not_authorized"
    assert result.query_type == "model"
    assert result.query == "Efficia DFM100"


def test_mfds_failure_kind_is_secret_safe_and_actionable() -> None:
    assert (
        mfds_recall_error_kind(
            SimpleNamespace(
                status="failure",
                error_type="PublicDataClientError",
                error_message="SERVICE_ACCESS_DENIED_ERROR code=30",
            )
        )
        == "authorization"
    )
    assert (
        mfds_recall_error_kind(
            SimpleNamespace(
                status="failure",
                error_type="PublicDataTransportError",
                error_message="synthetic transport failure",
            )
        )
        == "transport"
    )
    assert (
        mfds_recall_error_kind(
            SimpleNamespace(
                status="failure",
                error_type="TypeError",
                error_message="synthetic type mismatch",
            )
        )
        == "type_error"
    )


def search_all(query: object) -> object:
    return query


def resolve_classification_research(query: object) -> object:
    return query


def _synthetic_profiled_runner(query: object) -> object:
    search_all(query)
    resolve_classification_research(query)
    return query


def test_runtime_compat_profiles_named_research_substages() -> None:
    timings: dict[str, float] = {}
    marker = object()

    assert (
        run_market_research_hot_reload_safe(
            _synthetic_profiled_runner,
            marker,
            stage_timings=timings,
        )
        is marker
    )
    assert "direct_search_all" in timings
    assert "classification" in timings
    assert "runner_total" in timings


def test_dashboard_uses_runtime_compat_and_emits_latency_marker() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "run_market_research_hot_reload_safe(" in source
    assert "normalize_mfds_recall_lookup(result)" in source
    assert "mfds_recall_exception_result(" in source
    assert 'id="purchase-workspace-runtime-v10"' in source
    assert 'id="purchase-search-timings-v1"' in source
    assert 'id="purchase-research-stage-timings-v1"' in source
    assert 'id="purchase-safety-diagnostic-v1"' in source
    assert 'id="purchase-research-deferred-v1"' in source
    assert '"research_status": "pending"' in source
    assert "def _execute_deferred_research(" in source
    assert "run = SearchRun()" in source


def test_production_smoke_requires_new_runtime_and_records_stage_latency() -> None:
    source = Path("scripts/production_unified_search_smoke.py").read_text(encoding="utf-8")

    assert 'DEPLOYMENT_MARKER = "#purchase-workspace-runtime-v16"' in source
    assert '"direct_search_first_result_seconds"' in source
    assert '"direct_server_search_timings_seconds"' in source
    assert '"direct_workspace_sections_seconds"' in source
    assert '"quote_upload_workspace_seconds"' in source
    assert '"quote_server_search_timings_seconds"' in source
    assert '"direct_research_stage_timings_seconds"' in source
    assert '"quote_research_stage_timings_seconds"' in source
    assert '"direct_safety_diagnostic"' in source
    assert '"quote_safety_diagnostic"' in source
    assert '"direct_research_status"' in source
    assert '"quote_research_status"' in source
    assert "exceeded 25 second latency gate" in source
    assert "exceeded 35 second latency gate" in source
