from datetime import date

import pytest

from purchase_price.collectors import g2b_shopping, g2b_verified_search
from purchase_price.schemas import ProductQuery
from purchase_price.services import g2b_adaptive_search, g2b_pagination
from purchase_price.services.g2b_product_mapping import G2BProductMapping

QUERY = ProductQuery(
    product_name="인공호흡기",
    manufacturer="Stephan",
    model_name="Sophie",
)
VERIFIED_MAPPING = G2BProductMapping(
    model_name="Sophie",
    product_name="인공호흡기",
    detail_product_name="인공호흡기",
    detail_product_code="4227220901",
    mapping_status="verified",
)


def _record(record_id: str, *, day: str, price: str = "7800000") -> dict:
    return {
        "cntrctDlvrDivNm": "납품요구",
        "dtilPrdctClsfcNo": "4227220901",
        "cntrctDlvrReqDate": day,
        "cntrctDlvrReqNo": record_id,
        "prdctIdntNo": f"P-{record_id}",
        "prdctIdntNoNm": "인공호흡기, Stephan, Sophie, 운반형",
        "prdctUprc": price,
        "prdctQty": "1",
        "prdctUnit": "대",
        "prdctAmt": price,
    }


def _payload(items: list[dict], *, page_no: int, total_count: int) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "items": items,
                "numOfRows": len(items),
                "pageNo": page_no,
                "totalCount": total_count,
            },
        }
    }


class AdaptiveStubCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date, int]] = []

    def fetch_specific_item_page(self, **kwargs):
        begin = kwargs["begin_date"]
        end = kwargs["end_date"]
        page_no = kwargs["page_no"]
        self.calls.append((begin, end, page_no))

        if begin == date(2026, 7, 1) and end == date(2026, 7, 4):
            payload = _payload(
                [_record("FULL-1", day="20260701")],
                page_no=1,
                total_count=2,
            )
        elif begin == date(2026, 7, 1) and end == date(2026, 7, 2):
            payload = _payload(
                [_record("LEFT-1", day="20260702")],
                page_no=1,
                total_count=1,
            )
        elif begin == date(2026, 7, 3) and end == date(2026, 7, 4):
            payload = _payload(
                [_record("RIGHT-1", day="20260703", price="7900000")],
                page_no=1,
                total_count=1,
            )
        else:
            raise AssertionError(f"unexpected window: {begin}..{end} page={page_no}")
        return g2b_shopping.unwrap_g2b_page(payload), payload


def test_adaptive_search_bisects_only_pagination_limit_windows() -> None:
    collector = AdaptiveStubCollector()

    result = g2b_adaptive_search.search_mapped_g2b_candidates_adaptive(
        collector,
        QUERY,
        begin_date=date(2026, 7, 1),
        end_date=date(2026, 7, 4),
        mappings=(VERIFIED_MAPPING,),
        num_of_rows=1,
        max_pages=1,
    )

    assert collector.calls == [
        (date(2026, 7, 1), date(2026, 7, 4), 1),
        (date(2026, 7, 1), date(2026, 7, 2), 1),
        (date(2026, 7, 3), date(2026, 7, 4), 1),
    ]
    assert [(window.begin_date, window.end_date) for window in result.windows] == [
        (date(2026, 7, 1), date(2026, 7, 2)),
        (date(2026, 7, 3), date(2026, 7, 4)),
    ]
    assert len(result.candidate_prices) == 2
    assert {price.price for price in result.candidate_prices} == {7800000, 7900000}
    assert all(price.source_record_id for price in result.candidate_prices)


class OneDayOverflowCollector:
    def fetch_specific_item_page(self, **kwargs):
        payload = _payload(
            [_record("DAY-1", day="20260701")],
            page_no=kwargs["page_no"],
            total_count=2,
        )
        return g2b_shopping.unwrap_g2b_page(payload), payload


def test_adaptive_search_fails_closed_when_one_day_still_exceeds_cap() -> None:
    with pytest.raises(g2b_pagination.G2BPaginationLimitError, match="could not fully collect"):
        g2b_adaptive_search.search_mapped_g2b_candidates_adaptive(
            OneDayOverflowCollector(),
            QUERY,
            begin_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            mappings=(VERIFIED_MAPPING,),
            num_of_rows=1,
            max_pages=1,
        )


class SingleWindowCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def fetch_specific_item_page(self, **kwargs):
        self.calls.append((kwargs["begin_date"], kwargs["end_date"]))
        payload = _payload(
            [_record("LIVE-1", day="20260710")],
            page_no=kwargs["page_no"],
            total_count=1,
        )
        return g2b_shopping.unwrap_g2b_page(payload), payload


def test_user_collector_requires_exact_model_and_verified_mapping() -> None:
    stub = SingleWindowCollector()
    collector = g2b_verified_search.VerifiedG2BShoppingSearchCollector(
        collector=stub,
        mappings=(VERIFIED_MAPPING,),
        lookback_days=10,
        end_date=date(2026, 7, 10),
    )

    result = collector.search(QUERY)

    assert len(result) == 1
    assert stub.calls == [(date(2026, 7, 1), date(2026, 7, 10))]

    no_model = ProductQuery(product_name="인공호흡기", manufacturer="Stephan")
    assert collector.search(no_model) == []
    assert len(stub.calls) == 1

    unverified = G2BProductMapping(
        model_name="Sophie",
        product_name="인공호흡기",
        detail_product_name="인공호흡기",
        detail_product_code="4227220901",
        mapping_status="unverified",
    )
    unverified_collector = g2b_verified_search.VerifiedG2BShoppingSearchCollector(
        collector=stub,
        mappings=(unverified,),
        lookback_days=10,
        end_date=date(2026, 7, 10),
    )
    assert unverified_collector.search(QUERY) == []
    assert len(stub.calls) == 1
