from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.scripts.validate_g2b_track_b_db_live import _find_comparison_case
from purchase_price.services.g2b_track_b_normalization import (
    TrackBIdentityConflictError,
    TrackBRawPage,
)
from purchase_price.services.track_b_db_quote_comparison import (
    compare_track_b_quote,
    ingest_track_b_page,
    lookup_track_b_quote,
)


def _item(*, change: str = "00", price: str | None = "90", title: str | None = None):
    item = {
        "cntrctDlvrReqNo": "REQ-1",
        "cntrctDlvrReqChgOrd": change,
        "prdctSno": "1",
        "dtilPrdctClsfcNo": "4010190201",
        "prdctIdntNoNm": title or "제습기, 나우이엘, MA-045DT, 45L/d",
        "prdctQty": "1",
        "prdctAmt": price or "90",
        "cntrctDlvrReqDate": "20260901",
    }
    if price is not None:
        item["prdctUprc"] = price
    return item


def _page(items: list[dict[str, str]]) -> TrackBRawPage:
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
            "response": {"items": items},
        },
        raw_object_key="raw/v1/getSpcifyPrdlstPrcureInfoList-page/test.json.gz",
        raw_payload_sha256="a" * 64,
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def _query(model: str = "MA-045DT") -> ProductQuery:
    return ProductQuery(
        product_name="제습기",
        manufacturer="나우이엘",
        model_name=model,
        specification="45L/d",
    )


def test_upload_comparison_uses_only_latest_explicit_unit_price(session: Session) -> None:
    ingest_track_b_page(session, _page([_item(change="00", price="80")]))
    ingest_track_b_page(session, _page([_item(change="01", price="90")]))
    session.commit()

    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))

    assert result.status == "success"
    assert len(result.candidates) == 1
    assert result.candidates[0].price == Decimal("90")
    assert result.candidates[0].delta_percent == Decimal("11.1")
    assert result.candidates[0].source_record_id == "delivery:REQ-1|change:01|line:1"
    assert result.candidates[0].raw_object_key.endswith("test.json.gz")
    assert len(session.scalars(select(TrackBDeliveryLine)).all()) == 2


def test_replay_is_idempotent_and_divergent_identity_fails_closed(session: Session) -> None:
    first = _page([_item()])
    assert ingest_track_b_page(session, first).inserted == 1
    assert ingest_track_b_page(session, first).replayed == 1
    changed = _item()
    changed["prdctUprc"] = "91"
    with pytest.raises(TrackBIdentityConflictError):
        ingest_track_b_page(session, _page([changed]))
    assert len(session.scalars(select(TrackBDeliveryLine)).all()) == 1


def test_missing_or_zero_unit_price_is_not_displayed(session: Session) -> None:
    missing = _item(price=None)
    zero = _item(change="01", price="0")
    ingest_track_b_page(session, _page([missing, zero]))
    session.commit()

    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))

    assert result.status == "success_0"
    assert result.candidates == ()


def test_model_prefix_is_not_promoted_to_price_comparison(session: Session) -> None:
    ingest_track_b_page(session, _page([_item(title="제습기, 나우이엘, MA-045DTX, 45L/d")]))
    session.commit()

    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))

    assert result.status == "success_0"
    assert result.candidates == ()


def test_latest_change_without_unit_price_suppresses_older_price(session: Session) -> None:
    ingest_track_b_page(session, _page([_item(change="00", price="80")]))
    ingest_track_b_page(session, _page([_item(change="01", price=None)]))
    session.commit()

    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))
    assert result.status == "success_0"


def test_numeric_change_order_collision_is_explicit(session: Session) -> None:
    ingest_track_b_page(session, _page([_item(change="00")]))
    with pytest.raises(TrackBIdentityConflictError):
        ingest_track_b_page(session, _page([_item(change="0")]))


def test_missing_db_is_unavailable_not_zero_results(monkeypatch) -> None:
    from purchase_price import db

    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(db, "SessionLocal", lambda: Session(engine))
    result = lookup_track_b_quote(_query(), quote_unit_price=Decimal("100"))
    assert result.status == "unavailable"
    engine.dispose()


def test_empty_db_is_not_reported_as_successful_zero_match(session: Session) -> None:
    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))
    assert result.status == "not_ingested"


def test_unverified_model_qualifier_does_not_become_same_model_price(session: Session) -> None:
    ingest_track_b_page(
        session, _page([_item(title="제습기, 나우이엘, (임의접두어)MA-045DT, 45L/d")])
    )
    session.commit()

    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))
    assert result.status == "success_0"


def test_verified_origin_qualifier_remains_eligible(session: Session) -> None:
    ingest_track_b_page(session, _page([_item(title="제습기, 나우이엘, (VN)MA-045DT, 45L/d")]))
    session.commit()

    result = compare_track_b_quote(session, _query(), quote_unit_price=Decimal("100"))
    assert len(result.candidates) == 1
    assert result.candidates[0].delta_percent == Decimal("11.1")


def test_live_validation_selects_searchable_current_row_not_superseded_row(
    session: Session,
) -> None:
    ingest_track_b_page(
        session, _page([_item(change="00", title="제습기, 나우이엘, OLD-MODEL, 45L/d")])
    )
    ingest_track_b_page(
        session, _page([_item(change="01", title="제습기, 나우이엘, NEW-MODEL, 45L/d")])
    )
    session.commit()

    sample, _, comparison = _find_comparison_case(session)
    assert sample.model_name == "NEW-MODEL"
    assert comparison.candidates
