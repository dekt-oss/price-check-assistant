from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import TrackBQuoteComparison
from purchase_price.services.track_b_reference_quality import refine_track_b_reference_quality


def _line(
    *,
    request: str,
    detail_code: str,
    product_class: str,
    title: str,
    model: str | None = None,
    manufacturer: str | None = None,
    price: str = "1000000",
) -> TrackBDeliveryLine:
    return TrackBDeliveryLine(
        delivery_request_number=request,
        change_order="00",
        change_order_number=0,
        product_sequence="1",
        item_sha256=(request[-1:] or "a") * 64,
        identity_conflict=False,
        identity_conflict_count=0,
        raw_object_key=f"raw/{request}.json.gz",
        raw_payload_sha256="b" * 64,
        detail_code=detail_code,
        product_id=None,
        product_title=title,
        product_class=product_class,
        class_key=normalize_text(product_class),
        manufacturer=manufacturer,
        manufacturer_qualifier=None,
        model_name=model,
        model_qualifier=None,
        model_qualifier_verified_as_origin=False,
        model_key=normalize_text(model) or None,
        specification=None,
        unit_price=Decimal(price),
        quantity=Decimal("1"),
        unit="EA",
        total_amount=Decimal(price),
        amount_check="consistent",
        transaction_date=date(2026, 8, 1),
        supplier="공급사",
        demand_institution="수요기관",
        api_params_json="{}",
    )


def _zero_result(*, old_reference=()) -> TrackBQuoteComparison:
    return TrackBQuoteComparison(
        status="success_0",
        candidates=(),
        examined=0,
        reference_candidates=tuple(old_reference),
    )


def test_verified_detail_code_is_preferred_for_category_reference() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                _line(
                    request="REQ-A",
                    detail_code="4110630701",
                    product_class="유전자증폭기",
                    title="유전자증폭기, Applied Biosystems, SimpliAmp Thermal Cycler",
                    model="SimpliAmp Thermal Cycler",
                    price="8200000",
                ),
                _line(
                    request="REQ-B",
                    detail_code="9999999999",
                    product_class="실험실장비",
                    title="Veriti 관련 액세서리",
                    price="10000",
                ),
            ]
        )
        session.commit()
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(
                product_name="핵산증폭기",
                manufacturer="Thermo Fisher Scientific",
                model_name="Veriti Pro Dx",
            ),
            _zero_result(),
        )

    engine.dispose()
    assert len(refined.reference_candidates) == 1
    reference = refined.reference_candidates[0]
    assert reference.price == Decimal("8200000.00")
    assert "4110630701" in reference.reference_reason
    assert "동일 세부품명 참고" in reference.reference_reason
    assert reference.reference_scope == "SAME_CLASS"


def test_weak_roman_token_does_not_create_exoatlet_false_positive() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            _line(
                request="REQ-C",
                detail_code="4210000001",
                product_class="재활장비",
                title="II형 재활훈련장비",
                price="25000000",
            )
        )
        session.commit()
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(product_name="엑소아틀레트 - II"),
            _zero_result(old_reference=(object(),)),
        )

    engine.dispose()
    assert refined.reference_candidates == ()


def test_product_fallback_requires_strong_combined_tokens() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                _line(
                    request="REQ-D",
                    detail_code="4321190201",
                    product_class="모니터",
                    title="일반 사무용 모니터",
                    price="300000",
                ),
                _line(
                    request="REQ-E",
                    detail_code="4219000001",
                    product_class="의료영상표시장치",
                    title="영상 판독용 의료 모니터",
                    price="8500000",
                ),
            ]
        )
        session.commit()
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(product_name="영상 판독용 모니터", model_name="CX30N"),
            _zero_result(),
        )

    engine.dispose()
    assert len(refined.reference_candidates) == 1
    assert refined.reference_candidates[0].price == Decimal("8500000.00")
    assert "판독용" in refined.reference_candidates[0].reference_reason
    assert "모니터" in refined.reference_candidates[0].reference_reason


def test_existing_strict_candidate_result_is_never_rewritten() -> None:
    original = TrackBQuoteComparison(status="success", candidates=(object(),), examined=1)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(product_name="아무품목"),
            original,
        )
    engine.dispose()
    assert refined is original


def test_verified_class_prefers_same_manufacturer_scope() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                _line(
                    request="REQ-M1",
                    detail_code="4110630701",
                    product_class="유전자증폭기",
                    title="유전자증폭기, Thermo fisher scientific, QuantStudio 5",
                    model="QuantStudio 5",
                    manufacturer="Thermo fisher scientific",
                    price="15000000",
                ),
                _line(
                    request="REQ-M2",
                    detail_code="4110630701",
                    product_class="유전자증폭기",
                    title="유전자증폭기, Bio-rad, CFX Opus 96",
                    model="CFX Opus 96",
                    manufacturer="Bio-rad",
                    price="12000000",
                ),
            ]
        )
        session.commit()
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(
                product_name="핵산증폭기",
                manufacturer="Thermo Fisher Scientific",
                model_name="Veriti Pro Dx",
            ),
            _zero_result(),
        )

    engine.dispose()
    assert len(refined.reference_candidates) == 1
    reference = refined.reference_candidates[0]
    assert reference.reference_scope == "SAME_MANUFACTURER_CLASS"
    assert "동일 제조사·동일 세부품명 참고" in reference.reference_reason


def test_strong_model_reference_has_unverified_same_model_scope() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            _line(
                request="REQ-SM",
                detail_code="4111581101",
                product_class="DNA서열분석기",
                title="DNA서열분석기, Oxford nanopore technologies, (GB)MinION MK1D",
                model="MinION Mk1D",
                manufacturer="Oxford nanopore technologies",
                price="13310000",
            )
        )
        session.commit()
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(
                product_name="염기서열분석기",
                manufacturer="Oxford Nanopore",
                model_name="MinION Mk1D",
            ),
            _zero_result(),
        )

    engine.dispose()
    assert refined.reference_candidates[0].reference_scope == "SAME_MODEL_UNVERIFIED"


def test_keyword_fallback_is_labeled_keyword_scope() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            _line(
                request="REQ-KW",
                detail_code="4219000001",
                product_class="의료영상표시장치",
                title="영상 판독용 의료 모니터",
                price="8500000",
            )
        )
        session.commit()
        refined = refine_track_b_reference_quality(
            session,
            ProductQuery(product_name="영상 판독용 모니터", model_name="CX30N"),
            _zero_result(),
        )

    engine.dispose()
    assert refined.reference_candidates[0].reference_scope == "KEYWORD"
