from __future__ import annotations

from decimal import Decimal

from purchase_price.schemas import CollectedPrice
from purchase_price.services.g2b_bid_items import G2BBidItemClient, parse_bid_purchase_item
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchAmountType,
)
from purchase_price.services.g2b_research_linking import link_procurement_cases


class FakePortal:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return self.payloads.pop(0)


def _page(items: list[dict], total_count: int | None = None) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {
                "items": items,
                "totalCount": len(items) if total_count is None else total_count,
                "pageNo": 1,
                "numOfRows": 100,
            },
        }
    }


def test_purchase_item_preserves_quantity_unit_and_estimated_price_semantics() -> None:
    item = parse_bid_purchase_item(
        {
            "bidNtceNo": "R26BK01234567",
            "bidNtceOrd": "00",
            "bidNtceDtlSeq": "1",
            "prdctClsfcNo": "42181703",
            "prdctClsfcNoNm": "전신가스마취기",
            "prdctQty": "4",
            "prdctUnit": "SET",
            "presmptUnitPrce": "55,000,000",
            "mnfcturNm": "Maquet",
            "modelNm": "FLOW-C",
        }
    )

    assert item.source_type == G2BResearchSource.BID_ITEM
    assert item.bid_notice_no == "R26BK01234567"
    assert item.product_name == "전신가스마취기"
    assert item.quantity == Decimal("4")
    assert item.unit == "SET"
    assert item.manufacturer == "Maquet"
    assert item.model_name == "FLOW-C"
    assert item.amount == Decimal("55000000")
    assert item.amount_type == ResearchAmountType.ESTIMATED_UNIT_PRICE
    assert not item.is_direct_unit_price
    assert not isinstance(item, CollectedPrice)


def test_purchase_item_client_queries_by_explicit_notice_number() -> None:
    portal = FakePortal(
        [
            _page(
                [
                    {
                        "bidNtceNo": "R26BK01234567",
                        "bidNtceOrd": "00",
                        "bidNtceDtlSeq": "1",
                        "prdctClsfcNoNm": "전신가스마취기",
                        "prdctQty": "4",
                    }
                ]
            )
        ]
    )
    client = G2BBidItemClient("key", client=portal)  # type: ignore[arg-type]

    items, request_count = client.fetch_items(
        bid_notice_no="R26BK01234567",
        bid_notice_order="00",
        max_pages=1,
    )

    assert request_count == 1
    assert len(items) == 1
    _, endpoint, params = portal.calls[0]
    assert endpoint == "getBidPblancListInfoThngPurchsObjPrdct"
    assert params["inqryDiv"] == "2"
    assert params["bidNtceNo"] == "R26BK01234567"
    assert params["bidNtceOrd"] == "00"
    assert params["pageNo"] == 1


def test_item_detail_links_to_bid_and_award_only_by_notice_number() -> None:
    bid = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:1",
        bid_notice_no="R26BK01234567",
        title="마취기 구매",
    )
    item = G2BResearchRecord(
        source_type=G2BResearchSource.BID_ITEM,
        source_record_id="item:1",
        bid_notice_no="R26BK01234567",
        product_name="전신가스마취기",
        quantity=Decimal("4"),
    )
    award = G2BResearchRecord(
        source_type=G2BResearchSource.AWARD,
        source_record_id="award:1",
        bid_notice_no="R26BK01234567",
        amount=Decimal("200000000"),
        amount_type=ResearchAmountType.AWARD_TOTAL,
    )
    same_title_other_notice = G2BResearchRecord(
        source_type=G2BResearchSource.BID_ITEM,
        source_record_id="item:2",
        bid_notice_no="R26BK09999999",
        product_name="전신가스마취기",
        quantity=Decimal("1"),
    )

    cases = link_procurement_cases([bid, item, award, same_title_other_notice])
    linked = next(case for case in cases if case.bid_notice_no == "R26BK01234567")
    other = next(case for case in cases if case.bid_notice_no == "R26BK09999999")

    assert linked.bid_notices == (bid,)
    assert linked.bid_items == (item,)
    assert linked.awards == (award,)
    assert linked.has_item_detail
    assert linked.has_award
    assert other.bid_items == (same_title_other_notice,)
    assert not other.bid_notices
    assert not other.awards
