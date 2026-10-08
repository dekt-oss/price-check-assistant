from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.schemas import ProductQuery
from purchase_price.scripts import sync_g2b_track_b_r2_index as sync_script
from purchase_price.services import track_b_db_quote_comparison as comparison
from purchase_price.services.g2b_track_b_normalization import TrackBRawPage
from purchase_price.storage.r2_serving_index import (
    SERVING_INDEX_SCHEMA,
    SUPPORTED_SERVING_INDEX_SCHEMAS,
)
from purchase_price.ui import result_summary
from purchase_price.ui.track_b_transactions import direct_transaction_rows

BUSINESS = "2026년 중환자실 환자감시장치 구매"


def _page(business_name: str | None = BUSINESS) -> TrackBRawPage:
    item = {
        "cntrctDlvrReqNo": "R26TB0001",
        "cntrctDlvrReqChgOrd": "00",
        "prdctSno": "1",
        "dtilPrdctClsfcNo": "4010190201",
        "prdctIdntNoNm": "제습기, 나우이엘, MA-045DT, 45L/d",
        "prdctQty": "2",
        "prdctUprc": "90",
        "prdctAmt": "180",
        "cntrctDlvrReqDate": "20260901",
        "corpNm": "공급사A",
        "dminsttNm": "구매기관B",
        "prdctUnit": "대",
    }
    if business_name is not None:
        item["cntrctDlvrReqNm"] = business_name
    return TrackBRawPage(
        payload={
            "schema": "g2b-track-b-page-v1",
            "operation": "getSpcifyPrdlstPrcureInfoList",
            "request": {
                "detail_code": "4010190201",
                "begin_date": "2025-09-12",
                "end_date": "2026-09-11",
                "page_no": 1,
                "page_size": 999,
                "final_change_order_filter": "OMITTED",
            },
            "response": {"items": [item]},
        },
        raw_object_key="raw/v1/getSpcifyPrdlstPrcureInfoList-page/test.json.gz",
        raw_payload_sha256="a" * 64,
    )


def _query() -> ProductQuery:
    return ProductQuery(
        product_name="제습기", manufacturer="나우이엘", model_name="MA-045DT", specification="45L/d"
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_business_name_flows_from_the_api_into_each_trade(session: Session) -> None:
    comparison.ingest_track_b_page(session, _page())
    session.commit()

    result = comparison.compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))

    assert result.candidates[0].business_name == BUSINESS
    rows = direct_transaction_rows(result)
    assert rows[0]["사업명"] == BUSINESS
    assert result_summary.trade_table_rows(rows)[0]["사업명"] == BUSINESS


def test_business_name_does_not_change_the_conflict_fingerprint(session: Session) -> None:
    """Re-reading a page with 사업명 must replay, not conflict, against a line stored without it."""

    comparison.ingest_track_b_page(session, _page(business_name=None))
    session.commit()
    result = comparison.ingest_track_b_page(session, _page())

    assert result.conflicts == 0
    assert result.replayed == 1


def test_an_index_built_before_business_name_still_answers(session: Session) -> None:
    line = SimpleNamespace(
        contract_delivery_type="일반납품",
        contract_type="단가계약",
        delivery_condition="현장설치도",
        business_name=BUSINESS,
    )
    v2_columns = frozenset(comparison._CONDITION_COLUMNS)

    assert comparison._row_conditions(line, available=v2_columns) == (
        "일반납품",
        "단가계약",
        "현장설치도",
        None,
    )
    assert comparison._row_conditions(line, available=frozenset()) == (None, None, None, None)
    assert comparison._row_conditions(line, available=True)[3] == BUSINESS


def test_outlier_line_names_the_business_and_shortens_long_names() -> None:
    row = {"가격": "36,513,000원", "총액": "73,026,000원", "수량": "2", "단위": "set"}
    long_name = "가" * 60

    line = result_summary.outlier_line({**row, "사업명": BUSINESS}, Decimal("4400000"), "대")
    shortened = result_summary.outlier_line({**row, "사업명": long_name}, Decimal("4400000"), "대")

    assert f"사업명 「{BUSINESS}」" in line
    assert "가" * result_summary.BUSINESS_NAME_MAX_CHARS not in shortened
    assert "…」" in shortened


def test_older_serving_indexes_are_rebuilt_to_add_business_name() -> None:
    assert "business_name" in sync_script._REQUIRED_SERVING_COLUMNS
    assert SERVING_INDEX_SCHEMA == "track-b-serving-sqlite-v3"
    # The app keeps reading the v2 index it already has while the rebuild runs.
    assert "track-b-serving-sqlite-v2" in SUPPORTED_SERVING_INDEX_SCHEMAS
