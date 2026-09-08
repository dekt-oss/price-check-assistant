from __future__ import annotations

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_classification_research import (
    ClassificationResearchStatus,
    build_classification_lookup_requests,
    resolve_classification_research,
)
from purchase_price.services.g2b_classification_resolver import (
    DetailClassSearchField,
    G2BDetailClassCandidate,
    G2BDetailClassSearchResult,
)


class StubResolver:
    def __init__(self, *, fail_terms: set[str] | None = None) -> None:
        self.fail_terms = fail_terms or set()
        self.calls: list[tuple[str, DetailClassSearchField]] = []

    def search_detail_classes(self, *, term: str, field: DetailClassSearchField):
        self.calls.append((term, field))
        if term in self.fail_terms:
            raise PublicDataClientError(f"synthetic resolver failure: {term}")
        if term.casefold() == "carbon dioxide incubators":
            candidate = G2BDetailClassCandidate(
                detail_product_code="4110449801",
                korean_name="이산화탄소배양기",
                english_name="Carbon dioxide incubators",
                use_status="Y",
                search_field=field,
                search_term=term,
            )
            return G2BDetailClassSearchResult(
                search_field=field,
                search_term=term,
                candidates=(candidate,),
                total_count=1,
            )
        return G2BDetailClassSearchResult(
            search_field=field,
            search_term=term,
            candidates=(),
            total_count=0,
        )


def test_apc_label_plans_meaning_preserving_official_class_lookups() -> None:
    requests = build_classification_lookup_requests("CO₂ Incubator(Water Jacket)")

    assert [(row.field, row.term) for row in requests] == [
        (DetailClassSearchField.ENGLISH_NAME, "CO2 Incubator"),
        (DetailClassSearchField.ENGLISH_NAME, "Carbon dioxide Incubator"),
        (DetailClassSearchField.ENGLISH_NAME, "Carbon dioxide incubators"),
    ]


def test_apc_resolution_keeps_spec_clue_and_returns_research_terms_only() -> None:
    resolver = StubResolver()
    result = resolve_classification_research(
        ProductQuery(product_name="CO₂ Incubator(Water Jacket)", model_name="APC-30D"),
        service_key=None,
        client=resolver,  # type: ignore[arg-type]
    )

    assert result.status == ClassificationResearchStatus.SUCCESS
    assert result.normalized_label.base_name == "CO2 Incubator"
    assert result.specification_clues == ("Water Jacket",)
    assert [candidate.detail_product_code for candidate in result.candidates] == ["4110449801"]
    assert "이산화탄소배양기" in result.research_terms
    assert "Carbon dioxide incubators" in result.research_terms
    assert result.request_count == 3
    assert result.failed_request_count == 0


def test_all_resolver_failures_are_not_collapsed_to_normal_zero() -> None:
    requests = build_classification_lookup_requests("CO₂ Incubator(Water Jacket)")
    resolver = StubResolver(fail_terms={row.term for row in requests})

    result = resolve_classification_research(
        ProductQuery(product_name="CO₂ Incubator(Water Jacket)"),
        service_key=None,
        client=resolver,  # type: ignore[arg-type]
    )

    assert result.status == ClassificationResearchStatus.FAILURE
    assert result.failed_request_count == 3
    assert result.candidates == ()
    assert result.status != ClassificationResearchStatus.SUCCESS_0


def test_mixed_success_and_failure_is_partial_not_zero() -> None:
    resolver = StubResolver(fail_terms={"CO2 Incubator"})

    result = resolve_classification_research(
        ProductQuery(product_name="CO₂ Incubator(Water Jacket)"),
        service_key=None,
        client=resolver,  # type: ignore[arg-type]
    )

    assert result.status == ClassificationResearchStatus.PARTIAL
    assert [candidate.detail_product_code for candidate in result.candidates] == ["4110449801"]
    assert result.failed_request_count == 1


def test_missing_catalog_key_is_explicitly_not_configured() -> None:
    result = resolve_classification_research(
        ProductQuery(product_name="CO₂ Incubator(Water Jacket)"),
        service_key=None,
    )

    assert result.status == ClassificationResearchStatus.NOT_CONFIGURED
    assert result.request_count == 0
    assert result.candidates == ()
