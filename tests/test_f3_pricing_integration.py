from datetime import date
from decimal import Decimal

from purchase_price.collectors.g2b_shopping import unwrap_g2b_page
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


def test_only_identity_verified_g2b_price_enters_reference_range() -> None:
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
    assert assessment.comparable_count == 1
    assert assessment.low == Decimal("7800000")
    assert assessment.high == Decimal("7800000")
    assert assessment.quote_position == "상단 초과"
