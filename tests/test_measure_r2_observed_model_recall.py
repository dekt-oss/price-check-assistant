from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.domain import MatchGrade
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.measure_r2_observed_model_recall import (
    ObservedCase,
    build_report,
    select_observed_cases,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteCandidate,
    TrackBQuoteComparison,
)


def _line(
    *,
    request: str,
    detail_code: str,
    product_class: str,
    manufacturer: str,
    model: str,
    qualifier: str | None = None,
    qualifier_verified: bool = False,
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
        product_id=f"P-{request}",
        product_title=f"{product_class}, {manufacturer}, {model}",
        product_class=product_class,
        class_key=normalize_text(product_class),
        manufacturer=manufacturer,
        manufacturer_qualifier=None,
        model_name=model,
        model_qualifier=qualifier,
        model_qualifier_verified_as_origin=qualifier_verified,
        model_key=normalize_text(model),
        specification=None,
        unit_price=Decimal("1000000"),
        quantity=Decimal("1"),
        unit="EA",
        total_amount=Decimal("1000000"),
        amount_check="consistent",
        transaction_date=date(2026, 9, 1),
        supplier="공급사",
        demand_institution="수요기관",
        api_params_json="{}",
    )


def test_select_observed_cases_is_diverse_and_fail_closed() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                _line(
                    request="REQ-A",
                    detail_code="4110000001",
                    product_class="장비A",
                    manufacturer="Maker A",
                    model="Model A1",
                ),
                _line(
                    request="REQ-B",
                    detail_code="4210000002",
                    product_class="장비B",
                    manufacturer="Maker B",
                    model="Model B2",
                ),
                _line(
                    request="REQ-C",
                    detail_code="4310000003",
                    product_class="장비C",
                    manufacturer="Maker C",
                    model="수요기관규격",
                ),
                _line(
                    request="REQ-D",
                    detail_code="4410000004",
                    product_class="장비D",
                    manufacturer="Maker D",
                    model="Model D4",
                    qualifier="XX",
                    qualifier_verified=False,
                ),
                _line(
                    request="REQ-E",
                    detail_code="2710000005",
                    product_class="장비E",
                    manufacturer="Maker E",
                    model="Model E5",
                ),
            ]
        )
        session.commit()
        cases = select_observed_cases(
            session,
            target_count=2,
            excluded_models={normalize_text("Model E5")},
        )

    engine.dispose()
    assert len(cases) == 2
    assert len({case.detail_code for case in cases}) == 2
    assert all(case.model_name not in {"수요기관규격", "Model D4", "Model E5"} for case in cases)


def test_build_report_requires_every_observed_case_to_recover_source() -> None:
    cases = [
        ObservedCase(
            case_id="observed_01",
            source_record_id="delivery:REQ-A|change:00|line:1",
            detail_code="4110000001",
            product_name="장비A",
            manufacturer="Maker A",
            model_name="Model A1",
            transaction_date="2026-09-01",
            unit_price="1000000.00",
        ),
        ObservedCase(
            case_id="observed_02",
            source_record_id="delivery:REQ-B|change:00|line:1",
            detail_code="4210000002",
            product_name="장비B",
            manufacturer="Maker B",
            model_name="Model B2",
            transaction_date="2026-09-01",
            unit_price="1000000.00",
        ),
    ]

    def lookup(query, *, quote_unit_price):
        del quote_unit_price
        request = "REQ-A" if query.model_name == "Model A1" else "REQ-B"
        candidate = TrackBQuoteCandidate(
            source_record_id=f"delivery:{request}|change:00|line:1",
            product_title=f"{query.product_name}, {query.manufacturer}, {query.model_name}",
            price=Decimal("1000000"),
            match_grade=MatchGrade.A,
            match_note="exact",
            delta_percent=None,
            raw_object_key=f"raw/{request}.json.gz",
            amount_check="consistent",
            transaction_date="2026-09-01",
        )
        return TrackBQuoteComparison(
            status="success",
            candidates=(candidate,),
            examined=1,
        )

    report = build_report(
        cases,
        target_count=2,
        curated_case_count=16,
        lookup=lookup,
    )

    assert report["status"] == "SUCCESS"
    assert report["combined_case_count"] == 18
    assert report["direct_ab_count"] == 2
    assert report["source_recovered_count"] == 2


def test_build_report_fails_when_source_row_is_not_recovered() -> None:
    case = ObservedCase(
        case_id="observed_01",
        source_record_id="delivery:REQ-A|change:00|line:1",
        detail_code="4110000001",
        product_name="장비A",
        manufacturer="Maker A",
        model_name="Model A1",
        transaction_date="2026-09-01",
        unit_price="1000000.00",
    )

    def lookup(query, *, quote_unit_price):
        del query, quote_unit_price
        candidate = TrackBQuoteCandidate(
            source_record_id="delivery:OTHER|change:00|line:1",
            product_title="장비A, Maker A, Model A1",
            price=Decimal("1000000"),
            match_grade=MatchGrade.B,
            match_note="alias",
            delta_percent=None,
            raw_object_key="raw/other.json.gz",
            amount_check="consistent",
            transaction_date="2026-09-01",
        )
        return TrackBQuoteComparison(
            status="success",
            candidates=(candidate,),
            examined=1,
        )

    report = build_report(
        [case],
        target_count=1,
        curated_case_count=16,
        lookup=lookup,
    )

    assert report["status"] == "ERROR"
    assert report["direct_ab_count"] == 1
    assert report["source_recovered_count"] == 0
