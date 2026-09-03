from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.collectors.g2b_shopping import SOURCE_NAME, unwrap_g2b_page
from purchase_price.db import Base
from purchase_price.models import RawEvidence
from purchase_price.repositories.evidence import start_collection_run
from purchase_price.services.g2b_shopping_collection import (
    collect_specific_item_history,
    iter_specific_item_pages,
)


def _payload(page_no: int, *, total_count: int, record_id: str) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "items": [
                    {
                        "cntrctDlvrDivNm": "납품요구",
                        "cntrctDlvrReqDate": "20260715",
                        "cntrctDlvrReqNo": record_id,
                        "prdctIdntNo": f"P-{record_id}",
                        "prdctIdntNoNm": f"테스트 품목 {record_id}",
                        "prdctUprc": "100000",
                        "prdctQty": "1",
                        "prdctUnit": "대",
                        "prdctAmt": "100000",
                    }
                ],
                "numOfRows": 1,
                "pageNo": page_no,
                "totalCount": total_count,
            },
        }
    }


class StubCollector:
    def __init__(self, payloads: dict[int, dict]) -> None:
        self.payloads = payloads
        self.requested_pages: list[int] = []

    def fetch_specific_item_page(self, **kwargs):
        page_no = kwargs["page_no"]
        self.requested_pages.append(page_no)
        payload = self.payloads[page_no]
        return unwrap_g2b_page(payload), payload


def test_pagination_uses_total_count_and_stops_after_complete_page_set() -> None:
    collector = StubCollector(
        {
            1: _payload(1, total_count=2, record_id="DLVR-1"),
            2: _payload(2, total_count=2, record_id="DLVR-2"),
        }
    )

    pages = list(
        iter_specific_item_pages(
            collector,
            detail_product_name="테스트",
            begin_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            num_of_rows=1,
            max_pages=5,
        )
    )

    assert len(pages) == 2
    assert collector.requested_pages == [1, 2]


def test_pagination_fails_closed_when_safety_cap_would_truncate() -> None:
    collector = StubCollector({1: _payload(1, total_count=3, record_id="DLVR-1")})

    with pytest.raises(PublicDataClientError, match="pagination safety limit"):
        list(
            iter_specific_item_pages(
                collector,
                detail_product_name="테스트",
                begin_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
                num_of_rows=1,
                max_pages=1,
            )
        )


def test_paginated_collection_persists_raw_evidence_idempotently() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    payloads = {
        1: _payload(1, total_count=2, record_id="DLVR-1"),
        2: _payload(2, total_count=2, record_id="DLVR-2"),
    }

    with Session(engine) as session:
        first_run = start_collection_run(session, source_name=SOURCE_NAME, query_text="테스트")
        first = collect_specific_item_history(
            session,
            collector=StubCollector(payloads),
            run=first_run,
            detail_product_name="테스트",
            begin_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            num_of_rows=1,
            max_pages=5,
        )

        second_run = start_collection_run(session, source_name=SOURCE_NAME, query_text="테스트")
        second = collect_specific_item_history(
            session,
            collector=StubCollector(payloads),
            run=second_run,
            detail_product_name="테스트",
            begin_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            num_of_rows=1,
            max_pages=5,
        )

        evidence = session.scalars(select(RawEvidence)).all()

        assert first.pages_fetched == 2
        assert first.records_seen == 2
        assert first.evidence_created == 2
        assert first.duplicates_seen == 0
        assert first.reported_total_count == 2
        assert second.pages_fetched == 2
        assert second.records_seen == 2
        assert second.evidence_created == 0
        assert second.duplicates_seen == 2
        assert len(evidence) == 2
        assert {row.source_record_id for row in evidence} == {"DLVR-1", "DLVR-2"}
