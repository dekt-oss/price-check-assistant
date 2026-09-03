from datetime import date
from decimal import Decimal

import pytest

from purchase_price.collectors.g2b_shopping import unwrap_g2b_page
from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_candidate_search import search_mapped_g2b_candidates
from purchase_price.services.g2b_product_mapping import (
    G2BMappingError,
    G2BProductMapping,
    filter_g2b_query_candidates,
    load_g2b_product_mappings,
    resolve_verified_g2b_mapping,
)


def _record(record_id: str, title: str, price: str = "5000000") -> dict:
    return {
        "cntrctDlvrDivNm": "납품요구",
        "cntrctDlvrReqDate": "20260715",
        "cntrctDlvrReqNo": record_id,
        "prdctIdntNo": f"P-{record_id}",
        "prdctIdntNoNm": title,
        "prdctUprc": price,
        "prdctQty": "1",
        "prdctUnit": "대",
        "prdctAmt": price,
    }


def _payload(items: list[dict]) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "items": items,
                "numOfRows": 100,
                "pageNo": 1,
                "totalCount": len(items),
            },
        }
    }


class StubCollector:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.detail_product_names: list[str] = []

    def fetch_specific_item_page(self, **kwargs):
        self.detail_product_names.append(kwargs["detail_product_name"])
        return unwrap_g2b_page(self.payload), self.payload


def test_default_registry_contains_all_phase0_rows_but_only_verified_rows_resolve() -> None:
    mappings = load_g2b_product_mappings()

    assert len(mappings) == 20
    assert sum(mapping.verified for mapping in mappings) == 2

    sophie = resolve_verified_g2b_mapping(ProductQuery(model_name="Sophie"), mappings)
    galaxy = resolve_verified_g2b_mapping(
        ProductQuery(model_name="NT960XJG-K72AG"), mappings
    )
    tn500 = resolve_verified_g2b_mapping(ProductQuery(model_name="TN500"), mappings)

    assert sophie is not None
    assert sophie.detail_product_name == "인공호흡기"
    assert sophie.detail_product_code == "4227220901"
    assert galaxy is not None
    assert galaxy.detail_product_name == "노트북컴퓨터"
    assert galaxy.detail_product_code == "4321150301"
    assert tn500 is None


def test_model_token_candidate_filter_ignores_punctuation_and_rejects_other_models() -> None:
    records = [
        _record(
            "A",
            "노트북컴퓨터, 삼성전자, NT960XJG-K72AG, Intel Core Ultra",
            "2200000",
        ),
        _record(
            "B",
            "노트북컴퓨터, 삼성전자, NT750XHD-K5P62, Intel Core Ultra",
            "1600000",
        ),
    ]

    candidates = filter_g2b_query_candidates(
        records,
        ProductQuery(model_name="NT960XJG K72AG"),
    )

    assert len(candidates) == 1
    assert candidates[0]["cntrctDlvrReqNo"] == "A"


def _sophie_mapping() -> G2BProductMapping:
    return G2BProductMapping(
        model_name="Sophie",
        product_name="인공호흡기",
        detail_product_name="인공호흡기",
        detail_product_code="4227220901",
        mapping_status="verified",
    )


def test_mapped_search_promotes_candidate_to_a_only_with_query_spec_evidence() -> None:
    collector = StubCollector(
        _payload(
            [
                _record("SOPHIE-1", "인공호흡기, Stephan, Sophie, 운반형", "7800000"),
                _record("OTHER-1", "인공호흡기, 조선기기, CSI-2000, 운반형", "5000000"),
            ]
        )
    )

    result = search_mapped_g2b_candidates(
        collector,
        ProductQuery(
            product_name="인공호흡기",
            manufacturer="Stephan",
            model_name="Sophie",
            specification="운반형",
        ),
        begin_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        mappings=(_sophie_mapping(),),
    )

    assert collector.detail_product_names == ["인공호흡기"]
    assert result.records_seen == 2
    assert len(result.candidate_prices) == 1
    candidate = result.candidate_prices[0]
    assert candidate.price == Decimal("7800000")
    assert candidate.manufacturer == "Stephan"
    assert candidate.model_name == "Sophie"
    assert candidate.specification == "운반형"
    assert candidate.match_grade == MatchGrade.A
    assert "specification=compatible" in (candidate.match_note or "")


def test_mapped_search_same_model_without_query_spec_is_b() -> None:
    collector = StubCollector(
        _payload([_record("SOPHIE-B", "인공호흡기, Stephan, Sophie, 운반형", "7800000")])
    )

    result = search_mapped_g2b_candidates(
        collector,
        ProductQuery(product_name="인공호흡기", manufacturer="Stephan", model_name="Sophie"),
        begin_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        mappings=(_sophie_mapping(),),
    )

    assert len(result.candidate_prices) == 1
    assert result.candidate_prices[0].match_grade == MatchGrade.B
    assert "specification=not_provided" in (result.candidate_prices[0].match_note or "")


def test_mapped_search_keeps_same_model_with_conflicting_manufacturer_as_x() -> None:
    collector = StubCollector(
        _payload([_record("SOPHIE-X", "인공호흡기, Other Medical, Sophie, 운반형")])
    )

    result = search_mapped_g2b_candidates(
        collector,
        ProductQuery(product_name="인공호흡기", manufacturer="Stephan", model_name="Sophie"),
        begin_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        mappings=(_sophie_mapping(),),
    )

    assert len(result.candidate_prices) == 1
    assert result.candidate_prices[0].match_grade == MatchGrade.X
    assert "manufacturer=conflict" in (result.candidate_prices[0].match_note or "")


def test_mapped_search_refuses_unverified_classification() -> None:
    mapping = G2BProductMapping(
        model_name="TN500",
        product_name="인큐베이터(인공보육기)",
        detail_product_name=None,
        detail_product_code=None,
        mapping_status="unverified",
    )
    collector = StubCollector(_payload([]))

    with pytest.raises(G2BMappingError, match="No verified G2B"):
        search_mapped_g2b_candidates(
            collector,
            ProductQuery(model_name="TN500"),
            begin_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            mappings=(mapping,),
        )
