from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.scripts.capture_track_b_r2_ground_truth import (
    capture_candidates,
    write_capture,
)


def _line(
    *,
    delivery: str,
    change: int,
    sequence: str,
    title: str,
    model_key: str | None,
    model_name: str | None,
    manufacturer: str | None = None,
    conflict: bool = False,
    when: date = date(2026, 9, 1),
) -> TrackBDeliveryLine:
    return TrackBDeliveryLine(
        delivery_request_number=delivery,
        change_order=str(change),
        change_order_number=change,
        product_sequence=sequence,
        item_sha256=f"{delivery}-{change}-{sequence}".ljust(64, "0")[:64],
        identity_conflict=conflict,
        identity_conflict_count=1 if conflict else 0,
        raw_object_key=f"raw/v1/{delivery}-{change}-{sequence}.json.gz",
        raw_payload_sha256=("a" * 63) + str(change % 10),
        detail_code="4227220901",
        product_id=f"P-{delivery}-{sequence}",
        product_title=title,
        product_class="인공호흡기",
        class_key="인공호흡기",
        manufacturer=manufacturer,
        manufacturer_qualifier=None,
        model_name=model_name,
        model_qualifier=None,
        model_qualifier_verified_as_origin=False,
        model_key=model_key,
        specification=None,
        unit_price=None,
        quantity=None,
        unit=None,
        total_amount=None,
        amount_check="not_checked",
        transaction_date=when,
        supplier=None,
        demand_institution=None,
        api_params_json="{}",
    )


def _write_products(path: Path) -> None:
    path.write_text(
        "category,manufacturer,product_name,model_name,specification,status,notes\n"
        "의료장비,Stephan,인공호흡기,Sophie,Sophie,benchmark 확정,test\n"
        "의료장비,Vendor,시험장비,TEST-123,,benchmark 확정,test\n",
        encoding="utf-8",
    )


def _write_ground_truth(path: Path) -> None:
    path.write_text(
        "benchmark_model,source_name,source_record_id,candidate_title,expected_grade,review_note,evidence_url\n"
        'Sophie,g2b,"delivery:D-EXIST|change:0|line:1","인공호흡기, Stephan, Sophie",A,test,https://example.test\n',
        encoding="utf-8",
    )


def test_capture_uses_current_nonconflict_rows_and_excludes_existing_ground_truth(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    products = tmp_path / "products.csv"
    truth = tmp_path / "truth.csv"
    _write_products(products)
    _write_ground_truth(truth)

    with Session(engine) as session:
        session.add_all(
            [
                _line(
                    delivery="D-EXIST",
                    change=0,
                    sequence="1",
                    title="인공호흡기, Stephan, Sophie",
                    model_key="sophie",
                    model_name="Sophie",
                    manufacturer="Stephan",
                ),
                _line(
                    delivery="D-NEW",
                    change=0,
                    sequence="1",
                    title="인공호흡기, Stephan, Sophie, 운반형",
                    model_key="sophie",
                    model_name="Sophie",
                    manufacturer="Stephan",
                ),
                _line(
                    delivery="D-CONFLICT",
                    change=0,
                    sequence="1",
                    title="인공호흡기, Stephan, Sophie, conflict",
                    model_key="sophie",
                    model_name="Sophie",
                    manufacturer="Stephan",
                    conflict=True,
                ),
                _line(
                    delivery="D-SUPER",
                    change=0,
                    sequence="1",
                    title="시험장비, Vendor, TEST-123",
                    model_key="test123",
                    model_name="TEST-123",
                ),
                _line(
                    delivery="D-SUPER",
                    change=1,
                    sequence="1",
                    title="시험장비, Vendor, OTHER-999",
                    model_key="other999",
                    model_name="OTHER-999",
                    when=date(2026, 9, 2),
                ),
                _line(
                    delivery="D-TITLE",
                    change=0,
                    sequence="1",
                    title="시험장비 Vendor TEST-123 특수형",
                    model_key=None,
                    model_name=None,
                ),
            ]
        )
        session.commit()

        rows, summary = capture_candidates(
            session,
            products_path=products,
            ground_truth_path=truth,
            max_per_model=10,
        )

    sophie = [row for row in rows if row["benchmark_model"] == "Sophie"]
    test_model = [row for row in rows if row["benchmark_model"] == "TEST-123"]

    assert len(sophie) == 1
    assert sophie[0]["source_record_id"] == "delivery:D-NEW|change:0|line:1"
    assert sophie[0]["candidate_match_basis"] == "parsed_model_exact"
    assert sophie[0]["expected_grade"] == ""
    assert sophie[0]["review_note"] == ""

    assert len(test_model) == 1
    assert test_model[0]["source_record_id"] == "delivery:D-TITLE|change:0|line:1"
    assert test_model[0]["candidate_match_basis"] == "title_model_literal"

    assert summary["model_count"] == 2
    assert summary["models_with_candidates"] == 2
    assert summary["candidate_row_count"] == 2
    assert summary["existing_ground_truth_pairs_excluded"] == 1
    assert summary["safety_contract"]["g2b_live_api_requests"] == 0
    assert summary["safety_contract"]["predicted_grade_written"] is False


def test_capture_dedupes_repeated_identity_titles(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TrackBDeliveryLine.__table__])
    products = tmp_path / "products.csv"
    truth = tmp_path / "truth.csv"
    _write_products(products)
    truth.write_text(
        "benchmark_model,source_name,source_record_id,candidate_title,expected_grade,review_note,evidence_url\n",
        encoding="utf-8",
    )

    with Session(engine) as session:
        session.add_all(
            [
                _line(
                    delivery="D-1",
                    change=0,
                    sequence="1",
                    title="인공호흡기, Stephan, Sophie",
                    model_key="sophie",
                    model_name="Sophie",
                    manufacturer="Stephan",
                ),
                _line(
                    delivery="D-2",
                    change=0,
                    sequence="1",
                    title="인공호흡기, Stephan, Sophie",
                    model_key="sophie",
                    model_name="Sophie",
                    manufacturer="Stephan",
                    when=date(2026, 9, 2),
                ),
            ]
        )
        session.commit()
        rows, _ = capture_candidates(
            session,
            products_path=products,
            ground_truth_path=truth,
            max_per_model=10,
        )

    assert len([row for row in rows if row["benchmark_model"] == "Sophie"]) == 1


def test_write_capture_keeps_human_review_fields_blank(tmp_path: Path) -> None:
    rows = [
        {
            "benchmark_model": "Sophie",
            "benchmark_manufacturer": "Stephan",
            "benchmark_product_name": "인공호흡기",
            "source_name": "g2b",
            "source_record_id": "delivery:1|change:0|line:1",
            "candidate_title": "인공호흡기, Stephan, Sophie",
            "candidate_match_basis": "parsed_model_exact",
            "parsed_manufacturer": "Stephan",
            "parsed_model_name": "Sophie",
            "parsed_product_class": "인공호흡기",
            "detail_code": "4227220901",
            "transaction_date": "2026-09-01",
            "raw_object_key": "raw/v1/x.json.gz",
            "expected_grade": "",
            "review_note": "",
        }
    ]
    summary = {"schema": "test"}
    csv_path = tmp_path / "candidates.csv"
    summary_path = tmp_path / "summary.json"

    write_capture(
        rows=rows,
        summary=summary,
        csv_path=csv_path,
        summary_path=summary_path,
    )

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        parsed = list(csv.DictReader(handle))

    assert parsed[0]["expected_grade"] == ""
    assert parsed[0]["review_note"] == ""
    assert summary_path.exists()
