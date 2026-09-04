from datetime import date
from decimal import Decimal

from purchase_price.collectors.g2b_shopping import unwrap_g2b_page
from purchase_price.collectors.manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_candidate_search import search_mapped_g2b_candidates
from purchase_price.services.g2b_product_mapping import G2BProductMapping
from purchase_price.services.pricing import assess_prices


def _record(record_id: str, manufacturer: str, model: str, price: str) -> dict:
    return {
        "cntrctDlvrDivNm": "납품요구",
        "cntrctDlvrReqDate": "20260715",
        "cntrctDlvrReqNo": record_id,
        "prdctIdntNo": f"P-{record_id}",
        "prdctIdntNoNm": f"인공호흡기, {manufacturer}, {model}, 운반형",
        "prdctUprc": price,
        "prdctQty": "1",
        "prdctUnit": "대",
        "prdctAmt": price,
    }


class StubCollector:
    def fetch_specific_item_page(self, **kwargs):
        items = [
            _record("GOOD", "Stephan", "Sophie", "7800000"),
            _record("CONFLICT", "Other Medical", "Sophie", "4000000"),
        ]
        payload = {
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
        return unwrap_g2b_page(payload), payload


class C5570StubCollector:
    def fetch_specific_item_page(self, **kwargs):
        item = {
            "cntrctDlvrDivNm": "납품요구",
            "cntrctDlvrReqDate": "20260715",
            "cntrctDlvrReqNo": "R26TB02131898",
            "prdctIdntNo": "P-C5570",
            "prdctIdntNoNm": (
                "레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A3, 55ppm/55ppm"
            ),
            "prdctUprc": "2981000",
            "prdctQty": "1",
            "prdctUnit": "대",
            "prdctAmt": "2981000",
        }
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "정상"},
                "body": {
                    "items": [item],
                    "numOfRows": 100,
                    "pageNo": 1,
                    "totalCount": 1,
                },
            }
        }
        return unwrap_g2b_page(payload), payload


def test_only_identity_verified_g2b_price_enters_observed_range() -> None:
    mapping = G2BProductMapping(
        model_name="Sophie",
        product_name="인공호흡기",
        detail_product_name="인공호흡기",
        detail_product_code="4227220901",
        mapping_status="verified",
    )
    result = search_mapped_g2b_candidates(
        StubCollector(),
        ProductQuery(product_name="인공호흡기", manufacturer="Stephan", model_name="Sophie"),
        begin_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        mappings=(mapping,),
    )

    assessment = assess_prices(list(result.candidate_prices), current_quote=Decimal("8000000"))

    assert len(result.candidate_prices) == 2
    assert assessment.observed_count == 1
    assert assessment.low == Decimal("7800000")
    assert assessment.high == Decimal("7800000")
    assert assessment.quote_comparable_count == 0
    assert assessment.quote_position is None


def test_c5570_g2b_and_manufacturer_prices_form_real_multi_source_observed_range() -> None:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        specification="A3,55PPM",
    )
    mapping = G2BProductMapping(
        model_name="ApeosPrint C5570 GK",
        product_name="컬러 레이저프린터",
        detail_product_name="레이저프린터",
        detail_product_code="4321210501",
        mapping_status="verified",
    )
    g2b = search_mapped_g2b_candidates(
        C5570StubCollector(),
        query,
        begin_date=date(2026, 7, 14),
        end_date=date(2026, 8, 13),
        mappings=(mapping,),
    )
    manufacturer = ManufacturerPublicCatalogCollector().search(query)

    evidence = list(g2b.candidate_prices) + manufacturer
    assessment = assess_prices(evidence)

    assert len(g2b.candidate_prices) == 1
    assert len(manufacturer) == 1
    assert assessment.observed_count == 2
    assert assessment.source_count == 2
    assert assessment.low == Decimal("2981000")
    assert assessment.high == Decimal("5500000")
    assert assessment.quote_comparable_count == 0
    assert {row.source_name for row in evidence} == {
        "조달청_나라장터쇼핑몰 품목정보 서비스",
        "FUJIFILM Business Innovation Korea 공식몰",
    }
