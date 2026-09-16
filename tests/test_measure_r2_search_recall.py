from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.scripts.measure_r2_search_recall import (
    _load_manifest,
    _tier_for_result,
    build_report,
)


def _result(*, status: str = "success", grades=(), references=()):
    return SimpleNamespace(
        status=status,
        candidates=tuple(SimpleNamespace(match_grade=grade) for grade in grades),
        reference_candidates=tuple(references),
    )


def test_tier_prefers_direct_ab_over_reference() -> None:
    result = _result(
        grades=(MatchGrade.C, MatchGrade.B),
        references=(SimpleNamespace(),),
    )

    assert _tier_for_result(result) == "DIRECT_AB"


def test_tier_distinguishes_class_reference_and_zero() -> None:
    assert _tier_for_result(_result(grades=(MatchGrade.C,))) == "CLASS_C"
    assert (
        _tier_for_result(_result(references=(SimpleNamespace(),)))
        == "BROAD_REFERENCE"
    )
    assert _tier_for_result(_result()) == "ZERO"
    assert _tier_for_result(_result(status="not_ingested")) == "INDEX_ERROR"


def test_manifest_contains_initial_real_uat_cases() -> None:
    cases = _load_manifest(Path("data/uat/r2-search-recall-cases.json"))

    assert {case["case_id"] for case in cases} == {"flow_c", "apc30d"}
    flow = next(case for case in cases if case["case_id"] == "flow_c")
    assert flow["manufacturer"] == "Maquet"
    assert flow["model_name"] == "FLOW-C"


def test_report_counts_recall_tiers_without_promoting_reference() -> None:
    cases = [
        {
            "case_id": "direct",
            "product_name": "A",
            "manufacturer": "",
            "model_name": "M1",
            "specification": "",
        },
        {
            "case_id": "reference",
            "product_name": "B",
            "manufacturer": "",
            "model_name": "M2",
            "specification": "",
        },
    ]

    direct_candidate = SimpleNamespace(
        source_record_id="1",
        product_title="A M1",
        price=100,
        match_grade=MatchGrade.A,
        match_note="same",
        transaction_date="2026-01-01",
        supplier="seller",
        demand_institution="buyer",
        quantity=None,
        unit=None,
        transaction_type="나라장터 납품요구",
    )
    reference_candidate = SimpleNamespace(
        source_record_id="2",
        product_title="B similar",
        price=200,
        reference_reason="검색 참고",
        raw_object_key="raw/key",
        transaction_date="2026-01-02",
        supplier="seller2",
        demand_institution="buyer2",
        quantity=None,
        unit=None,
        model_name="M2-X",
        transaction_type="나라장터 납품요구",
    )

    def lookup(query, *, quote_unit_price):
        del quote_unit_price
        if query.model_name == "M1":
            return SimpleNamespace(
                status="success",
                candidates=(direct_candidate,),
                reference_candidates=(),
                examined=1,
            )
        return SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(reference_candidate,),
            examined=0,
        )

    report = build_report(cases, lookup=lookup)

    assert report["status"] == "SUCCESS"
    assert report["summary"]["direct_ab_count"] == 1
    assert report["summary"]["broad_reference_count"] == 1
    assert report["summary"]["class_c_count"] == 0
    assert report["cases"][1]["tier"] == "BROAD_REFERENCE"
    assert report["cases"][1]["external_research_rescue"] == "NOT_RUN"
