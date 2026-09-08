from datetime import date
from decimal import Decimal

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_classification_resolver import normalize_product_label
from purchase_price.services.g2b_unmapped_discovery import (
    _candidate_from_record,
    _model_matches_title,
    build_g2b_discovery_terms,
)
from purchase_price.services.price_conditions import PriceConditionProfile
from purchase_price.services.quote_condition_comparison import (
    ConditionComparisonStatus,
    build_quote_condition_profile,
    compare_quote_to_evidence_conditions,
)


def _shopping_row(title: str, *, code: str = "4218200101") -> dict[str, str]:
    return {
        "dtilPrdctClsfcNoNm": "가스마취기",
        "dtilPrdctClsfcNo": code,
        "cntrctDlvrDivNm": "납품요구",
        "cntrctDlvrReqDate": "20260901",
        "cntrctDlvrReqNo": "GOLDEN-1",
        "cntrctDlvrReqChgOrd": "1",
        "prdctSno": "1",
        "prdctIdntNo": "GOLDEN-PRODUCT",
        "prdctIdntNoNm": title,
        "prdctUprc": "66000000",
        "prdctQty": "1",
        "prdctUnit": "대",
        "prdctAmt": "66000000",
        "dminsttNm": "테스트기관",
        "corpNm": "테스트공급사",
        "dlvryCndtnNm": "현장설치",
        "prdctSpcfctn": "vaporizer 포함, monitoring 포함",
    }


def test_apc_label_preserves_co2_and_water_jacket_as_spec_clue() -> None:
    normalized = normalize_product_label("CO₂ Incubator(Water Jacket)")

    assert normalized.base_name == "CO2 Incubator"
    assert normalized.parenthetical_terms == ("Water Jacket",)
    assert build_g2b_discovery_terms("CO₂ Incubator(Water Jacket)")[0] == "CO2 Incubator"
    assert "CO Incubator" not in build_g2b_discovery_terms(
        "CO₂ Incubator(Water Jacket)"
    )


def test_flow_model_identity_is_bounded_and_accessories_are_not_same_model() -> None:
    assert _model_matches_title("FLOW-C", "Maquet FLOW-C Anesthesia System")
    assert not _model_matches_title("FLOW-C", "Maquet FLOW-C20 Anesthesia System")
    assert not _model_matches_title("FLOW-C", "Maquet FLOW-C accessory kit")
    assert not _model_matches_title("FLOW-C", "FLOW-C 부속품 세트")


def test_targeted_class_row_remains_research_candidate_with_provenance() -> None:
    query = ProductQuery(
        product_name="가스 마취기",
        manufacturer="Maquet",
        model_name="FLOW-C",
    )
    candidate = _candidate_from_record(
        _shopping_row("가스마취기, Maquet, FLOW-C"),
        query,
        search_term="4218200101",
        target_detail_code="4218200101",
    )

    assert candidate is not None
    assert candidate.relevance == "모델 표기 후보"
    assert candidate.classification_code == "4218200101"
    assert candidate.search_term == "code:4218200101"
    assert "세부품명번호 서버필터 일치" in candidate.match_reason
    assert candidate.institution == "테스트기관"
    assert candidate.supplier == "테스트공급사"
    assert candidate.quantity == Decimal("1")
    assert candidate.unit == "대"
    assert candidate.item_sequence == "1"
    assert candidate.delivery_condition == "현장설치"
    assert candidate.original_specification


def test_flow_configuration_differences_are_not_collapsed_to_included_or_free() -> None:
    quote = build_quote_condition_profile(
        installation="포함",
        options="Desflurane vaporizer 포함",
        warranty="무상 3년",
    )
    evidence = PriceConditionProfile(
        vat="미확인",
        quantity_unit="1 대",
        delivery="미확인",
        installation="포함",
        options="Sevoflurane vaporizer 포함",
        warranty="무상 1년",
        maintenance="미확인",
        basis_date=date(2026, 9, 1).isoformat(),
    )

    comparison = compare_quote_to_evidence_conditions(quote, evidence)
    by_label = {item.label: item.status for item in comparison.comparisons}

    assert by_label["설치"] == ConditionComparisonStatus.MATCH
    assert by_label["옵션"] == ConditionComparisonStatus.CONFLICT
    assert by_label["보증"] == ConditionComparisonStatus.CONFLICT


def test_missing_flow_configuration_detail_is_unknown_not_match() -> None:
    quote = build_quote_condition_profile(
        options="Desflurane vaporizer 포함",
        warranty="무상 3년",
    )
    evidence = PriceConditionProfile(
        vat="미확인",
        quantity_unit="1 대",
        delivery="미확인",
        installation="미확인",
        options="포함",
        warranty="무상",
        maintenance="미확인",
        basis_date="2026-09-01",
    )

    comparison = compare_quote_to_evidence_conditions(quote, evidence)
    by_label = {item.label: item.status for item in comparison.comparisons}

    assert by_label["옵션"] == ConditionComparisonStatus.UNKNOWN
    assert by_label["보증"] == ConditionComparisonStatus.UNKNOWN
