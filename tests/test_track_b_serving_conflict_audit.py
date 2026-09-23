from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.audit_track_b_serving_conflicts import audit_conflict_rows


def _row(
    *,
    request: str,
    conflict: bool,
    conflict_count: int,
    detail_code: str = "4217210101",
    supplier: str = "공급사A",
    unit_price: Decimal | None = Decimal("100"),
) -> TrackBDeliveryLine:
    return TrackBDeliveryLine(
        delivery_request_number=request,
        change_order="00",
        change_order_number=0,
        product_sequence="1",
        item_sha256="a" * 64,
        identity_conflict=conflict,
        identity_conflict_count=conflict_count,
        raw_object_key=f"raw/v1/test/{request}.json.gz",
        raw_payload_sha256="b" * 64,
        detail_code=detail_code,
        product_id="12345678",
        product_title="심장충격기, Example, MODEL-1",
        product_class="심장충격기",
        class_key="심장충격기",
        manufacturer="Example",
        manufacturer_qualifier=None,
        model_name="MODEL-1",
        model_qualifier=None,
        model_qualifier_verified_as_origin=False,
        specification="200J",
        model_key="model1",
        unit_price=unit_price,
        quantity=Decimal("1"),
        unit="대",
        total_amount=unit_price,
        amount_check="consistent",
        transaction_date=date(2026, 8, 21),
        supplier=supplier,
        demand_institution="병원A",
        contract_delivery_type="일반납품",
        contract_type="단가계약",
        delivery_condition="현장설치도",
        api_params_json="{}",
    )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_audit_conflict_rows_reports_quarantined_scope(session: Session) -> None:
    session.add_all(
        [
            _row(request="R1", conflict=True, conflict_count=3),
            _row(
                request="R2",
                conflict=True,
                conflict_count=1,
                detail_code="4217210201",
                supplier="공급사B",
                unit_price=None,
            ),
            _row(request="R3", conflict=False, conflict_count=0),
        ]
    )
    session.commit()

    report = audit_conflict_rows(session, sample_limit=10)

    assert report["status"] == "CONFLICTS_PRESENT"
    assert report["conflict_row_count"] == 2
    assert report["conflict_event_count"] == 4
    assert report["max_conflicts_for_one_identity"] == 3
    assert report["priced_conflict_row_count"] == 1
    assert report["top_detail_codes"] == [
        ("4217210101", 1),
        ("4217210201", 1),
    ]
    assert report["samples"][0]["source_record_id"] == "delivery:R1|change:00|line:1"
    assert report["samples"][0]["unit_price"] == "100.00"
    assert "fail-closed" in report["interpretation"]


def test_audit_conflict_rows_clean_index(session: Session) -> None:
    session.add(_row(request="R1", conflict=False, conflict_count=0))
    session.commit()

    report = audit_conflict_rows(session)

    assert report["status"] == "CLEAN"
    assert report["conflict_row_count"] == 0
    assert report["conflict_event_count"] == 0
    assert report["max_conflicts_for_one_identity"] == 0
    assert report["samples"] == []


def test_audit_conflict_rows_requires_positive_sample_limit(session: Session) -> None:
    with pytest.raises(ValueError, match="sample_limit"):
        audit_conflict_rows(session, sample_limit=0)
