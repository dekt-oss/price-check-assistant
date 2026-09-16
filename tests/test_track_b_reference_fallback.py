from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote


def _line(*, model: str, product_class: str, title: str) -> TrackBDeliveryLine:
    return TrackBDeliveryLine(
        delivery_request_number=f"REQ-{model}",
        change_order="00",
        change_order_number=0,
        product_sequence="1",
        item_sha256="a" * 64,
        identity_conflict=False,
        identity_conflict_count=0,
        raw_object_key=f"raw/{model}.json.gz",
        raw_payload_sha256="b" * 64,
        detail_code="4218200101",
        product_id=None,
        product_title=title,
        product_class=product_class,
        class_key=normalize_text(product_class),
        manufacturer="Maquet",
        manufacturer_qualifier=None,
        model_name=model,
        model_qualifier=None,
        model_qualifier_verified_as_origin=False,
        model_key=normalize_text(model),
        specification="SET",
        unit_price=Decimal("60000000"),
        quantity=Decimal("1"),
        unit="SET",
        total_amount=Decimal("60000000"),
        amount_check="consistent",
        transaction_date=date(2026, 8, 1),
        supplier="의료기기공급사",
        demand_institution="테스트대학병원",
        api_params_json="{}",
    )


def test_exact_trade_exposes_supplier_buyer_and_quantity() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            _line(
                model="FLOW-C",
                product_class="가스마취기",
                title="가스마취기, Maquet, FLOW-C, SET",
            )
        )
        session.commit()
        result = compare_track_b_quote(
            session,
            ProductQuery(
                product_name="가스마취기",
                manufacturer="Maquet",
                model_name="FLOW-C",
                specification="SET",
            ),
            quote_unit_price=Decimal("66000000"),
        )

    engine.dispose()
    assert result.candidates
    candidate = result.candidates[0]
    assert candidate.supplier == "의료기기공급사"
    assert candidate.demand_institution == "테스트대학병원"
    assert candidate.quantity == Decimal("1.000")
    assert candidate.unit == "SET"
    assert candidate.transaction_type == "나라장터 납품요구"


def test_zero_strict_match_returns_price_as_reference_only() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            _line(
                model="OTHER-1",
                product_class="마취기",
                title="마취기, Maquet, OTHER-1, SET",
            )
        )
        session.commit()
        result = compare_track_b_quote(
            session,
            ProductQuery(
                product_name="가스 마취기 (Anesthesia Machine)",
                manufacturer="Maquet",
                model_name="FLOW-X",
                specification="SET",
            ),
            quote_unit_price=Decimal("66000000"),
        )

    engine.dispose()
    assert result.status == "success_0"
    assert result.candidates == ()
    assert result.reference_candidates
    reference = result.reference_candidates[0]
    assert reference.price == Decimal("60000000.00")
    assert reference.supplier == "의료기기공급사"
    assert reference.demand_institution == "테스트대학병원"
    assert "참고" in reference.reference_reason
    assert not hasattr(reference, "delta_percent")
