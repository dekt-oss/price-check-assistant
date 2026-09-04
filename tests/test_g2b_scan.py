from datetime import date

import pytest

from purchase_price.collectors.g2b_shopping import unwrap_g2b_page
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_product_mapping import G2BProductMapping
from purchase_price.services.g2b_scan import (
    iter_date_chunks,
    scan_exact_model_candidates,
)

QUERY = ProductQuery(
    product_name="노트북컴퓨터",
    manufacturer="삼성전자",
    model_name="NT960XJG-K72AG",
    specification="NT960XJG-K72AG",
)
MAPPINGS = (
    G2BProductMapping(
        model_name="NT960XJG-K72AG",
        product_name="노트북컴퓨터",
        detail_product_name="노트북컴퓨터",
        detail_product_code="4321150301",
        mapping_status="verified",
    ),
)


def _record(record_id: str, title: str, *, price: str = "2000000", day: str = "20260715") -> dict:
    return {
        "cntrctDlvrDivNm": "납품요구",
        "cntrctDlvrReqDate": day,
        "cntrctDlvrReqNo": record_id,
        "prdctIdntNo": f"P-{record_id}",
        "prdctIdntNoNm": title,
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


class WindowStubCollector:
    """Serve pages keyed by (begin_date, end_date, page_no) so window boundaries are asserted."""

    def __init__(self, pages: dict[tuple[date, date, int], dict]) -> None:
        self.pages = pages
        self.requests: list[tuple[date, date, int]] = []

    def fetch_specific_item_page(self, **kwargs):
        key = (kwargs["begin_date"], kwargs["end_date"], kwargs["page_no"])
        self.requests.append(key)
        payload = self.pages[key]
        return unwrap_g2b_page(payload), payload


def test_date_chunks_are_consecutive_inclusive_and_bounded() -> None:
    chunks = list(iter_date_chunks(date(2026, 1, 1), date(2026, 3, 5), max_days=31))

    assert [(c.begin, c.end) for c in chunks] == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 3, 3)),
        (date(2026, 3, 4), date(2026, 3, 5)),
    ]
    assert list(iter_date_chunks(date(2026, 7, 14), date(2026, 7, 14), max_days=31)) == [
        chunks[0].__class__(begin=date(2026, 7, 14), end=date(2026, 7, 14))
    ]
    with pytest.raises(ValueError):
        list(iter_date_chunks(date(2026, 2, 1), date(2026, 1, 1), max_days=31))
    with pytest.raises(ValueError):
        list(iter_date_chunks(date(2026, 1, 1), date(2026, 1, 2), max_days=0))


def test_scan_paginates_every_window_and_dedupes_repeated_identities() -> None:
    w1 = (date(2026, 7, 1), date(2026, 7, 10))
    w2 = (date(2026, 7, 11), date(2026, 7, 15))
    same_title = "노트북컴퓨터, 삼성전자, (VN)NT960XJG-K72AG, Intel Core Ultra 7 256V"
    other_title = "노트북컴퓨터, 삼성전자, (VN)NT960XHA-KG71G, Intel Core Ultra 7 256V"
    collector = WindowStubCollector(
        {
            (*w1, 1): _payload(
                [_record("R-1", same_title, day="20260702"), _record("R-2", other_title)],
                page_no=1,
                total_count=3,
            ),
            (*w1, 2): _payload(
                [_record("R-3", same_title, price="2100000", day="20260709")],
                page_no=2,
                total_count=3,
            ),
            (*w2, 1): _payload(
                [_record("R-4", same_title, day="20260712")], page_no=1, total_count=1
            ),
        }
    )

    result = scan_exact_model_candidates(
        collector,
        QUERY,
        begin_date=w1[0],
        end_date=w2[1],
        mappings=MAPPINGS,
        chunk_days=10,
        num_of_rows=2,
        max_pages_per_chunk=5,
    )

    assert collector.requests == [(*w1, 1), (*w1, 2), (*w2, 1)]
    assert result.complete
    assert [c.status for c in result.chunks] == ["complete", "complete"]
    assert [c.records_seen for c in result.chunks] == [3, 1]
    assert [c.candidate_count for c in result.chunks] == [2, 1]
    assert result.chunks[0].grade_counts == {"B": 2}

    # The other model never carries the query token, so it is not a candidate at all.
    # 3 transactions of 1 distinct identity; the exact model behind verified (VN) origin is B.
    assert result.transaction_count == 3
    assert len(result.candidates) == 1
    exact = next(c for c in result.candidates if "K72AG" in c.candidate_title)
    assert exact.transaction_count == 3
    assert exact.predicted_grade == "B"
    assert "model=exact_with_verified_origin" in exact.match_note
    assert exact.first_transaction_date == date(2026, 7, 2)
    assert exact.last_transaction_date == date(2026, 7, 12)
    assert str(exact.min_price) == "2000000" and str(exact.max_price) == "2100000"
    assert exact.source_record_ids == ("R-1", "R-3", "R-4")



def test_scan_keeps_unverified_qualifier_candidates_at_x() -> None:
    # Only (CN)/(VN) were verified as G2B origin metadata. Every other leading qualifier must
    # still fail closed through the scan path, so an unverified one never reaches A/B and can
    # never enter the direct reference range.
    window = (date(2026, 7, 1), date(2026, 7, 10))
    collector = WindowStubCollector(
        {
            (*window, 1): _payload(
                [
                    _record(
                        "R-1",
                        "노트북컴퓨터, 삼성전자, (재제조)NT960XJG-K72AG, Intel Core Ultra 7 256V",
                    )
                ],
                page_no=1,
                total_count=1,
            )
        }
    )

    result = scan_exact_model_candidates(
        collector,
        QUERY,
        begin_date=window[0],
        end_date=window[1],
        mappings=MAPPINGS,
        chunk_days=10,
        num_of_rows=100,
        max_pages_per_chunk=5,
    )

    assert result.complete
    assert result.chunks[0].grade_counts == {"X": 1}
    assert result.candidates[0].predicted_grade == "X"
    assert "model=exact_with_unverified_qualifier" in result.candidates[0].match_note

def test_scan_marks_truncated_window_incomplete_and_continues() -> None:
    w1 = (date(2026, 7, 1), date(2026, 7, 10))
    w2 = (date(2026, 7, 11), date(2026, 7, 15))
    title = "노트북컴퓨터, 삼성전자, NT960XJG-K72AG, 16GB"
    collector = WindowStubCollector(
        {
            # totalCount says 2 pages, but the cap allows only 1 -> must not look complete
            (*w1, 1): _payload([_record("R-1", title)], page_no=1, total_count=2),
            (*w2, 1): _payload([_record("R-2", title)], page_no=1, total_count=1),
        }
    )

    result = scan_exact_model_candidates(
        collector,
        QUERY,
        begin_date=w1[0],
        end_date=w2[1],
        mappings=MAPPINGS,
        chunk_days=10,
        num_of_rows=1,
        max_pages_per_chunk=1,
    )

    assert not result.complete
    assert result.chunks[0].status == "incomplete"
    assert "safety limit" in (result.chunks[0].error or "")
    assert result.chunks[1].status == "complete"
    # Only the complete window's record is reported as a candidate.
    assert result.transaction_count == 1
    assert result.candidates[0].predicted_grade == "B"
