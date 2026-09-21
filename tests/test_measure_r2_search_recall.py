from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.scripts.measure_r2_search_recall import (
    _load_manifest,
    _reference_diagnostic,
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


def test_manifest_keeps_initial_real_uat_cases_when_matrix_expands() -> None:
    cases = _load_manifest(Path("data/uat/r2-search-recall-cases.json"))
    case_ids = {case["case_id"] for case in cases}

    assert {"flow_c", "apc30d"}.issubset(case_ids)
    assert len(cases) >= 2
    flow = next(case for case in cases if case["case_id"] == "flow_c")
    assert flow["manufacturer"] == "Maquet"
    assert flow["model_name"] == "FLOW-C"
    negative = next(case for case in cases if case["case_id"] == "exoatlet_negative_control")
    assert negative["expected_negative"] is True


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
        reference_scope="SAME_CLASS",
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


def test_report_separates_expected_negative_from_unexpected_zero() -> None:
    cases = [
        {
            "case_id": "missing_positive",
            "product_name": "A",
            "manufacturer": "",
            "model_name": "M1",
            "specification": "",
            "expected_negative": False,
        },
        {
            "case_id": "negative_control",
            "product_name": "B",
            "manufacturer": "",
            "model_name": "",
            "specification": "",
            "expected_negative": True,
        },
    ]

    def lookup(query, *, quote_unit_price):
        del query, quote_unit_price
        return SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(),
            examined=0,
        )

    report = build_report(cases, lookup=lookup)

    assert report["summary"]["zero_count"] == 2
    assert report["summary"]["expected_negative_zero_count"] == 1
    assert report["summary"]["unexpected_zero_count"] == 1
    assert report["summary"]["unexpected_zero_rate"] == 1.0

def test_reference_diagnostic_flags_unverified_origin_qualifier_for_review() -> None:
    query = ProductQuery(
        product_name="염기서열분석기",
        manufacturer="Oxford Nanopore",
        model_name="MinION Mk1D",
        specification="MinION Mk1D",
    )
    reference = SimpleNamespace(
        source_record_id="minion-1",
        product_title="DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
        price=13310000,
        product_id="12345678",
        detail_code="4111549901",
    )

    diagnostic = _reference_diagnostic(query, reference)

    assert diagnostic["blocker"] == "UNVERIFIED_MODEL_QUALIFIER"
    assert diagnostic["promotion_candidate"] is True
    assert diagnostic["parsed_model_name"] == "MinION MK1D"
    assert diagnostic["model_qualifier"] == "GB"
    assert diagnostic["catalog_url"] == (
        "https://goods.g2b.go.kr/search/productSearchView.do?"
        "goodsClsfcNo=4111549901&goodsIdntfcNo=12345678"
    )


def test_reference_diagnostic_does_not_promote_different_model_reference() -> None:
    query = ProductQuery(
        product_name="이산화탄소배양기",
        manufacturer="ASTEC",
        model_name="APC-30D",
    )
    reference = SimpleNamespace(
        source_record_id="incubator-1",
        product_title="이산화탄소배양기, Thermo fisher scientific, (US)Forma 4111, 184L",
        price=10120000,
    )

    diagnostic = _reference_diagnostic(query, reference)

    assert diagnostic["promotion_candidate"] is False
    assert diagnostic["blocker"] == "REFERENCE_ONLY"


def test_report_counts_broad_reference_promotion_candidates() -> None:
    cases = [
        {
            "case_id": "minion",
            "product_name": "염기서열분석기",
            "manufacturer": "Oxford Nanopore",
            "model_name": "MinION Mk1D",
            "specification": "MinION Mk1D",
        }
    ]
    reference = SimpleNamespace(
        source_record_id="minion-1",
        product_title="DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
        price=13310000,
        reference_reason="모델명 포함 거래 참고",
        raw_object_key="raw/minion",
        transaction_date="2026-09-01",
        supplier="seller",
        demand_institution="buyer",
        quantity=1,
        unit="대",
        model_name="MinION MK1D",
        transaction_type="나라장터 납품요구",
    )

    def lookup(query, *, quote_unit_price):
        del query, quote_unit_price
        return SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(reference,),
            examined=0,
        )

    report = build_report(cases, lookup=lookup)

    assert report["summary"]["promotion_candidate_case_count"] == 1
    assert report["summary"]["promotion_candidate_count"] == 1
    assert report["summary"]["promotion_blocker_counts"] == {
        "UNVERIFIED_MODEL_QUALIFIER": 1
    }
    assert report["cases"][0]["promotion_candidates"][0]["promotion_candidate"] is True


def test_reference_diagnostic_preserves_catalog_identity_for_review() -> None:
    query = ProductQuery(
        product_name="염기서열분석기",
        manufacturer="Oxford Nanopore",
        model_name="MinION Mk1D",
        specification="MinION Mk1D",
    )
    reference = SimpleNamespace(
        source_record_id="minion-1",
        raw_object_key="raw/v1/example.json.gz",
        product_title="DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
        price=13310000,
        product_id="25900137",
        detail_code="4110530101",
    )

    diagnostic = _reference_diagnostic(query, reference)

    assert diagnostic["product_id"] == "25900137"
    assert diagnostic["detail_code"] == "4110530101"
    assert diagnostic["raw_object_key"] == "raw/v1/example.json.gz"
    assert "goodsIdntfcNo=25900137" in diagnostic["catalog_url"]


def test_report_summarizes_best_broad_reference_scope() -> None:
    cases = [
        {
            "case_id": "reference",
            "product_name": "A",
            "manufacturer": "Maker",
            "model_name": "M1",
            "specification": "",
        }
    ]
    reference = SimpleNamespace(
        source_record_id="r1",
        product_title="A, Maker, M2",
        price=100,
        reference_reason="동일 제조사·동일 세부품명 참고",
        reference_scope="SAME_MANUFACTURER_CLASS",
        raw_object_key="raw/r1",
        transaction_date="2026-01-01",
        supplier="seller",
        demand_institution="buyer",
        quantity=1,
        unit="EA",
        model_name="M2",
        product_id=None,
        detail_code="123",
        transaction_type="나라장터 납품요구",
    )

    def lookup(query, *, quote_unit_price):
        del query, quote_unit_price
        return SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(reference,),
            examined=0,
        )

    report = build_report(cases, lookup=lookup)

    assert report["cases"][0]["best_reference_scope"] == "SAME_MANUFACTURER_CLASS"
    assert report["summary"]["broad_reference_scope_case_counts"][
        "SAME_MANUFACTURER_CLASS"
    ] == 1
