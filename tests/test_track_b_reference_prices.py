from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.domain import MatchGrade
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote
from purchase_price.services.track_b_reference_prices import add_same_class_reference_prices


def _row(*, request: str, product_class: str, model: str, price: str) -> TrackBDeliveryLine:
    return TrackBDeliveryLine(
        delivery_request_number=request,
        change_order="00",
        change_order_number=0,
        product_sequence="1",
        item_sha256=(request[-1] * 64),
        identity_conflict=False,
        identity_conflict_count=0,
        raw_object_key=f"raw/v1/test/{request}.json.gz",
        raw_payload_sha256=(request[-1] * 64),
        detail_code="4010190201",
        product_id=f"P-{request}",
        product_title=f"{product_class}, 나우이엘, {model}, 45L/d",
        product_class=product_class,
        class_key=normalize_text(product_class),
        manufacturer="나우이엘",
        manufacturer_qualifier=None,
        model_name=model,
        model_qualifier=None,
        model_qualifier_verified_as_origin=False,
        model_key=normalize_text(model),
        specification="45L/d",
        unit_price=Decimal(price),
        quantity=Decimal("1"),
        unit="대",
        total_amount=Decimal(price),
        amount_check="consistent",
        transaction_date=date(2026, 9, 1),
        supplier="테스트공급사",
        demand_institution="테스트기관",
        api_params_json="{}",
    )


def _query(model: str) -> ProductQuery:
    return ProductQuery(
        product_name="제습기",
        manufacturer="나우이엘",
        model_name=model,
        specification="45L/d",
    )


def test_zero_exact_model_gets_reference_only_same_class_prices() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_row(request="REQ1", product_class="제습기", model="MA-045DT", price="900000"))
        session.add(_row(request="REQ2", product_class="공기청정기", model="AIR-100", price="500000"))
        session.commit()

        query = _query("MA-999ZZ")
        strict = compare_track_b_quote(session, query, quote_unit_price=Decimal("1000000"))
        assert strict.status == "success_0"

        result = add_same_class_reference_prices(session, query, strict)

    engine.dispose()
    assert result.status == "reference"
    assert len(result.candidates) == 1
    assert result.candidates[0].product_title.startswith("제습기")
    assert result.candidates[0].match_grade is MatchGrade.C
    assert result.candidates[0].delta_percent is None
    assert "not eligible for direct quote comparison" in result.candidates[0].match_note


def test_exact_model_result_is_never_replaced_by_reference_prices() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_row(request="REQ3", product_class="제습기", model="MA-045DT", price="900000"))
        session.add(_row(request="REQ4", product_class="제습기", model="MA-060DT", price="1200000"))
        session.commit()

        query = _query("MA-045DT")
        strict = compare_track_b_quote(session, query, quote_unit_price=Decimal("1000000"))
        result = add_same_class_reference_prices(session, query, strict)

    engine.dispose()
    assert strict.status == "success"
    assert result == strict
    assert result.candidates[0].match_grade in {MatchGrade.A, MatchGrade.B}
